# insight-kit Monorepo Restructure Plan

**Status:** Planning only — no files moved, renamed, or edited.
**Branch at time of writing:** `feat/agents-system-v2`
**Python baseline:** 546 tests passing, ruff clean.

---

## 1. Packaging Decision: Option A — Single `insight_kit` package, reorganised internal subpackages

### The two options

| | Option A — single package, internal reorg | Option B — `uv` workspace, multiple distributable packages |
|---|---|---|
| Import surface | `insight_kit.*` unchanged everywhere | Each boundary becomes its own dist (`insight-kit-gate`, `insight-kit-hamilton`, …) |
| `pyproject.toml` changes | `packages` path only; no workspace table | Full workspace: `[tool.uv.workspace]`, per-package `pyproject.toml` |
| Churn estimate | ~60 file moves, 0 `import` edits | ~60 file moves + 4+ new `pyproject.toml` + namespace `__init__.py` + cross-package deps |
| Isolation enforcement | Convention + CI lint rules (already done via ruff per-file ignores + test_purity.py AST scan) | Hard package boundary — cross-boundary imports fail at install |
| Risk | Low; one editable install, one `.pth` entry | Medium; `uv sync` must resolve all workspace members; editable installs of sibling packages |
| Reversible | Yes | Harder to collapse back |

**Recommendation: Option A.**

The gate's isolation invariant (C1/V5: gate never imports hamilton or pi) is already enforced by two independent mechanisms — an AST scan in `tests/gate/test_purity.py` and a ruff lint rule scoped to `src/insight_kit/gate/`. Adding hard package boundaries for a single-team, single-deployer project buys nothing beyond what the existing tooling already enforces, at material coordination overhead. Option A achieves real boundary separation (directory taxonomy + CI-enforced import rules) without the workspace-management cost.

The new internal layout mirrors the Signet group names but stays inside `src/insight_kit/`:

```
src/insight_kit/
  platform/gate/       ← current gate/
  platform/harness/    ← current harness.py (promoted to subpackage)
  libs/errors.py       ← current errors.py
  libs/config/         ← current config/
  libs/provenance/     ← current provenance/ (root.py, kit discovery)
  libs/validation/     ← current validation/
  integrations/hamilton/ ← current hamilton/
  integrations/agents/   ← current agents/
  surfaces/cli/        ← current cli/
  surfaces/annotations.py ← current annotations.py
```

The public re-export `insight_kit/__init__.py` remains unchanged; callers using `from insight_kit import ik_claim_emit` never notice the internal path change.

---

## 2. Current-state tree

```
insight-kit/
  src/insight_kit/
    __init__.py
    annotations.py
    errors.py
    harness.py
    agents/            __init__.py  bootstrap.py  cli.py  config.py  yaml_edit.py
    assets/            (Svelte components — not moved by this plan)
    cli/               __init__.py  __main__.py
    config/            __init__.py
    gate/              __init__.py  audit.py  cli.py  emit.py  env.py  feature.py
                       fingerprint.py  render_adapters.py  runcheck.py  runstate.py
                       schema.py  store.py  verdict.py
    hamilton/          __init__.py  adapter.py
    provenance/        __init__.py  root.py
    validation/        __init__.py
  tests/
    conftest.py
    gate/              (27 test files)
    test_agents_cli.py  test_agents_config.py  test_annotations.py
    test_bootstrap_secrets.py  test_hamilton.py  test_harness.py
    test_ik_cli.py  test_root.py  test_validation.py
  viz/
    core/              @insight-kit/viz-core  (bun workspace member)
    evidence/          @insight-kit/viz-evidence
    sdk/               @insight-kit/viz
    tsconfig.json
  scripts/
    gen-pi-schema.ts
    pi-run.sh
  .pi/
    extensions/insight-kit.ts
    lib/core.ts  schema.generated.ts
    test/
    settings.json  tsconfig.json  README.md
  .agents/           (agent personas, skills — config files only, no code)
  docs/
  pyproject.toml     (hatchling, src layout, ik entrypoint)
  package.json       (bun workspace: viz/*)
  .github/workflows/ci.yml
```

---

## 3. Move-map

Every path is relative to repo root. "STAYS" = not moved.

### 3.1 Root-level non-code configs — STAYS

