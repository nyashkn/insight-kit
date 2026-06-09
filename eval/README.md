# Eval harness — reusable modules + reference deployment

`insight-kit` exposes the building blocks for running an analyst/critic loop:
score gate, omp session parser, Laminar tracing helpers, analyst prompt
skeleton. Consumer repos wire them into their own containerised eval pipeline.

`growth_insights` is the reference consumer — its `deploy/eval/` Dockerfile +
shim modules show the canonical wiring (git+ssh dep pin, BuildKit SSH mount,
founder-context kwarg injection).

## Public surface

### `insight_kit.platform.eval.score`

9-check semantic score gate for an analyst/critic run directory. Flat weighting
(`passed / 9`) — no opaque bucketing.

| Check | What it guards |
|------:|----------------|
| 1-3   | `claims.jsonl` structural (exists, parseable, non-empty) |
| 4-6   | Sibling `findings_*.md` + `queries/<id>.sql` files exist |
| 7     | Every `claim_id` matches `^MD-[DC]-[A-Z][A-Z0-9]+-(?:\d{3}\|T\d{2})$` (numeric + critic-threading T-suffix both accepted) |
| 8     | Every MD-D-* claim declares a non-empty `query_path` field and every cited path resolves on disk. Whitespace-tokenised — multi-source citations OK, bare `<id>.sql` is normalised to `queries/<id>.sql`, `.py` extractor scripts accepted |
| 9     | Length prior on `findings_*.md` (2000-50000 bytes) — catches stub-as-substantive + runaway-blob |

Usage:

```python
from insight_kit.platform.eval.score import score

s = score(Path("/app/data/agent_runs/2026-06-09_0843_analyst_g6"))
print(f"{s:.4f}")  # → 0.8889
```

CLI:

```sh
python -m insight_kit.platform.eval.score <run_dir>
# stdout: single float in [0.0, 1.0]
# stderr: per-check pass/fail diagnostics
```

### `insight_kit.integrations.omp.session_parser`

Parser for opencode-go (omp) 15.2.4 session JSONL files. Handles hidden `.tmp`
dotfile sessions, persona-boundary splitting (analyst → critic when
`run_analyst_critic.py --critic-phase` appears in a tool call).

```python
from insight_kit.integrations.omp.session_parser import (
    find_session_file, parse_session, ParsedTurn, ParsedToolCall,
)

session_path = find_session_file(Path("/app/data/agent_runs/.../session"))
turns = parse_session(session_path)  # list[ParsedTurn]
```

### `insight_kit.platform.observability.lmnr`

Laminar (self-hosted or cloud) OTel tracing helpers. Lazy-imported — install
the optional dep to use:

```sh
pip install "insight-kit[observability]"
```

Surface:

| Symbol | Purpose |
|--------|---------|
| `init_from_env() -> bool` | Read `LMNR_*` env, call `Laminar.initialize()`. Returns `False` (tracing OFF) when `LMNR_PROJECT_API_KEY` unset. Self-host vs cloud determined by `LMNR_BASE_URL` presence. |
| `RunIdentity` | Dataclass: `run_id`, `git_sha`, `git_branch`, `image_digest`, `harness_version`, `cwd`, `image`. `RunIdentity.from_env(cwd, image, harness_version)` captures from env+git. `.as_metadata()` → kwargs for `Laminar.start_as_current_span(metadata=...)`. |
| `emit_session_spans(parsed_turns, *, namespace, gen_ai_system="opencode-go") -> int` | Back-emit one `LLM` span per assistant turn + child `TOOL` spans. Parented to the live OTel span. Returns emitted count. Never raises. |
| `score_check_span(check_name, passed, *, namespace, file_path)` | One per-check span under the active score span. Sync open/close. |
| `read_capped(path, cap=50_000) -> str` | Capped read for span output attachment (truncates with marker). |

Env recognised by `init_from_env()`:

| Var | Required? | Notes |
|-----|-----------|-------|
| `LMNR_PROJECT_API_KEY` | yes | Tracing OFF when unset — no exception, just `False` return |
| `LMNR_BASE_URL`        | self-host only | gRPC URL, **scheme+host only, NO port in URL string** — port goes in `LMNR_GRPC_PORT` |
| `LMNR_BASE_HTTP_URL`   | self-host only | HTTP URL, scheme+host |
| `LMNR_GRPC_PORT`       | self-host only | Integer |
| `LMNR_HTTP_PORT`       | self-host only | Integer |

### `insight_kit.narrative.analyst_prompt`

Reusable analyst prompt skeleton: claim schema, strict `query_path` rules,
output file list. Project-specific bits (founder context, data scope markdown)
are kwargs.

