# Eval harness — local containerization

The eval harness (`src/insight_kit/harness.py`) diffs a claim-producing run
against an audited-truth **golden** and classifies every field difference as
`match` / `regression` / `legitimate` / `coverage_drop` (V11, C10, C11).

The harness *logic* is pure and is tested in `tests/test_harness.py` on
synthetic golden + negative fixtures — no real data, no credentials.

This document is the recipe for the **other** half: running the harness against
**real `nairomarket` / `growth_insights` business data** inside a container.

## Hard constraints

- **The real-data image is LOCAL-only. Never `docker push` it to any registry.**
  It contains real business data; a pushed image is a data leak. Build it, run
  it, discard it locally.
- **No credentials in the image.** The image carries code only. Provider
  credentials are pulled at *runtime* from Infisical — see below.
- **The golden is audited truth, never raw `agent_runs`** (C11). Buggy historical
  runs are negative fixtures, not goldens (RT6).

## Credentials — Infisical

Application/harness-runtime secrets live in an Infisical project (`naimarket`),
not in `.env` files, not in the image, not in git.

1. Create the Infisical project `naimarket`; migrate the keys currently in
   `growth_insights/.env` into it, then delete the on-disk `.env`.
2. Create a Machine Identity `mi-eval-harness` (Universal Auth) scoped read-only
   to just the secret paths the harness needs (least privilege).
3. At container launch, inject **only** that identity's bootstrap credential via
   env — never bake it in:

   ```sh
   docker run --rm \
     -e INFISICAL_CLIENT_ID="$MI_EVAL_HARNESS_CLIENT_ID" \
     -e INFISICAL_CLIENT_SECRET="$MI_EVAL_HARNESS_CLIENT_SECRET" \
     -v "$PWD/growth_insights:/data:ro" \
     insight-kit-eval:local \
     infisical run --projectId naimarket -- python -m insight_kit.harness ...
   ```

   `infisical run` injects the provider keys into the process env without ever
   writing them to disk. The bootstrap `CLIENT_ID/CLIENT_SECRET` are the launch
   environment's responsibility (its own secret store) — not chat, git, memory.

Net effect: N provider keys collapse to 1 rotatable bootstrap credential, and
the frozen L1 gate never sees a credential.

## Harbor — later

When the harness verifier is stable and the first AutoAgent meta-loop is wired,
this harness becomes a Harbor task `tests/checks.py` verifier (Harbor adoption
was deferred — see `docs/ck-build-log.md`). The harness logic does not change;
Harbor wraps the outside (container orchestration, RewardKit scalar, runner).
