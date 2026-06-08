---
query: "how to properly test a pi coding-agent extension"
date: 2026-05-22
tags: [synth, pi-coding-agent, testing, T18, insight-kit]
entities: ["pi-coding-agent", "pi-extensions", "insight-kit", "ExtensionAPI"]
sources:
  - "~/.bun/install/global/node_modules/@earendil-works/pi-coding-agent/docs/extensions.md"
  - "~/.bun/install/global/node_modules/@earendil-works/pi-coding-agent/docs/sdk.md"
  - "/tmp/repos/pi-subagents/test/support/mock-pi.ts"
  - "/tmp/repos/pi-subagents/test/unit/index-child-registration.test.ts"
  - "/tmp/repos/pi-autoresearch/extensions"
---

# Testing a `pi` coding-agent extension

Research + design notes for T18 — how `.pi/extensions/insight-kit.ts` is tested.

## TL;DR

A pi extension's default export is **just a factory** `(pi: ExtensionAPI) => void`.
The cleanest, fastest, most deterministic way to test it is to hand a
**fake `ExtensionAPI`** to that factory, capture every `registerTool` definition
and every `on` handler, then **invoke the captured `execute`/hook functions
directly** and assert on the results. No LLM, no API key, no pi runtime.

This is the pattern the most mature third-party pi extension — **pi-subagents** —
uses, and it is what insight-kit now uses.

## How pi extensions are structured (so you know what to test)

From `docs/extensions.md`:

- An extension is a TS file exporting `export default function (pi: ExtensionAPI)`.
- It is loaded by pi via **jiti** (no build step) from `.pi/extensions/*.ts`,
  `.pi/extensions/*/index.ts`, or the global `~/.pi/agent/extensions/`.
- Inside the factory it calls `pi.registerTool({name,label,description,parameters,execute})`,
  `pi.on(event, handler)`, `pi.registerCommand(...)`, etc.