```python
from insight_kit.narrative.analyst_prompt import render_analyst_prompt

header = render_analyst_prompt(
    goal_slug="g6_attribution",
    question="Why did CPA fall in April?",
    run_dir="/app/data/agent_runs/r1",
    data_scope=data_scope_md,           # consumer-formatted markdown
    founder_context="April is the worst month on record. ...",  # optional
)
prompt = header + persona_instructions  # caller appends persona text
```

`founder_context=""` (default) omits the entire `**Founder context:**` block —
no empty heading leaks through.

`query_path` rules baked into the template:
- Exactly ONE path. Single string. No spaces, no concatenation.
- Format MUST be `queries/<claim_id>.sql`.
- Composite/derived claims reference upstream `claim_id`s in the `cites` array,
  NOT in `query_path`.

## Reference consumer — `growth_insights`

### Pinning insight-kit

`growth_insights/pyproject.toml`:

```toml
[project]
dependencies = [
    "insight-kit",
    # ...
]

[tool.uv.sources]
insight-kit = { git = "ssh://git@github.com/nyashkn/insight-kit.git", rev = "6f0ade3a1bb1be32384ca9874bdc5a05a2ee2799" }
```

**Pin by SHA, never by path.** `path = "../../insight-kit"` works locally but
breaks inside Docker (the sibling repo is not in the build context). The git+ssh
ref resolves identically on host and in container.

### Docker — BuildKit SSH mount

`growth_insights/deploy/eval/Dockerfile`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client git \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.ssh && ssh-keyscan github.com >> /root/.ssh/known_hosts

# Both sync passes mount the SSH agent so uv can pull insight-kit
RUN --mount=type=ssh uv sync --frozen --no-install-project
COPY . .
RUN --mount=type=ssh uv sync --frozen
```

Build invocation (`growth_insights/deploy/eval/run-eval.sh`):

```sh
DOCKER_BUILDKIT=1 docker build \
    --ssh default \
    -f deploy/eval/Dockerfile \
    -t insight-eval-harness:t17 .
```

The host's running `ssh-agent` provides the credential to BuildKit; no key
material lands in the image layer.

### Wiring the analyst prompt

`growth_insights/src/growth_insights/analyst/runner.py`:

```python
from insight_kit.narrative.analyst_prompt import render_analyst_prompt

_FOUNDER_CONTEXT = (
    "April is the worst month on record. Every lever you surface "
    "must be actionable within the next 7 days and must include a $ projection."
)

def build_prompt(self) -> str:
    data_scope = format_data_scope_md(self.goal)   # nairomarket-specific
    header = render_analyst_prompt(
        goal_slug=self._goal_slug(),
        question=self.goal["question"],
        run_dir=self.run_dir,
        data_scope=data_scope,
        founder_context=_FOUNDER_CONTEXT,
    )
    return header + self._load_persona_prompt(...)
```

### Wiring the score gate + telemetry

`growth_insights/deploy/eval/lmnr_harness.py`:

```python
from insight_kit.platform.eval.score import score
from insight_kit.platform.observability.lmnr import (
    init_from_env, RunIdentity, emit_session_spans, score_check_span, read_capped,
)

_LMNR_ACTIVE = init_from_env()  # module-level

def main() -> None:
    identity = RunIdentity.from_env(
        cwd="/app",
        image="insight-eval-harness:t17",
        harness_version="stage-2",
    )
    # ... start root span with identity.as_metadata(), then call score(run_dir)
    # under a child span, wrapping each check via score_check_span(...)
```

## Constraints — non-negotiable

- **Never touch the shared `LMNR_PROJECT_API_KEY` Infisical secret.** Used by
  25+ consumers across `kg_rust` and `kg_rust_embed_first`. Use a dedicated
  key (e.g. `LMNR_PROJECT_API_KEY_INSIGHT_KIT`) injected as
  `LMNR_PROJECT_API_KEY` only inside the eval container.
- **gRPC `LMNR_BASE_URL` is scheme+host with NO port in the URL string.**
  `"https://laminar-grpc.lan.ds.ke"` ✓, `"https://laminar-grpc.lan.ds.ke:443"` ✗.
  Port goes in `LMNR_GRPC_PORT`.
- **Telemetry must NEVER fail the eval run.** All `emit_*` helpers swallow
  exceptions internally; consumer code that calls them should still wrap in
  `try/except` for defence in depth.
- **Pin insight-kit by SHA, not by path.** Docker breaks otherwise.
- **Never inline `LMNR_PROJECT_API_KEY` in code, commits, comments, or chat.**

## Versioning

Current: `insight-kit==0.1.6` (main @ `6f0ade3`). Bump the rev pin in
consumer `pyproject.toml` to adopt new releases — the contract is the public
symbols documented above; signature changes will bump the minor version.