| Current path | Proposed path | Rationale |
|---|---|---|
| `pyproject.toml` | STAYS | Single package, single build config |
| `package.json` | STAYS | bun workspace root; `workspaces: ["viz/*"]` must remain at repo root |
| `.pi/` (entire dir) | STAYS | pi auto-discovers `.pi/extensions/*.ts` and `.pi/settings.json` relative to repo root; moving requires `pi-run.sh` + settings changes that break the L3 seam. Constraint noted in brief; recommendation: stay. |
| `scripts/pi-run.sh` | `deploy/scripts/pi-run.sh` | deploy group owns launch infrastructure |
| `scripts/gen-pi-schema.ts` | `deploy/scripts/gen-pi-schema.ts` | build/codegen utility |
| `.github/` | STAYS | CI is repo-root infra |
| `.agents/` | STAYS | Persona config, not source code |

> **Note on `package.json` `pi:gen-schema` script:** it references `scripts/gen-pi-schema.ts`. After Phase 4 moves that file, the script path must update to `deploy/scripts/gen-pi-schema.ts`.

### 3.2 Platform group — L1 gate + eval harness

**Semantics:** frozen core domain. No external-connector imports allowed.

| Current path | Proposed path | Rationale |
|---|---|---|
| `src/insight_kit/gate/__init__.py` | `src/insight_kit/platform/gate/__init__.py` | Gate is the frozen L1 core |
| `src/insight_kit/gate/audit.py` | `src/insight_kit/platform/gate/audit.py` | |
| `src/insight_kit/gate/cli.py` | `src/insight_kit/platform/gate/cli.py` | The C4 lang seam subprocess CLI |
| `src/insight_kit/gate/emit.py` | `src/insight_kit/platform/gate/emit.py` | |
| `src/insight_kit/gate/env.py` | `src/insight_kit/platform/gate/env.py` | |
| `src/insight_kit/gate/feature.py` | `src/insight_kit/platform/gate/feature.py` | |
| `src/insight_kit/gate/fingerprint.py` | `src/insight_kit/platform/gate/fingerprint.py` | |
| `src/insight_kit/gate/render_adapters.py` | `src/insight_kit/platform/gate/render_adapters.py` | |
| `src/insight_kit/gate/runcheck.py` | `src/insight_kit/platform/gate/runcheck.py` | |
| `src/insight_kit/gate/runstate.py` | `src/insight_kit/platform/gate/runstate.py` | |
| `src/insight_kit/gate/schema.py` | `src/insight_kit/platform/gate/schema.py` | |
| `src/insight_kit/gate/store.py` | `src/insight_kit/platform/gate/store.py` | |
| `src/insight_kit/gate/verdict.py` | `src/insight_kit/platform/gate/verdict.py` | |
| `src/insight_kit/harness.py` | `src/insight_kit/platform/harness/__init__.py` | Eval harness sits next to the gate it validates |
| *(new)* | `src/insight_kit/platform/__init__.py` | Group marker |

**Frozen-gate constraint:** Every file inside `gate/` moves as a unit. No file inside is edited during the move — only the directory path changes. Internal imports within the gate (`from insight_kit.gate.schema import ...`) become `from insight_kit.platform.gate.schema import ...` — this is a mechanical text replacement applied in a single commit.

### 3.3 Libs group — shared low-level utilities

**Semantics:** zero domain logic, no connectors, imported by platform + integrations + surfaces.

| Current path | Proposed path | Rationale |
|---|---|---|
| `src/insight_kit/errors.py` | `src/insight_kit/libs/errors.py` | Single exception; shared by gate, config, CLI |
| `src/insight_kit/config/__init__.py` | `src/insight_kit/libs/config/__init__.py` | Secrets loader; imported by provenance.root |
| `src/insight_kit/provenance/__init__.py` | `src/insight_kit/libs/provenance/__init__.py` | Re-export shim |
| `src/insight_kit/provenance/root.py` | `src/insight_kit/libs/provenance/root.py` | Kit-root discovery — pure utility |
| `src/insight_kit/validation/__init__.py` | `src/insight_kit/libs/validation/__init__.py` | Layer-A guards — shared by gate + CLI |
| *(new)* | `src/insight_kit/libs/__init__.py` | Group marker |

**Divergence from html-kit explainer:** The html-kit doc proposed `libs/gate-cli/` as the subprocess CLI seam. On closer inspection `gate/cli.py` is pure gate code (it calls `ik_*_emit` and nothing else); the subprocess interface is the *calling convention*, not a separate library. It belongs in `platform/gate/`, not `libs/`. The libs group here contains what the html-kit doc describes as "shared SDK" — errors, config, provenance/root — which is low-level with no domain logic.

### 3.4 Integrations group — external connectors

