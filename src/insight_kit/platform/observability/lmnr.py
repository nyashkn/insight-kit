"""lmnr.py — Laminar (self-hosted or cloud) tracing helpers for analyst/critic runs.

Pure infrastructure. No business logic — consumers pass in their phase functions,
parsed turn list, namespace prefix, and run-dir conventions.

Helpers:
- `init_from_env()` — read LMNR_* env vars + call Laminar.initialize(). Returns True
  when tracing is active. False when LMNR_PROJECT_API_KEY is unset. Self-host vs
  cloud is determined by LMNR_BASE_URL presence (no separate flag).
- `RunIdentity` — dataclass holding run_id/git_sha/git_branch/image_digest/etc.
  Use `RunIdentity.from_env(cwd, image_name)` to capture them from the env + git.
- `emit_session_spans(parsed_turns, *, namespace)` — back-emit one LLM span per
  assistant turn + child TOOL spans, parented to the live OTel span. Returns count
  of emitted spans (0 on any failure — caller wraps in try/except).
- `score_check_span(check_name, passed, *, namespace, file_path)` — emit one
  per-check span under the active score span. Synchronous open/close.
- `read_capped(path, cap)` — capped text read for span output attachment.

All env-driven init mirrors the consumer-repo/deploy/eval/lmnr_harness.py
behavior — same env var names, same self-host vs cloud switch (LMNR_BASE_URL),
same fallback (warn + run when LMNR_PROJECT_API_KEY unset).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Lazy import guard — keep insight-kit importable without lmnr dep
# ---------------------------------------------------------------------------

def _require_lmnr() -> tuple[Any, Any]:
    """Import lmnr + opentelemetry. Raise a clean error if not installed.

    Returns (Laminar, ot_trace) so callers can use the API without re-importing.
    """
    try:
        from lmnr import Laminar
        from opentelemetry import trace as _ot_trace
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "insight_kit.platform.observability requires the `lmnr` package. "
            "Install with `pip install insight-kit[observability]`."
        ) from exc
    return Laminar, _ot_trace


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_from_env() -> bool:
    """Read LMNR_* env vars + initialise Laminar.

    Recognised env vars (read at call time):
      LMNR_PROJECT_API_KEY — REQUIRED. Tracing OFF when unset (returns False).
      LMNR_BASE_URL        — Optional. Self-host gRPC URL (scheme+host, NO port
                             in the URL string — port goes in LMNR_GRPC_PORT).
                             When unset, Laminar defaults to cloud (api.lmnr.ai).
      LMNR_BASE_HTTP_URL   — Optional. Self-host HTTP URL (scheme+host).
      LMNR_GRPC_PORT       — Optional. Integer port for gRPC base_url.
      LMNR_HTTP_PORT       — Optional. Integer port for base_http_url.

    Returns:
        True if Laminar was initialised, False if LMNR_PROJECT_API_KEY unset.

    Side effects:
        - Calls Laminar.initialize() with the resolved kwargs.
        - Prints a one-line status to stdout (flushed).
    """
    api_key = os.environ.get("LMNR_PROJECT_API_KEY")
    if not api_key:
        print("[insight-kit.lmnr] LMNR_PROJECT_API_KEY unset — tracing OFF", flush=True)
        return False

    Laminar, _ = _require_lmnr()

    init_kwargs: dict[str, Any] = {"project_api_key": api_key}
    base_url = os.environ.get("LMNR_BASE_URL")
    if base_url:
        # Self-host. LMNR_BASE_URL must be scheme+host with NO port in URL string.
        # Good: "https://laminar-grpc.internal.example.com"
        # Bad:  "https://laminar-grpc.internal.example.com:443"
        init_kwargs["base_url"] = base_url
        base_http_url = os.environ.get("LMNR_BASE_HTTP_URL")
        if base_http_url:
            init_kwargs["base_http_url"] = base_http_url
        if os.environ.get("LMNR_HTTP_PORT"):
            init_kwargs["http_port"] = int(os.environ["LMNR_HTTP_PORT"])
        if os.environ.get("LMNR_GRPC_PORT"):
            init_kwargs["grpc_port"] = int(os.environ["LMNR_GRPC_PORT"])

    Laminar.initialize(**init_kwargs)
    print(f"[insight-kit.lmnr] tracing ON  base_url={base_url or 'cloud'}", flush=True)
    return True


# ---------------------------------------------------------------------------
# Run identity
# ---------------------------------------------------------------------------

@dataclass
class RunIdentity:
    """Captured run-identity metadata. Pass to Laminar.set_trace_metadata()."""

    run_id: str
    started_at: str
    git_sha: str = "unknown"
    git_branch: str = "unknown"
    image: str | None = None
    image_digest: str | None = None
    harness_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        *,
        cwd: Path | str = "/app",
        image: str | None = None,
        harness_version: str | None = None,
    ) -> RunIdentity:
        """Capture identity from env vars + git in `cwd`.

        Reads (in order):
          RUN_ID         — preferred stable id. Falls back to a fresh uuid4.
          GIT_SHA env    — fallback when `git rev-parse HEAD` fails.
          GIT_BRANCH env — fallback when `git rev-parse --abbrev-ref HEAD` fails.
          /etc/podinfo/digest then IMAGE_DIGEST env — container image digest.
        """
        cwd_path = Path(cwd) if not isinstance(cwd, Path) else cwd

        return cls(
            run_id=os.environ.get("RUN_ID") or str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=_git_rev(["git", "rev-parse", "HEAD"], cwd=cwd_path)
            or os.environ.get("GIT_SHA", "unknown"),
            git_branch=_git_rev(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd_path)
            or os.environ.get("GIT_BRANCH", "unknown"),
            image=image,
            image_digest=_read_image_digest(),
            harness_version=harness_version,
        )

    def as_metadata(self) -> dict[str, Any]:
        """Flatten into a metadata dict suitable for Laminar.set_trace_metadata()."""
        meta: dict[str, Any] = {
            "run.id": self.run_id,
            "run.session_id": self.run_id,
            "run.git_sha": self.git_sha,
            "run.git_branch": self.git_branch,
            "started_at": self.started_at,
        }
        if self.image:
            meta["run.image"] = self.image
        if self.image_digest:
            meta["run.image_digest"] = self.image_digest
        if self.harness_version:
            meta["harness.version"] = self.harness_version
        meta.update(self.extra)
        return meta


def _git_rev(cmd: list[str], cwd: Path) -> str | None:
    """Run a git command in `cwd`. Returns stripped stdout or None on failure."""
    try:
        return subprocess.check_output(
            cmd, cwd=str(cwd), stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return None


def _read_image_digest() -> str | None:
    """Return container image digest from /etc/podinfo/digest or IMAGE_DIGEST env."""
    podinfo = Path("/etc/podinfo/digest")
    if podinfo.exists():
        try:
            return podinfo.read_text().strip()
        except Exception:
            pass
    return os.environ.get("IMAGE_DIGEST") or None


# ---------------------------------------------------------------------------
# Per-turn span back-emit (Stage-2: omp session axis 4/5/6)
# ---------------------------------------------------------------------------

def emit_session_spans(
    parsed_turns: list,
    *,
    namespace: str = "omp",
    gen_ai_system: str = "opencode-go",
) -> int:
    """Emit one LLM span per parsed turn (+ child TOOL spans), parented to live span.

    `parsed_turns` must be a list of objects with the ParsedTurn protocol:
      role, persona, model, start_time, end_time, input_tokens, output_tokens,
      cost_usd, text_preview, tool_calls (list of ParsedToolCall-shaped objects
      with tool_name, input, output_preview, error).

    Spans are emitted via an independent OTLPSpanExporter pointed at
    `LMNR_BASE_HTTP_URL/v1/traces` (or Laminar cloud default) with the live
    span's context as parent so they thread into the existing trace.

    Args:
        parsed_turns: ordered list of turn objects (output of e.g.
                      `insight_kit.integrations.omp.session_parser.parse_session`).
        namespace:    prefix for `lmnr.span.path` (e.g. "T17.omp"). The full path
                      becomes `<namespace>.<persona>.turn_<idx>`.
        gen_ai_system: value for `gen_ai.system` attribute (default 'opencode-go').

    Returns:
        Count of top-level LLM spans emitted. 0 if `parsed_turns` is empty or
        the OTLP exporter fails to import.
    """
    if not parsed_turns:
        return 0

    try:
        from opentelemetry import trace as _ot_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.trace import NonRecordingSpan
    except ImportError as exc:
        print(
            f"[insight-kit.lmnr] OTLP HTTP exporter not available: {exc}",
            file=sys.stderr,
        )
        return 0

    api_key = os.environ.get("LMNR_PROJECT_API_KEY", "")
    base_http_url = os.environ.get("LMNR_BASE_HTTP_URL", "https://api.lmnr.ai")
    endpoint = f"{base_http_url}/v1/traces"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("insight_kit.lmnr.session")

    # Reconstruct parent ctx from live span so children thread into the trace
    live_span = _ot_trace.get_current_span()
    live_ctx = live_span.get_span_context()

    emitted = 0
    for turn_idx, turn in enumerate(parsed_turns):
        if turn.role != "assistant":
            # Skip user/system/tool meta turns — they carry no LLM usage.
            continue

        attrs: dict[str, Any] = {
            "gen_ai.system": gen_ai_system,
            "gen_ai.operation.name": "chat",
            "lmnr.span.type": "LLM",
            "lmnr.span.path": f"{namespace}.{turn.persona}.turn_{turn_idx}",
            "lmnr.association.properties.persona": turn.persona,
            "lmnr.association.properties.turn_index": turn_idx,
        }
        if turn.model:
            attrs["gen_ai.request.model"] = turn.model
        if turn.input_tokens is not None:
            attrs["gen_ai.usage.input_tokens"] = turn.input_tokens
        if turn.output_tokens is not None:
            attrs["gen_ai.usage.output_tokens"] = turn.output_tokens
        if turn.cost_usd is not None:
            attrs["gen_ai.usage.cost"] = turn.cost_usd
        if turn.text_preview:
            attrs["gen_ai.prompt"] = turn.text_preview[:4096]

        parent_ctx = _ot_trace.set_span_in_context(
            NonRecordingSpan(live_ctx) if (live_ctx and live_ctx.is_valid)
            else _ot_trace.INVALID_SPAN
        )
        with tracer.start_as_current_span(
            f"{namespace}.{turn.persona}.turn_{turn_idx}",
            context=parent_ctx,
            attributes=attrs,
        ):
            for tc in turn.tool_calls:
                tool_attrs: dict[str, Any] = {
                    "lmnr.span.type": "TOOL",
                    "lmnr.span.path": (
                        f"{namespace}.{turn.persona}.turn_{turn_idx}.{tc.tool_name}"
                    ),
                    "lmnr.association.properties.tool_name": tc.tool_name,
                    "lmnr.association.properties.tool_error": tc.error,
                }
                if tc.input:
                    tool_attrs["gen_ai.tool.call.input"] = tc.input[:2048]
                if tc.output_preview:
                    tool_attrs["gen_ai.tool.call.output"] = tc.output_preview[:500]
                with tracer.start_as_current_span(
                    f"tool.{tc.tool_name}",
                    attributes=tool_attrs,
                ):
                    pass

        emitted += 1

    provider.force_flush()
    return emitted


# ---------------------------------------------------------------------------
# Per-check span (Stage-1: score axis 2)
# ---------------------------------------------------------------------------

def score_check_span(
    check_name: str,
    passed: bool,
    *,
    namespace: str = "score",
    file_path: Path | None = None,
) -> None:
    """Emit a child span for one structural check.

    Opens + closes a span on the active OTel context. Parent is whatever span
    is current (typically the @observe-decorated score function).

    Args:
        check_name:   short check identifier, used in the span name and path.
        passed:       check outcome (recorded on the span).
        namespace:    prefix for `lmnr.span.path` (e.g. "T17.score").
        file_path:    optional file whose byte size is recorded as an attribute.
    """
    _, _ot_trace = _require_lmnr()

    tracer = _ot_trace.get_tracer("insight_kit.lmnr.score")
    attrs: dict[str, Any] = {
        "lmnr.span.path": f"{namespace}.{check_name}",
        "lmnr.span.type": "DEFAULT",
        "lmnr.association.properties.check": check_name,
        "lmnr.association.properties.passed": passed,
    }
    if file_path is not None and file_path.exists():
        attrs["lmnr.association.properties.bytes"] = file_path.stat().st_size
    with tracer.start_as_current_span(f"{namespace}.{check_name}", attributes=attrs):
        pass


# ---------------------------------------------------------------------------
# Text utility (capped read for span output attachment)
# ---------------------------------------------------------------------------

def read_capped(path: Path, cap: int = 50_000) -> str:
    """Read a text file capped at `cap` bytes; append a truncation marker if cut.

    Returns empty string when the path doesn't exist.
    """
    if not path.exists():
        return ""
    text = path.read_text(errors="replace")
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n...[truncated {len(text) - cap} bytes]"