- `pi.exec(cmd, args, opts)` is the sanctioned way to shell out; it returns
  `{stdout, stderr, code, killed}` (pi's `ExecResult`, see `dist/core/exec.d.ts`).
  **There is no stdin** — input must go on argv.
- A tool's `execute(toolCallId, params, signal, onUpdate, ctx)` returns an
  `AgentToolResult` (`{content, details}`) on success and **signals failure by
  throwing** — returning an error object never sets `isError`.
- The `tool_call` hook can return `{block:true, reason}`; `tool_result` can
  return a patch or nothing.

## What pi's own SDK offers for testing (and why we did not use it)

pi *does* ship an in-process SDK (`docs/sdk.md`, `dist/core/sdk.d.ts`):

- `createAgentSession({customTools, tools, noTools, sessionManager, resourceLoader})`
  builds a real `AgentSession`.
- `DefaultResourceLoader({additionalExtensionPaths, extensionFactories})` loads
  extension files; `extensionFactories` can inject an extension inline.
- `SessionManager.inMemory()` / `SettingsManager.inMemory()` avoid disk I/O.
- `runPrintMode(runtime, {...})` drives a single-shot prompt to completion.
- `loadExtensions` / `createExtensionRuntime` / `ExtensionRunner` live in
  `dist/core/extensions/{loader,runner}.d.ts`.

**Why this is the wrong tool for a unit test of one extension:**

1. `createAgentSession` + `runPrintMode` need a **real model** — pi exposes no
   mock/scripted model provider in its public exports, so any end-to-end SDK
   test would burn an API key and be non-deterministic.
2. `ExtensionRunner` is built to be fed by the loader, not a hand-made fake; its
   constructor wants the full `AgentSession` services graph.
3. The thing under test — tool registration, the TypeBox param schema, the
   `tool_call` block hook, the `pi.exec` argv — is **all reachable without a
   model**. Spinning up a session just adds an LLM dependency and flakiness.

The SDK route is the right choice only for a true "does the LLM call my tool"
integration test. That is a separate, model-gated concern and out of scope for
a deterministic test of the extension's wiring.

## How real pi extensions in the wild test themselves

| Repo | Runner | Extension-test technique |
|------|--------|--------------------------|
| **pi-subagents** | `node --test` (`node:test`) | **Hand-rolled fake `ExtensionAPI`** — a `Proxy` whose `registerTool`/`on` capture into local vars; unknown methods are no-op. Then it calls `registeredTool.execute(...)` / `renderCall(...)` directly. Also a **`mock-pi-script.mjs`** fake `pi` binary on `$PATH` for subprocess-spawning tests. See `test/support/mock-pi.ts` and `test/unit/index-child-registration.test.ts`. |
| **pi-autoresearch** | `node --experimental-strip-types --test` | Tests the **pure helper modules** (`jsonl.ts`, `compaction.ts`, schema) in isolation — same split insight-kit already has with `core.ts`. The pi-aware `index.ts`/`hooks.ts` are not driven through a runtime. |
| Fusion (`/tmp/repos/Fusion`) | vitest, `src/__tests__/` | **Not pi** — Fusion is its own plugin SDK (`@fusion/plugin-sdk`). Its `fusion-plugin-*` packages test manifest shape, route handlers, and runtime-adapter probes with mocked clients. Useful as a structural model (one `__tests__/` dir per package, mock the external client, assert behaviour) but its `Plugin` API is unrelated to pi's `ExtensionAPI`. |

The clear, repeated winner for *unit-testing a pi extension* is the
**pi-subagents fake-`ExtensionAPI`** approach.

### The pi-subagents fake (the canonical pattern)

```ts
const events = { on() { return () => {}; }, emit() {} };
let registeredTool;
const fakePi = new Proxy({
  events,
  registerTool(tool) { registeredTool = tool; },
  registerCommand() {}, registerShortcut() {}, /* ... */
}, { get(t, p) { return p in t ? t[p] : () => undefined; } });

registerSubagentExtension(fakePi);          // run the factory
await registeredTool.execute("id", {action:"list"}, signal, undefined, ctx);
```

A `Proxy` with a no-op fallback `get` keeps the fake tiny while the cast to
`ExtensionAPI` stays honest — only the methods the extension actually touches
need real implementations.

## Chosen approach for insight-kit (T18)

**Approach (b): hand-rolled fake `ExtensionAPI`, with a real-subprocess option.**

Rationale:

- The extension touches exactly three `pi` methods: `on`, `registerTool`,
  `exec`. A fake covering those three is ~150 lines and has zero flakiness.
- `pi.exec` is captured in the **factory closure**, so whatever `pi.exec` the
  fake provides is what the tool's `execute` calls. This gives a free choice
  per test: stub `pi.exec` with a scripted `ExecResult` for deterministic unit
  tests, OR let the fake **spawn a real `uv run`** for end-to-end tests. The
  Python gate is fast and already installed, so real e2e is cheap.
- It is the same approach pi-subagents validated in production.

### Test file layout

```
.pi/test/fake-extension-api.ts          ← the fake ExtensionAPI + ctx + event builders
.pi/test/insight-kit.extension.test.ts  ← 26 bun tests for the extension
.pi/lib/core.test.ts                    ← 12 bun tests for the pure wire logic (pre-existing)
```

Test files live in **`.pi/test/`, never `.pi/extensions/`** — pi's loader scans
only `.pi/extensions/*.ts` (and `*/index.ts`), so a `.test.ts` placed there
would be loaded *as an extension* and crash the loader (it calls the default
export with the real `pi`). Keeping tests one directory over is the safeguard.

Runner: **`bun test`** (the repo's runner; `core.test.ts` already uses
`bun:test`). `tsconfig.json` `include` extended to `test/**/*.ts`. The
`pi:test` package script now runs `bun test ./.pi/lib/ ./.pi/test/`.

### What is covered

1. **Tool registration** — exactly 4 `ik_*_emit` tools; `name == label`;
   record-type-specific descriptions; exactly one `tool_call` + one
   `tool_result` hook; every tool's `parameters` is an object schema.
2. **Param schema** — `typebox/value`'s `Value.Check` against the *registered*
   `parameters`: accepts a valid claim/research/intervention payload; rejects
   missing-required, unknown-property (`additionalProperties:false`),
   out-of-enum `tier`, and a nested-required (`intent.description`) violation.
3. **`tool_call` block hook** — blocks all 4 gate tools when
   `INSIGHT_KIT_RUN_DIR` is unset; passes (`undefined`) when set; ignores
   non-gate tools.
4. **`pi.exec` round-trip (stubbed)** — argv is `uv run python -m
   insight_kit.platform.gate.cli emit-<type> --payload <json>`; payload serialized
   verbatim as the last argv element; a finite timeout and the abort signal
   are forwarded; `ok:true` → `AgentToolResult` with the record in `details`;
   `ok:false` → thrown error carrying `rule_id`; no-output → thrown error.
5. **`tool_result` tally** — the observe-only hook runs without throwing for
   ok/error/non-gate results.
6. **End-to-end** — real `uv run` against a real `mkdtemp` run dir: a claim and
   a skill_use emit produce real on-disk content-addressed records; a research
   emit with an empty `snapshot` is **rejected by the gate (V2)** and the
   reject surfaces as a thrown `knowledge-snapshot-missing` error.

## Risks found in the extension / core while testing

These were observed while writing the tests. **Not bugs that break the tests** —
they are seam-fragility notes worth recording. The extension was not modified.

1. **Payload on argv, no stdin (`pi.exec` limitation).** `pi.exec` has no stdin
   channel, so `gateArgv` puts the whole JSON payload as a single argv element.
   A very large `snapshot`/`fields` payload could approach the OS `ARG_MAX`
   limit (~256 KB–2 MB depending on platform). The Python CLI *does* accept
   `--payload` or stdin, but the extension can only use `--payload`. For
   typical records this is fine; a pathological large snapshot is a latent
   failure mode. No quoting issue — `pi.exec` passes argv as an array straight
   to `spawn`, so no shell-quoting risk.

2. **Last-line stdout parse is fragile if the gate logs to stdout.**
   `parseGateResult` takes the **last** non-blank line of stdout and JSON-parses
   it. The CLI today prints exactly one JSON line, so this is correct. But if
   the gate (or any future `print()` / library it imports) writes a trailing
   line to **stdout** after the result, the parse silently reads the wrong
   line. Logging to **stderr** is safe. This is a contract the Python side must
   keep; it is not enforced by a test on the TS side. The existing
   `core.test.ts` "extra lines" test actually documents the *opposite*
   tolerance (noise *before* the result is fine) — noise *after* is the risk.

3. **Timeout produces a `killed` ExecResult, not a distinct error.** On a
   `GATE_EXEC_TIMEOUT_MS` (60s) timeout, `pi.exec` resolves with
   `killed:true` and likely empty stdout. `parseGateResult` then throws the
   generic "produced no output" error — the model is told the gate produced
   nothing, not that it *timed out*. A hung `uv` is correctly capped, but the
   error message could be clearer. Minor.

4. **jiti could load a stray `.test.ts` as an extension.** If a test file were
   ever placed under `.pi/extensions/`, pi's loader would `import` it and call
   its default export with the real `pi` — `bun:test`'s `describe/test` would
   run at import time and the missing default export would error the loader.
   Mitigation: tests live in `.pi/test/`. This is a placement discipline, not a
   code fix — worth a one-line note in `.pi/README.md` if not already there.

5. **`console.error` tally line is unconditional.** The `tool_result` hook
   prints `[insight-kit] gate emits this session: N ok / M rejected` to stderr
   on every gate tool result. Harmless (stderr, not stdout, so it cannot
   corrupt `parseGateResult`), but it is noise in a non-interactive/RPC run.
   Visible in the test output. Not a correctness issue.

6. **No re-validation against the TypeBox schema before `pi.exec`.** pi
   validates tool `params` against `parameters` before calling `execute`, and
   the Python CLI re-validates — so a bad payload is caught twice. But the
   extension itself does no validation; it trusts pi. If the extension were
   ever driven outside pi (as the tests do), a malformed payload goes straight
   to `uv`. The tests therefore exercise the schema *separately* via
   `Value.Check` rather than relying on `execute` to reject bad input — which
   is the correct division: schema-acceptance is pi's job, the extension's job
   is the subprocess round-trip.

## Verification

```sh
bun run pi:test        # 38 pass (12 core + 26 extension)
bun run pi:typecheck   # tsc -p .pi/tsconfig.json — clean
```
