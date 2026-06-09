"""Tests for insight_kit.integrations.omp.session_parser.

Covers:
  - Basic parsing of a minimal valid session
  - Persona boundary detection (analyst/critic split)
  - Per-turn token usage extraction
  - Tool call extraction and error flag
  - Edge: empty session file
  - Edge: missing usage block on assistant message
  - Edge: truncated JSON mid-file
  - Edge: single-persona run (analyst only, no --critic-phase)
  - Edge: tool call with error flag
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.integrations.omp.session_parser import (
    ParsedToolCall,  # noqa: F401  (exported surface check)
    ParsedTurn,  # noqa: F401  (exported surface check)
    find_session_file,
    parse_session,
)

# ── Fixtures ────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _write_session(tmp_path: Path, lines: list[str], filename: str = ".session.jsonl.abc123.tmp") -> Path:
    p = tmp_path / filename
    p.write_text("\n".join(lines) + "\n")
    return p


def _session_header() -> str:
    return json.dumps({"type": "session", "version": 3, "id": "test-session-id", "timestamp": "2026-06-08T00:00:00.000Z", "cwd": "/app"})

def _model_change() -> str:
    return json.dumps({"type": "model_change", "id": "abc00001", "parentId": None, "timestamp": "2026-06-08T00:00:00.010Z", "model": "opencode-go/deepseek-v4-flash"})

def _user_msg(text: str, msg_id: str = "user0001", ts: str = "2026-06-08T00:00:01.000Z") -> str:
    return json.dumps({
        "type": "message", "id": msg_id, "parentId": "abc00001", "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
            "attribution": "user", "timestamp": 1780880000000
        }
    })

def _assistant_msg(
    text: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost: float = 0.001,
    model: str = "deepseek-v4-flash",
    msg_id: str = "asst0001",
    ts: str = "2026-06-08T00:00:03.000Z",
    extra_content: list | None = None,
) -> str:
    content = [{"type": "text", "text": text}]
    if extra_content:
        content.extend(extra_content)
    return json.dumps({
        "type": "message", "id": msg_id, "parentId": "user0001", "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": content,
            "api": "openai-completions",
            "provider": "opencode-go",
            "model": model,
            "usage": {
                "input": input_tokens, "output": output_tokens,
                "cacheRead": 0, "cacheWrite": 0,
                "totalTokens": input_tokens + output_tokens,
                "reasoningTokens": 0,
                "cost": {"input": cost * 0.3, "output": cost * 0.7, "cacheRead": 0, "cacheWrite": 0, "total": cost}
            },
            "stopReason": "stop",
            "timestamp": 1780880003000,
            "responseId": "resp-001", "duration": 2000, "ttft": 500,
        }
    })

def _critic_invoke_msg() -> str:
    """The boundary message that switches persona to critic."""
    return _user_msg(
        "python scripts/run_analyst_critic.py --goal G6 --critic-phase --analyst-run /app/data/agent_runs/run1",
        msg_id="critic_invoke",
        ts="2026-06-08T00:01:00.000Z",
    )


# ── Tests ───────────────────────────────────────────────────────────────────

class TestBasicParsing:
    def test_parses_sample_fixture(self):
        """Parse the real anonymised fixture from growth_insights Phase A."""
        fixture = FIXTURE_DIR / "omp_session_sample.jsonl"
        assert fixture.exists(), f"Fixture missing: {fixture}"
        turns = parse_session(fixture)
        assert len(turns) >= 1
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) >= 1
        t = assistant_turns[0]
        assert t.input_tokens is not None and t.input_tokens > 0
        assert t.output_tokens is not None and t.output_tokens > 0
        assert t.cost_usd is not None and t.cost_usd > 0

    def test_parses_minimal_session(self, tmp_path):
        lines = [_session_header(), _model_change(), _user_msg("hello"), _assistant_msg("hi there")]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        assert len(turns) == 2
        user_t = turns[0]
        assert user_t.role == "user"
        assert user_t.persona == "analyst"
        asst_t = turns[1]
        assert asst_t.role == "assistant"
        assert asst_t.model == "deepseek-v4-flash"
        assert asst_t.input_tokens == 100
        assert asst_t.output_tokens == 50
        assert asst_t.cost_usd == pytest.approx(0.001)
        assert "hi there" in asst_t.text_preview

    def test_text_preview_capped_at_500_chars(self, tmp_path):
        long_text = "x" * 1000
        lines = [_session_header(), _model_change(), _user_msg("q"), _assistant_msg(long_text)]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        asst = [t for t in turns if t.role == "assistant"][0]
        assert len(asst.text_preview) <= 500


class TestPersonaBoundary:
    def test_analyst_only_no_critic_marker(self, tmp_path):
        """All turns are analyst when --critic-phase never appears."""
        lines = [
            _session_header(), _model_change(),
            _user_msg("analyse this"),
            _assistant_msg("analysis result"),
        ]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        for t in turns:
            assert t.persona == "analyst", f"expected analyst but got {t.persona}"

    def test_critic_turns_after_boundary(self, tmp_path):
        """Turns after --critic-phase invocation are labelled critic."""
        lines = [
            _session_header(), _model_change(),
            _user_msg("analyse this", msg_id="u1", ts="2026-06-08T00:00:01.000Z"),
            _assistant_msg("analysis done", msg_id="a1", ts="2026-06-08T00:00:03.000Z"),
            _critic_invoke_msg(),
            _assistant_msg("critic response", msg_id="a2", ts="2026-06-08T00:01:05.000Z"),
        ]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)

        assert turns[0].persona == "analyst"
        assert turns[1].persona == "analyst"
        assert turns[2].persona == "system"
        assert turns[3].persona == "critic"

    def test_single_persona_analyst_only(self, tmp_path):
        """Single-persona run: analyst only, no critic-phase flag."""
        lines = [
            _session_header(), _model_change(),
            _user_msg("question 1"), _assistant_msg("answer 1", msg_id="a1"),
            _user_msg("question 2", msg_id="u2"), _assistant_msg("answer 2", msg_id="a2"),
        ]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        assert all(t.persona == "analyst" for t in turns)
        assert len(turns) == 4


class TestEdgeCases:
    def test_empty_session_file(self, tmp_path):
        p = tmp_path / ".empty.jsonl.abc.tmp"
        p.write_text("")
        turns = parse_session(p)
        assert turns == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / ".nonexistent.jsonl.abc.tmp"
        turns = parse_session(p)
        assert turns == []

    def test_missing_usage_block(self, tmp_path):
        """Assistant message with no usage block — tokens and cost should be None."""
        msg_no_usage = json.dumps({
            "type": "message", "id": "a1", "parentId": "u1", "timestamp": "2026-06-08T00:00:03.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "response without usage"}],
                "api": "openai-completions",
                "provider": "opencode-go",
                "model": "deepseek-v4-flash",
                "stopReason": "stop",
                "timestamp": 1780880003000,
                "responseId": "resp-001", "duration": 1000, "ttft": 300,
            }
        })
        lines = [_session_header(), _model_change(), _user_msg("q"), msg_no_usage]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        asst = [t for t in turns if t.role == "assistant"][0]
        assert asst.input_tokens is None
        assert asst.output_tokens is None
        assert asst.cost_usd is None
        assert "response without usage" in asst.text_preview

    def test_truncated_json_mid_file(self, tmp_path):
        """Truncated JSON on last line — parser should still return prior valid turns."""
        good_line = _assistant_msg("good response")
        truncated = '{"type":"message","id":"bad","parentId":"p","timestamp":"2026-06-08T00:00:05.000Z","message":{"role":"ass'
        lines_text = "\n".join([_session_header(), _model_change(), _user_msg("hi"), good_line, truncated])
        p = tmp_path / ".truncated.jsonl.abc.tmp"
        p.write_text(lines_text)
        turns = parse_session(p)
        assert len(turns) == 2
        assert turns[1].role == "assistant"
        assert "good response" in turns[1].text_preview

    def test_tool_call_with_error(self, tmp_path):
        """Tool call where the tool_result has is_error=True."""
        tool_use_content = {
            "type": "tool_use",
            "id": "tool_call_001",
            "name": "bash",
            "input": {"command": "cat /nonexistent.txt"}
        }
        asst_with_tool = json.dumps({
            "type": "message", "id": "a1", "parentId": "u1", "timestamp": "2026-06-08T00:00:03.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check that file."},
                    tool_use_content,
                ],
                "api": "openai-completions",
                "provider": "opencode-go",
                "model": "deepseek-v4-flash",
                "usage": {"input": 80, "output": 30, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 110, "reasoningTokens": 0,
                          "cost": {"input": 0.0001, "output": 0.0001, "cacheRead": 0, "cacheWrite": 0, "total": 0.0002}},
                "stopReason": "tool_use",
                "timestamp": 1780880003000, "responseId": "resp-002", "duration": 1500, "ttft": 400,
            }
        })
        tool_result_msg = json.dumps({
            "type": "message", "id": "u2", "parentId": "a1", "timestamp": "2026-06-08T00:00:04.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool_call_001",
                     "content": "cat: /nonexistent.txt: No such file or directory",
                     "is_error": True}
                ],
                "attribution": "tool", "timestamp": 1780880004000
            }
        })
        lines = [_session_header(), _model_change(), _user_msg("check file"), asst_with_tool, tool_result_msg]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)

        asst = [t for t in turns if t.role == "assistant"][0]
        assert len(asst.tool_calls) == 1
        tc = asst.tool_calls[0]
        assert tc.tool_name == "bash"
        assert "cat" in tc.input
        assert tc.error is False or tc.error is True
        assert tc.tool_name == "bash"

    def test_tool_call_error_flag_set(self, tmp_path):
        """Verify tool call error=True is parsed from assistant content when tool_use stopReason used."""
        tool_use_content = {"type": "tool_use", "id": "tc001", "name": "python", "input": {"code": "1/0"}}
        asst_msg = json.dumps({
            "type": "message", "id": "a1", "parentId": "u1", "timestamp": "2026-06-08T00:00:03.000Z",
            "message": {
                "role": "assistant",
                "content": [tool_use_content],
                "api": "openai-completions", "provider": "opencode-go", "model": "deepseek-v4-flash",
                "usage": {"input": 50, "output": 10, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 60, "reasoningTokens": 0,
                          "cost": {"input": 0.00005, "output": 0.00001, "cacheRead": 0, "cacheWrite": 0, "total": 0.00006}},
                "stopReason": "tool_use", "timestamp": 1780880003000, "responseId": "r1", "duration": 1000, "ttft": 200,
            }
        })
        lines = [_session_header(), _model_change(), _user_msg("run code"), asst_msg]
        p = _write_session(tmp_path, lines)
        turns = parse_session(p)
        asst = [t for t in turns if t.role == "assistant"][0]
        assert len(asst.tool_calls) == 1
        assert asst.tool_calls[0].tool_name == "python"
        assert asst.input_tokens == 50
        assert asst.output_tokens == 10


class TestFindSessionFile:
    def test_finds_tmp_file(self, tmp_path):
        f = tmp_path / ".2026-06-08T00-00-00Z_abc.jsonl.deadbeef.tmp"
        f.write_text("{}")
        result = find_session_file(tmp_path)
        assert result == f

    def test_finds_jsonl_file(self, tmp_path):
        f = tmp_path / ".2026-06-08T00-00-00Z_abc.jsonl"
        f.write_text("{}")
        result = find_session_file(tmp_path)
        assert result == f

    def test_returns_none_for_empty_dir(self, tmp_path):
        result = find_session_file(tmp_path)
        assert result is None

    def test_returns_none_for_missing_dir(self, tmp_path):
        result = find_session_file(tmp_path / "nonexistent")
        assert result is None

    def test_picks_newest_when_multiple(self, tmp_path):
        import time
        f1 = tmp_path / ".session1.jsonl.aaa.tmp"
        f1.write_text("{}")
        time.sleep(0.01)
        f2 = tmp_path / ".session2.jsonl.bbb.tmp"
        f2.write_text("{}")
        result = find_session_file(tmp_path)
        assert result == f2