**Semantics:** one subpackage per external system. Imports from `platform` and `libs`. Never imported by `platform`.

| Current path | Proposed path | Rationale |
|---|---|---|
| `src/insight_kit/hamilton/__init__.py` | `src/insight_kit/integrations/hamilton/__init__.py` | Hamilton adapter is an integration |
| `src/insight_kit/hamilton/adapter.py` | `src/insight_kit/integrations/hamilton/adapter.py` | |
| `src/insight_kit/agents/__init__.py` | `src/insight_kit/integrations/agents/__init__.py` | Agent system orchestrates external tooling (Claude Code, pi); it is a connector layer |
| `src/insight_kit/agents/bootstrap.py` | `src/insight_kit/integrations/agents/bootstrap.py` | |
| `src/insight_kit/agents/cli.py` | `src/insight_kit/integrations/agents/cli.py` | |
| `src/insight_kit/agents/config.py` | `src/insight_kit/integrations/agents/config.py` | |
| `src/insight_kit/agents/yaml_edit.py` | `src/insight_kit/integrations/agents/yaml_edit.py` | |
| *(new)* | `src/insight_kit/integrations/__init__.py` | Group marker |

**Note on `.pi/`:** The pi extension itself (`.pi/extensions/insight-kit.ts`) stays at repo root as required by the pi discovery contract. It is logically an integration connector but its physical location is fixed. This plan treats `.pi/` as a virtual member of `integrations/` documented here but not moved.

**Divergence from html-kit explainer:** The html-kit doc proposed `integrations/pi/` as a separate bun package. Since `.pi/` must stay at root, and the pi extension is already scoped to `.pi/`, there is nothing to move. The `agents/` subpackage maps better to `integrations/` than to any other group because its bootstrap logic orchestrates external agent runtimes.

### 3.5 Surfaces group — user-facing I/O

**Semantics:** human/CLI entry points; no platform imports from here are allowed (surfaces consume, not produce).

| Current path | Proposed path | Rationale |
|---|---|---|
| `src/insight_kit/cli/__init__.py` | `src/insight_kit/surfaces/cli/__init__.py` | `ik` CLI is the primary human surface |
| `src/insight_kit/cli/__main__.py` | `src/insight_kit/surfaces/cli/__main__.py` | |
| `src/insight_kit/annotations.py` | `src/insight_kit/surfaces/annotations.py` | Binary annotation API; human-authored, read-facing |
| `viz/` (entire dir) | STAYS at `viz/` | bun workspace; `package.json` `workspaces: ["viz/*"]` requires `viz/` at repo root. Moving `viz/` would require changing `package.json` workspace glob and all `@insight-kit/viz-*` file: references — this is the JS surface layer, not inside `src/` |
| *(new)* | `src/insight_kit/surfaces/__init__.py` | Group marker |

**Note on CLI viz path hardcoding:** `cli/__main__.py` lines 95 + 126 compute the path to `viz/` as `Path(__file__).resolve().parents[3] / "viz" / ...`. Currently `__file__` is `src/insight_kit/cli/__main__.py` → `parents[3]` = repo root. After the move to `src/insight_kit/surfaces/cli/__main__.py` the depth is the same (`parents[3]` still = repo root, since `surfaces/cli/` is the same nesting depth as `cli/`). No change needed here.

### 3.6 Deploy group — containers, launch scripts, Infisical wiring

**Semantics:** zero business logic. Everything needed to run the system in a container or CI. The T17 eval container stays LOCAL — its Docker recipe lives here, never pushed to any registry.

| Current path | Proposed path | Rationale |
|---|---|---|
| `scripts/pi-run.sh` | `deploy/scripts/pi-run.sh` | Launch infrastructure |
| `scripts/gen-pi-schema.ts` | `deploy/scripts/gen-pi-schema.ts` | Codegen build utility |
| *(new)* | `deploy/eval/README.md` | The eval container recipe (LOCAL-only, as noted in ck-build-log.md T17) |
| *(new)* | `deploy/eval/Dockerfile` | When authored; referenced in README, never pushed |

**Note:** The `package.json` `"pi"` and `"pi:gen-schema"` scripts reference `scripts/pi-run.sh` and `scripts/gen-pi-schema.ts`. After Phase 4, these must be updated to `deploy/scripts/...`.

### 3.7 Tests — mirror the new source layout

