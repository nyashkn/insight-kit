"""session_parser.py — Parse omp v15.2.4 session JSONL into typed events.

omp writes session files as hidden `.tmp` dot-files in the --session-dir.
The file is JSONL: one JSON event per line.

Persona boundary detection:
  Scan message events sequentially. When a user-role message contains the text
  "run_analyst_critic.py --critic-phase", all turns AFTER that message are
  labelled persona="critic". Turns before = "analyst". Pre-turn-1 setup
  events (session/model_change/thinking_level_change) = "system".

Schema reference: see consumer-repo/deploy/eval/omp_session_schema.md
for the full reverse-engineered schema (v3, omp 15.2.4).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParsedToolCall:
    tool_name: str
    input: str                          # capped 2 KB
    output_preview: str                 # capped 500 chars
    duration_ms: Optional[int]
    error: bool


@dataclass
class ParsedTurn:
    role: str                           # assistant | user | system | tool
    persona: str                        # analyst | critic | system
    model: Optional[str]
    start_time: Optional[str]           # ISO 8601 (event-level timestamp)
    end_time: Optional[str]             # same as start_time (omp provides one ts per event)
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cost_usd: Optional[float]
    text_preview: str                   # first 500 chars of text content
    tool_calls: list = field(default_factory=list)  # list[ParsedToolCall]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Matches: "run_analyst_critic.py … --critic-phase" (--goal <X> may appear between)
_CRITIC_MARKER_RE = re.compile(r"run_analyst_critic\.py\b.*?--critic-phase")
_TEXT_PREVIEW_LEN = 500
_INPUT_CAP = 2048
_OUTPUT_CAP = 500


def _extract_text(content: list[dict]) -> str:
    """Concatenate text-type content items (skip thinking/tool blobs)."""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def _extract_tool_calls(content: list[dict], tool_results: list[dict]) -> list[ParsedToolCall]:
    """Extract tool_use items from content; match tool_results by tool_use_id."""
    # Build result lookup keyed by tool_use_id
    result_by_id: dict[str, dict] = {}
    for tr in tool_results:
        if isinstance(tr, dict) and tr.get("type") == "tool_result":
            tid = tr.get("tool_use_id", "")
            if tid:
                result_by_id[tid] = tr

    calls: list[ParsedToolCall] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool_use":
            continue
        tool_name = item.get("name", "unknown_tool")
        raw_input = item.get("input", {})
        input_str = json.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
        input_str = input_str[:_INPUT_CAP]

        tid = item.get("id", "")
        tr = result_by_id.get(tid, {})
        raw_output = tr.get("content", "")
        if isinstance(raw_output, list):
            raw_output = json.dumps(raw_output)
        output_preview = str(raw_output)[:_OUTPUT_CAP]
        is_error = bool(tr.get("is_error", False))

        calls.append(ParsedToolCall(
            tool_name=tool_name,
            input=input_str,
            output_preview=output_preview,
            duration_ms=None,   # omp doesn't attach per-tool duration in schema v3
            error=is_error,
        ))
    return calls


def _parse_events(lines: list[str]) -> list[dict]:
    """Parse JSONL lines into event dicts. Silently skip malformed lines."""
    events: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Truncated or corrupt line — stop here (rest of file unreadable)
            break
    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_session(session_path: Path) -> list[ParsedTurn]:
    """Parse an omp session JSONL (or .tmp) file into a list of ParsedTurn.

    Returns an empty list if the file is empty or unreadable.
    Tool-result events from subsequent user messages are matched back to the
    preceding assistant turn's tool_use items.
    """
    if not session_path.exists():
        return []

    raw = session_path.read_text(errors="replace")
    if not raw.strip():
        return []

    events = _parse_events(raw.splitlines())
    if not events:
        return []

    # --- Pass 1: determine critic-boundary index ---
    critic_start_idx: int | None = None
    for i, ev in enumerate(events):
        if ev.get("type") != "message":
            continue
        msg = ev.get("message", {})
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        full_text = _extract_text(content) if isinstance(content, list) else ""
        if _CRITIC_MARKER_RE.search(full_text):
            critic_start_idx = i
            break

    # --- Pass 2: build ParsedTurns from message events ---
    turns: list[ParsedTurn] = []
    # Collect tool_result items from user messages to attach to prior assistant turn
    pending_tool_results: list[dict] = []  # noqa: F841 (kept for future symmetry)

    for i, ev in enumerate(events):
        if ev.get("type") != "message":
            continue

        msg = ev.get("message", {})
        role = msg.get("role", "unknown")
        content = msg.get("content", [])
        if not isinstance(content, list):
            content = []

        # Persona assignment
        if critic_start_idx is None:
            persona = "analyst"
        elif i < critic_start_idx:
            persona = "analyst"
        elif i == critic_start_idx:
            persona = "system"   # the boundary message itself is the critic-phase invocation
        else:
            persona = "critic"

        ts = ev.get("timestamp")  # ISO 8601

        if role == "user":
            # Collect any tool_result content for the previous assistant turn
            tool_results_here = [
                item for item in content
                if isinstance(item, dict) and item.get("type") == "tool_result"
            ]
            if tool_results_here and turns:
                # Retroactively attach tool results to the last assistant turn
                last = turns[-1]
                for tc in last.tool_calls:
                    for tr in tool_results_here:
                        if tr.get("tool_use_id") == tc.tool_name:
                            # Update output_preview
                            raw_out = tr.get("content", "")
                            if isinstance(raw_out, list):
                                raw_out = json.dumps(raw_out)
                            tc.output_preview = str(raw_out)[:_OUTPUT_CAP]
                            tc.error = bool(tr.get("is_error", False))

            text_preview = _extract_text(content)[:_TEXT_PREVIEW_LEN]
            turns.append(ParsedTurn(
                role="user",
                persona=persona,
                model=None,
                start_time=ts,
                end_time=ts,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                text_preview=text_preview,
                tool_calls=[],
            ))

        elif role == "assistant":
            usage = msg.get("usage", {})
            cost_block = usage.get("cost", {})
            input_tokens = usage.get("input") or None
            output_tokens = usage.get("output") or None
            cost_usd = cost_block.get("total") or None

            model = msg.get("model") or None
            text_preview = _extract_text(content)[:_TEXT_PREVIEW_LEN]

            # Tool calls in this assistant message
            tool_calls = _extract_tool_calls(content, [])

            turns.append(ParsedTurn(
                role="assistant",
                persona=persona,
                model=model,
                start_time=ts,
                end_time=ts,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                text_preview=text_preview,
                tool_calls=tool_calls,
            ))

    return turns


def find_session_file(session_dir: Path) -> Path | None:
    """Find the newest session file in session_dir.

    omp writes hidden dot-files with .tmp suffix during/after a session.
    Glob for hidden files (starting with '.') to catch both .tmp and
    any finalized .jsonl files.
    """
    if not session_dir.is_dir():
        return None

    candidates: list[Path] = []
    # Hidden .tmp files (active or short sessions)
    candidates.extend(session_dir.glob(".*.tmp"))
    # Any finalized .jsonl files (long sessions that closed cleanly)
    candidates.extend(session_dir.glob(".*.jsonl"))
    # Also try non-hidden jsonl in case future omp versions change naming
    candidates.extend(session_dir.glob("*.jsonl"))

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)
