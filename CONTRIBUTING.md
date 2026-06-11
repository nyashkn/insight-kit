# Contributing to insight-kit

Thanks for your interest. insight-kit is alpha; the gate API may change before
1.0. Issues and PRs are welcome.

## Dev setup

The project uses [`uv`](https://docs.astral.sh/uv/) for Python and `bun` for the
TypeScript lang-seam (`.pi/`, `viz/`).

```bash
# install Python deps (dev + the extras CI runs against)
uv sync --extra dev --extra polars

# install the pre-commit hooks (gitleaks secret scan runs on every commit)
uv run pre-commit install

# run the test suite
uv run pytest

# lint
uv run ruff check src tests

# build the wheel
uv build
```

Optional extras are declared in `pyproject.toml` under
`[project.optional-dependencies]`: `hamilton`, `polars`, `pandas`, `evidence`,
`observability`. Install what you need, e.g. `uv sync --extra hamilton`.

### TypeScript seam (optional)

If you touch `viz/` or `.pi/`:

```bash
bun install
bun run pi:typecheck
bun run pi:test
```

## Tests

- `uv run pytest` runs the fast suite. Slower / probabilistic / networked tests
  are opt-in via markers: `-m slow`, `-m eval`, `-m network` (see
  `[tool.pytest.ini_options]` in `pyproject.toml`).
- New behavior needs a test. New schema fields must be reflected at the `.pi`
  tool surface in the same PR — CI has a schema-drift guard that fails otherwise.
- The gate modules under `src/insight_kit/platform/gate/` must not import
  `hamilton` or `pi` (purity invariant, enforced by an AST scan in
  `tests/platform/gate/test_purity.py`).

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):
`type(scope): summary`.

Common types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `style`.

**The subject line must be self-explanatory to someone who has never read
`SPEC.md`.** Internal task / invariant IDs (`T##`, `V##`, `C##`, `D##`) are
project bookkeeping — they belong in a `Refs:` trailer, not the subject.

Good:

```
fix(gate): flag claims that skip a high-relevance API the search surfaced

The endpoint-coverage critic now scopes the used-endpoint set to the
research bundle under check, so usage from a different bundle in the same
run can no longer mask a real gap.

Refs: T32, V16
```

Avoid:

```
fix(gate): T32 hardening + scope used-set       # opaque without the spec
feat: full epic (T1–T33)                        # one commit, unreviewable
docs(spec): T28-T32 . -> x                       # private checkbox notation
```

Guidelines:

- One logical change per commit. No multi-task "epic" commits.
- Imperative mood in the subject ("add", not "added").
- Keep the subject under ~72 chars; put detail in the body.

## Before opening a PR

```bash
uv run ruff check src tests
uv run pytest
uv build
```

CI runs these across Python 3.11–3.13, plus a gitleaks scan and the `.pi`
TypeScript seam. Please don't commit secrets or absolute local paths — the
gitleaks pre-commit hook catches most secrets, but machine-specific paths
(`/Users/...`, sibling-repo names) should be parameterized via env vars or
fixtures.

## License

By contributing, you agree your contributions are licensed under the
[MIT License](LICENSE).