| Current path | Proposed path | Rationale |
|---|---|---|
| `tests/gate/` | `tests/platform/gate/` | Mirror platform/gate |
| `tests/test_harness.py` | `tests/platform/test_harness.py` | Mirror platform/harness |
| `tests/test_hamilton.py` | `tests/integrations/test_hamilton.py` | Mirror integrations/hamilton |
| `tests/test_agents_cli.py` | `tests/integrations/test_agents_cli.py` | Mirror integrations/agents |
| `tests/test_agents_config.py` | `tests/integrations/test_agents_config.py` | |
| `tests/test_bootstrap_secrets.py` | `tests/integrations/test_bootstrap_secrets.py` | |
| `tests/test_annotations.py` | `tests/surfaces/test_annotations.py` | Mirror surfaces |
| `tests/test_ik_cli.py` | `tests/surfaces/test_ik_cli.py` | |
| `tests/test_root.py` | `tests/libs/test_root.py` | Mirror libs/provenance |
| `tests/test_validation.py` | `tests/libs/test_validation.py` | Mirror libs/validation |
| `tests/conftest.py` | `tests/conftest.py` | Stays at root — shared by all |

---

## 4. Phased execution plan

Each phase ends with `uv run pytest` green + `bun run pi:test` passing + `bun run pi:typecheck` exit 0. Phases are sequential (each depends on the previous). Total: **6 phases**.

### Phase 0 — Baseline snapshot (no moves)

**Goal:** Record the exact passing baseline before any moves.

**Actions:**
1. `uv run pytest -q` — record count (expected: 546 passed).
2. `bun run pi:typecheck` — confirm exit 0.
3. `bun run pi:test` — confirm 38 tests pass.
4. `uv run ruff check src tests` — confirm clean.

**What breaks:** Nothing. This is the sanity gate.

**Gate:** All four green.

---

### Phase 1 — Create group directories and `__init__.py` markers only

**Goal:** Scaffold the new directory tree with empty `__init__.py` files. No source moved yet.

**Actions:**
Create these empty `__init__.py` files:
- `src/insight_kit/platform/__init__.py`
- `src/insight_kit/platform/gate/` ← empty placeholder; gate not moved yet
- `src/insight_kit/platform/harness/` ← empty placeholder
- `src/insight_kit/libs/__init__.py`
- `src/insight_kit/integrations/__init__.py`
- `src/insight_kit/surfaces/__init__.py`
- `tests/platform/__init__.py`
- `tests/integrations/__init__.py`
- `tests/surfaces/__init__.py`
- `tests/libs/__init__.py`

Also create `deploy/scripts/` directory and `deploy/eval/` directory with a placeholder README.

**What breaks:** Nothing — source code unchanged, original paths still exist.

**Import changes:** None.

**pyproject.toml changes:** None.

**pytest discovery:** `testpaths = ["tests"]` already discovers recursively; new `tests/platform/` etc. subdirs with only `__init__.py` add 0 test files, 0 failures.

**Gate:** All four green (baseline unchanged).

---

### Phase 2 — Move `libs/` group

**Goal:** Move errors, config, provenance, validation into `src/insight_kit/libs/`.

**Files moved:**
- `src/insight_kit/errors.py` → `src/insight_kit/libs/errors.py`
- `src/insight_kit/config/__init__.py` → `src/insight_kit/libs/config/__init__.py`
- `src/insight_kit/provenance/__init__.py` → `src/insight_kit/libs/provenance/__init__.py`
- `src/insight_kit/provenance/root.py` → `src/insight_kit/libs/provenance/root.py`
- `src/insight_kit/validation/__init__.py` → `src/insight_kit/libs/validation/__init__.py`

**Test files moved:**
- `tests/test_root.py` → `tests/libs/test_root.py`
- `tests/test_validation.py` → `tests/libs/test_validation.py`

**What breaks (complete list):**

1. **All `from insight_kit.errors import ...`** — appears in:
   - `src/insight_kit/libs/config/__init__.py` (self-ref; already moved)
   - `src/insight_kit/libs/provenance/root.py` (self-ref; already moved)
   - `src/insight_kit/platform/gate/*.py` (not moved yet in this phase — but gate is not moved in Phase 2, so gate still imports from the old path: **BREAK**)

   > Phase 2 fix: add a back-compat shim at `src/insight_kit/errors.py` (keep the old file as a re-export): `from insight_kit.libs.errors import *; from insight_kit.libs.errors import ConfigError`. This shim is removed in Phase 6 cleanup.

2. **All `from insight_kit.config import ...`** — same pattern; add `src/insight_kit/config/__init__.py` shim.

3. **All `from insight_kit.provenance import ...` / `from insight_kit.provenance.root import ...`** — add `src/insight_kit/provenance/__init__.py` shim + `src/insight_kit/provenance/root.py` shim.

4. **All `from insight_kit.validation import ...`** — add `src/insight_kit/validation/__init__.py` shim.

5. **`pyproject.toml` `packages = ["src/insight_kit"]`** — unchanged; hatchling packages the whole `src/insight_kit/` tree, shims included.

6. **`pytest` `testpaths = ["tests"]`** — unchanged; picks up new `tests/libs/` location automatically.

**Precise fix:** Four backward-compat shim files at the old paths, each containing only:
```python
# Back-compat shim — remove in Phase 6.
from insight_kit.libs.<module> import *  # noqa: F401, F403
```

**Silently-broken risk:** None if shims are in place. The shim pattern is standard Python re-export; type checkers follow it.

**Gate:** 546 tests, ruff clean, pi unchanged.

---

### Phase 3 — Move `platform/` group (gate + harness)

**Goal:** Move the frozen L1 gate and harness into `src/insight_kit/platform/`.

**Files moved (gate — as a unit):**
All 13 files under `src/insight_kit/gate/` → `src/insight_kit/platform/gate/`.

**Files moved (harness):**
- `src/insight_kit/harness.py` → `src/insight_kit/platform/harness/__init__.py`

**Test files moved:**
- `tests/gate/` → `tests/platform/gate/`
- `tests/test_harness.py` → `tests/platform/test_harness.py`

**What breaks:**

1. **Intra-gate imports** — every `from insight_kit.gate.X import Y` inside the gate files themselves. These become `from insight_kit.platform.gate.X import Y`. Count: ~40 import lines across 13 files. This is a mechanical sed-style replacement, applied atomically in one commit.

2. **`insight_kit/gate/__init__.py`** — the public gate API re-export. Keep a back-compat shim at `src/insight_kit/gate/__init__.py`:
   ```python
   # Back-compat shim — remove in Phase 6.
   from insight_kit.platform.gate import *  # noqa: F401, F403
   ```

3. **`src/insight_kit/__init__.py`** — the top-level package re-export uses `import insight_kit.gate as _gate`. With the shim in place this continues to work (the shim re-exports the whole gate). Update lazily: `import insight_kit.platform.gate as _gate` in Phase 6.

4. **`tests/gate/test_purity.py`** — the AST scanner checks `src/insight_kit/gate/`. After the move it must scan `src/insight_kit/platform/gate/`. This test file must be updated in this phase (it is a test of the gate's source, not the gate's runtime, so updating it is safe even under the freeze constraint — only the scan path changes, not the gate code).

5. **`tests/platform/gate/test_cli.py`** — the CLI subprocess test calls `python -m insight_kit.gate.cli`. With the shim in place, the old module path is unavailable (the shim is `__init__.py` of the old package, which re-exports but does not preserve the `insight_kit.gate.cli` module path). Fix: update test to `python -m insight_kit.platform.gate.cli`. Alternatively, add a `src/insight_kit/gate/cli.py` shim stub — but that creates a misleading module. Prefer the test update.

6. **`harness.py` → `platform/harness/__init__.py`** — keep shim at `src/insight_kit/harness.py`.

7. **`pyproject.toml` `[tool.ruff.lint.extend-per-file-ignores]`** — currently scopes gate purity rules to `src/insight_kit/gate/`. Must update path to `src/insight_kit/platform/gate/`.

8. **`pyproject.toml` comment** in `[tool.ruff.lint.flake8-tidy-imports]` references `src/insight_kit/gate/` — update comment only (no functional change).

**Silently-broken risk:** The `test_purity.py` AST scan path is the main risk. It is addressed explicitly in step 4. CI runs the full test suite including gate purity tests, so a missed path update will fail loudly.

**Gate:** 546 tests, ruff clean, pi typecheck + test unchanged (pi extension calls `python -m insight_kit.gate.cli` — with the shim resolving the old path, pi still works; full update in Phase 5).

---

### Phase 4 — Move `integrations/` group + `deploy/` group

**Goal:** Move hamilton adapter + agents system into `src/insight_kit/integrations/`. Move scripts into `deploy/`.

**Files moved (integrations):**
- `src/insight_kit/hamilton/__init__.py` → `src/insight_kit/integrations/hamilton/__init__.py`
- `src/insight_kit/hamilton/adapter.py` → `src/insight_kit/integrations/hamilton/adapter.py`
- `src/insight_kit/agents/__init__.py` → `src/insight_kit/integrations/agents/__init__.py`
- `src/insight_kit/agents/bootstrap.py` → `src/insight_kit/integrations/agents/bootstrap.py`
- `src/insight_kit/agents/cli.py` → `src/insight_kit/integrations/agents/cli.py`
- `src/insight_kit/agents/config.py` → `src/insight_kit/integrations/agents/config.py`
- `src/insight_kit/agents/yaml_edit.py` → `src/insight_kit/integrations/agents/yaml_edit.py`

**Files moved (deploy):**
- `scripts/pi-run.sh` → `deploy/scripts/pi-run.sh`
- `scripts/gen-pi-schema.ts` → `deploy/scripts/gen-pi-schema.ts`

**Test files moved:**
- `tests/test_hamilton.py` → `tests/integrations/test_hamilton.py`
- `tests/test_agents_cli.py` → `tests/integrations/test_agents_cli.py`
- `tests/test_agents_config.py` → `tests/integrations/test_agents_config.py`
- `tests/test_bootstrap_secrets.py` → `tests/integrations/test_bootstrap_secrets.py`

**What breaks:**

1. **`from insight_kit.hamilton import ...` / `from insight_kit.agents import ...`** — all call sites. Back-compat shims at old paths:
   - `src/insight_kit/hamilton/__init__.py` shim
   - `src/insight_kit/agents/__init__.py` shim

2. **`insight_kit/integrations/hamilton/adapter.py`** internal imports — `from insight_kit.gate import ...` becomes `from insight_kit.platform.gate import ...`. (The gate shim would also work but clean is better for new code; update directly.)

3. **`insight_kit/integrations/agents/bootstrap.py`** internal imports — `from .config import ...` remains unchanged (relative import within the subpackage).

4. **`cli/__main__.py` `add_agents_parser` import** — currently `from insight_kit.agents.cli import add_agents_parser`. With shim in place, no change needed now. Update to `from insight_kit.integrations.agents.cli import ...` in Phase 6.

5. **`package.json` scripts `"pi"` and `"pi:gen-schema"`** — must update:
   - `"pi": "bash scripts/pi-run.sh"` → `"pi": "bash deploy/scripts/pi-run.sh"`
   - `"pi:gen-schema": "bun run scripts/gen-pi-schema.ts"` → `"bun run deploy/scripts/gen-pi-schema.ts"`

6. **`.pi/tsconfig.json`** and **`.pi/lib/core.ts`** — reference `scripts/gen-pi-schema.ts` if any? Check: `gen-pi-schema.ts` is called via `package.json` script only; `.pi/` files do not hard-code its path. No change to `.pi/`.

7. **`scripts/` directory** becomes empty after moves. Leave the directory in place (or add a `README.md` redirect) — do not delete until Phase 6 cleanup.

**Silently-broken risk:** The `package.json` script path update (item 5) must be done in this phase — `bun run pi` will immediately break on CI if the path is wrong. This is caught by `bun run pi:test` in the phase gate.

**Gate:** 546 tests, ruff clean, `bun run pi:test` + `bun run pi:typecheck` green.

---

### Phase 5 — Move `surfaces/` group

**Goal:** Move CLI and annotations into `src/insight_kit/surfaces/`.

**Files moved:**
- `src/insight_kit/cli/__init__.py` → `src/insight_kit/surfaces/cli/__init__.py`
- `src/insight_kit/cli/__main__.py` → `src/insight_kit/surfaces/cli/__main__.py`
- `src/insight_kit/annotations.py` → `src/insight_kit/surfaces/annotations.py`

**Test files moved:**
- `tests/test_ik_cli.py` → `tests/surfaces/test_ik_cli.py`
- `tests/test_annotations.py` → `tests/surfaces/test_annotations.py`

**What breaks:**

1. **`pyproject.toml` `[project.scripts] ik = "insight_kit.cli.__main__:main"`** — must update to `"insight_kit.surfaces.cli.__main__:main"`. This is the only change to `pyproject.toml`. After the change, `uv sync` re-installs the editable entry point. The `ik` binary in `.venv/bin/ik` regenerates automatically.

2. **`from insight_kit.cli import ...`** — add back-compat shim at `src/insight_kit/cli/__init__.py`.

3. **`from insight_kit.annotations import ...`** — add back-compat shim at `src/insight_kit/annotations.py`.

4. **`cli/__main__.py` internal imports** — currently `from insight_kit.agents.cli import add_agents_parser`. With the shim from Phase 4 in place, no change needed. Direct update: `from insight_kit.integrations.agents.cli import add_agents_parser`.

5. **`cli/__main__.py` viz path calculation** — confirmed safe: `Path(__file__).resolve().parents[3]` with `__file__` at `src/insight_kit/surfaces/cli/__main__.py` → `parents[0]` = `cli/`, `parents[1]` = `surfaces/`, `parents[2]` = `insight_kit/`, `parents[3]` = `src/`. That is NOT the repo root — this is a regression introduced by adding the `surfaces/` layer. Fix: change `parents[3]` to `parents[4]` in both occurrences (lines 95 + 126). Alternatively replace with `Path(__file__).resolve().parents[4] / "viz" / ...` or use the more robust `find_kit_root()`.

   > **Recommended fix:** Replace the fragile `parents[N]` expressions with an environment-variable-based path or `find_kit_root()`-relative lookup. Minimum change: `parents[3]` → `parents[4]`.

6. **`pi` extension** — `.pi/extensions/insight-kit.ts` calls `python -m insight_kit.gate.cli`. The gate shim preserves the old module path for now; update to `python -m insight_kit.platform.gate.cli` in this phase (the pi extension tests will catch a broken path).

**Silently-broken risk:** The `parents[N]` path bug (item 5) is the highest risk in this phase. `tests/surfaces/test_ik_cli.py` covers `ik preflight` and `ik viz install`; if those commands attempt to resolve the viz path, the wrong depth will produce a `FileNotFoundError` which the test will catch. The test must be run in an environment where `viz/core/cli.ts` exists; if the test mocks the subprocess call, the path bug is masked. Ensure at least one test resolves the actual path.

**Gate:** 546 tests, ruff clean, pi green.

---

### Phase 6 — Remove back-compat shims + clean up old empty paths

**Goal:** Delete all shim files, update all direct import references to use the new canonical paths, remove the now-empty `scripts/` directory.

**Shims to delete (and their replacements):**
| Shim file | Replace callers with |
|---|---|
| `src/insight_kit/errors.py` | `from insight_kit.libs.errors import ConfigError` |
| `src/insight_kit/config/__init__.py` | `from insight_kit.libs.config import load_secrets` |
| `src/insight_kit/provenance/__init__.py` | `from insight_kit.libs.provenance import ...` |
| `src/insight_kit/provenance/root.py` | `from insight_kit.libs.provenance.root import ...` |
| `src/insight_kit/validation/__init__.py` | `from insight_kit.libs.validation import ...` |
| `src/insight_kit/gate/__init__.py` | `from insight_kit.platform.gate import ...` |
| `src/insight_kit/harness.py` | `from insight_kit.platform.harness import ...` |
| `src/insight_kit/hamilton/__init__.py` | `from insight_kit.integrations.hamilton import ...` |
| `src/insight_kit/agents/__init__.py` | `from insight_kit.integrations.agents import ...` |
| `src/insight_kit/cli/__init__.py` | `from insight_kit.surfaces.cli import ...` |
| `src/insight_kit/annotations.py` | `from insight_kit.surfaces.annotations import ...` |

**Additional cleanup:**
- `src/insight_kit/__init__.py` — update the lazy `__getattr__` to import from `insight_kit.platform.gate` instead of `insight_kit.gate`.
- `ruff.toml` per-file-ignore path update: `src/insight_kit/platform/gate/` (done in Phase 3; confirm still correct).
- Delete now-empty `scripts/` directory.
- Delete `src/insight_kit/cli/` directory (was replaced by shim in Phase 5, now shim is deleted).
- Update any `TYPE_CHECKING` imports that still reference old paths.
- `pyproject.toml` comment about gate purity — update path reference.

**What breaks:** If any caller was missed in earlier phases, ruff `F401` (unused import in shim) or `ImportError` at test time will surface it. Run `uv run ruff check src tests` and `uv run pytest` before committing the shim deletion.

**Gate:** 546 tests, ruff clean (no F401/F403 from deleted shims), pi green.

---

## 5. What pyproject.toml must change and when

| Change | Phase | Description |
|---|---|---|
| `[tool.hatch.build.targets.wheel] packages` | None | `["src/insight_kit"]` already picks up the whole tree recursively — no change needed |
| `[project.scripts] ik = ...` | Phase 5 | `insight_kit.cli.__main__:main` → `insight_kit.surfaces.cli.__main__:main` |
| `[tool.ruff.lint.per-file-ignores] "src/insight_kit/gate/**"` | Phase 3 | → `"src/insight_kit/platform/gate/**"` |
| `[tool.pytest.ini_options] testpaths` | None | `["tests"]` — unchanged; pytest discovers subdirs |

---

## 6. What CI must change and when

`.github/workflows/ci.yml` currently runs:
- `uv run ruff check src tests`
- `uv run pytest -v`
- `uv build`

No path-specific CI steps exist. All three commands operate on the top-level `src/` and `tests/` trees and require no changes.

The one CI risk: `uv build` will fail if the `[project.scripts]` entry point path is wrong (Phase 5 update). This is caught by the local gate before CI runs.

---

## 7. Risk register: what could silently break and how phase gates catch it

| Risk | Severity | Phase introduced | Catch mechanism |
|---|---|---|---|
| `parents[N]` depth wrong in `cli/__main__.py` after `surfaces/` nesting | HIGH | Phase 5 | `tests/surfaces/test_ik_cli.py` preflight + viz tests must exercise the path calculation |
| `tests/gate/test_purity.py` AST scan path not updated | HIGH | Phase 3 | The test would scan the wrong directory and always pass — write a sentinel: assert the scan finds at least N Python files. Already exists (`test_purity.py` asserts non-empty scan). Update the path. |
| `python -m insight_kit.gate.cli` in pi extension not updated | MEDIUM | Phase 5 | `bun run pi:test` — the end-to-end `uv run` cases in `insight-kit.extension.test.ts` call the real CLI subprocess and will fail with `ModuleNotFoundError` if path is stale |
| `package.json` `pi-run.sh` path not updated | MEDIUM | Phase 4 | `bun run pi` fails immediately; caught by local developer but not by `bun run pi:test` (which uses `bun test`, not `bun run pi`). Add a CI step: `bash deploy/scripts/pi-run.sh --version` (dry-run) to verify the script path. |
| Stale shim imported by a new file added between phases | LOW | Phase 6 | `uv run ruff check src` — `F401` unused import in shim signals the shim is dead |
| `insight_kit.agents` shim import not triggering re-register of `add_agents_parser` | LOW | Phase 4/5 | `tests/surfaces/test_ik_cli.py` covers `ik agents` command; the CLI registers the subparser at import time |
| `uv build` wheel missing new subpackage directories (if hatchling has an exclude glob) | LOW | Phase 3+ | `uv build` + extract wheel and verify `insight_kit/platform/` present. Run `uv build` in every phase gate. |
| Empty `scripts/` left behind confuses `bun run pi` lookup | LOW | Phase 4 | Remove directory in Phase 6; the `package.json` path is updated in Phase 4 so no functional break |

---

## 8. Dependency flow diagram (post-restructure)

```
deploy/
  └─ calls ──────────────────────┐
                                  ↓
surfaces/cli, surfaces/annotations
  └─ import ─────────────────────┐
                                  ↓
integrations/hamilton, integrations/agents
  └─ import ─────────────────────┐
                                  ↓
platform/gate, platform/harness
  └─ import ─────────────────────┐
                                  ↓
libs/errors, libs/config, libs/provenance, libs/validation

(gate never imports outward — C1/V5 invariant preserved)
```

The `.pi/` integration (repo root) calls `python -m insight_kit.platform.gate.cli` — it touches `platform/gate` only, never `integrations/` or `surfaces/`. This is the swappability guarantee: any L3 orchestrator can drive the gate by knowing the subprocess CLI contract alone.

---

## 9. Assets subpackage

`src/insight_kit/assets/` (Svelte components: `ClaimBlock.svelte`, `ClaimDelta.svelte`, `ClaimInline.svelte`, `claimsManifest.js`) is excluded from this plan's moves. It does not import Python and is not imported by any Python code. It is logically a `surfaces/` artifact but moving it adds Svelte component path risk without Python benefit. Recommended: leave in place and document it as a surfaces asset in a follow-up.

---

## Summary

| Metric | Value |
|---|---|
| Recommended packaging approach | Option A — single `insight_kit` package, internal group subdirectories |
| Total phases | 6 |
| Total Python source files moved | 28 |
| Total test files moved | 12 |
| Total script files moved | 2 |
| Shim files created (temporarily) | 11 |
| `pyproject.toml` changes | 2 lines (scripts entry point + ruff path) |
| `package.json` changes | 2 script paths (Phase 4) |
| Files inside `gate/` edited | 0 (freeze constraint honoured; only directory path changes) |
| `.pi/` moved | No (root constraint) |
| `viz/` moved | No (bun workspace root constraint) |
