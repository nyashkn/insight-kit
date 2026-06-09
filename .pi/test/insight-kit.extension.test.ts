/**
 * T18 — tests for the L3 pi extension itself (`../extensions/insight-kit.ts`).
 *
 * `../lib/core.test.ts` already covers the pure wire logic. This file covers
 * the *extension surface* that core.test.ts cannot reach:
 *   1. tool registration   — the 4 ik_*_emit tools, names, labels, descriptions
 *   2. param schemas       — the TypeBox-wrapped pydantic schema accepts good
 *                            LLM args and rejects bad ones (additionalProperties,
 *                            required, enums)
 *   3. tool_call block hook — fires when INSIGHT_KIT_RUN_DIR is unset, passes
 *                            when set, ignores non-gate tools
 *   4. pi.exec round-trip   — `execute` shells out with the correct argv and
 *                            timeout, returns an AgentToolResult on ok, throws
 *                            on a gate reject
 *   5. tool_result tally    — the emitted/rejected counter increments
 *   6. end-to-end           — a real `uv run` against a real temp run dir, for
 *                            both an accepted emit and a gate reject (V2)
 *
 * Approach: a hand-rolled fake `ExtensionAPI` (see ./fake-extension-api.ts).
 * The extension's default export is a plain factory; the fake captures every
 * `registerTool` definition and every `on` handler, so each unit can be driven
 * directly. `pi.exec` is captured in the factory closure, so the SAME fake
 * `pi.exec` is what `execute` calls — a test either stubs it with a scripted
 * ExecResult (deterministic units) or lets it spawn a real `uv run` (e2e).
 *
 * Run: `bun test .pi/test/`  — no pi runtime, no LLM, no API key needed.
 */
import { afterAll, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Value } from "typebox/value";
import insightKitExtension from "../extensions/insight-kit.ts";
import { GATE_TOOL_NAMES } from "../lib/core.ts";
import {
	createFakeContext,
	createFakeExtensionAPI,
	type FakeExecResult,
	type FakeExtensionAPI,
	toolCallEvent,
	toolResultEvent,
} from "./fake-extension-api.ts";

// --- shared helpers ---------------------------------------------------------

/** Load the extension into a fresh fake pi and return the fake for inspection. */
function loadExtension(): FakeExtensionAPI {
	const fake = createFakeExtensionAPI();
	insightKitExtension(fake.pi);
	return fake;
}

/** Fetch a registered tool, asserting it exists (keeps tests free of `?.`). */
function getTool(fake: FakeExtensionAPI, name: string) {
	const tool = fake.tools.get(name);
	if (!tool) throw new Error(`tool '${name}' was not registered`);
	return tool;
}

/** Fetch a registered tool's param schema, asserting the tool exists. */
function getSchema(name: string) {
	return getTool(loadExtension(), name).parameters;
}

/** A well-formed ok ExecResult for tool `toolName`'s gate emit. */
function okExec(recordType: string): FakeExecResult {
	return {
		stdout: `${JSON.stringify({
			ok: true,
			record: {
				record_id: "abc1234567890def",
				record_type: recordType,
				record_fingerprint: "f".repeat(64),
				run_dir: "/tmp/run",
			},
		})}\n`,
		stderr: "",
		code: 0,
		killed: false,
	};
}

/** A well-formed gate-reject ExecResult (ok:false, exit 1). */
function rejectExec(): FakeExecResult {
	return {
		stdout: `${JSON.stringify({
			ok: false,
			error: {
				rule_id: "knowledge-snapshot-missing",
				message: "research record requires a non-empty snapshot",
				suggestion: "Pass snapshot=<dict of the captured results>",
			},
		})}\n`,
		stderr: "",
		code: 1,
		killed: false,
	};
}

/** Restore the original INSIGHT_KIT_RUN_DIR after each test that mutates it. */
const ORIGINAL_RUN_DIR = process.env.INSIGHT_KIT_RUN_DIR;
beforeEach(() => {
	delete process.env.INSIGHT_KIT_RUN_DIR;
});
afterAll(() => {
	if (ORIGINAL_RUN_DIR === undefined) delete process.env.INSIGHT_KIT_RUN_DIR;
	else process.env.INSIGHT_KIT_RUN_DIR = ORIGINAL_RUN_DIR;
});

// --- 1. tool registration ---------------------------------------------------

describe("tool registration", () => {
	test("registers exactly the four ik_*_emit tools", () => {
		const fake = loadExtension();
		expect([...fake.tools.keys()].sort()).toEqual([...GATE_TOOL_NAMES].sort());
		expect(fake.tools.size).toBe(4);
	});

	test("each tool has name == label and a non-trivial description", () => {
		const fake = loadExtension();
		for (const [name, tool] of fake.tools) {
			expect(tool.name).toBe(name);
			expect(tool.label).toBe(name);
			expect(tool.description.length).toBeGreaterThan(80);
		}
	});

	test("tool descriptions are record-type specific (not copy-pasted)", () => {
		const fake = loadExtension();
		expect(fake.tools.get("ik_claim_emit")?.description).toContain("claim");
		expect(fake.tools.get("ik_intervention_emit")?.description).toContain(
			"intervention",
		);
		expect(fake.tools.get("ik_research_emit")?.description).toContain(
			"snapshot",
		);
		expect(fake.tools.get("ik_skill_use_emit")?.description).toContain(
			"skill_use",
		);
	});

	test("registers one tool_call hook and one tool_result hook", () => {
		const fake = loadExtension();
		expect(fake.toolCallHandlers.length).toBe(1);
		expect(fake.toolResultHandlers.length).toBe(1);
	});

	test("every tool exposes a TypeBox-wrapped param schema", () => {
		const fake = loadExtension();
		for (const tool of fake.tools.values()) {
			// Type.Unsafe wraps a JSON Schema; it must at least be an object schema.
			expect((tool.parameters as { type?: string }).type).toBe("object");
		}
	});
});

// --- 2. param-schema acceptance / rejection ---------------------------------

describe("param schema (TypeBox Value.Check on the registered parameters)", () => {
	test("ik_claim_emit accepts a minimal valid claim payload", () => {
		const schema = getSchema("ik_claim_emit");
		expect(
			Value.Check(schema, {
				claim_id: "AB-D-001",
				fields: { revenue: { value: 123456, fmt_hint: "$,.0f" } },
			}),
		).toBe(true);
	});

	test("ik_claim_emit rejects a payload missing the required claim_id", () => {
		const schema = getSchema("ik_claim_emit");
		expect(Value.Check(schema, { fields: {} })).toBe(false);
	});

	test("ik_claim_emit rejects an unknown property (additionalProperties:false)", () => {
		const schema = getSchema("ik_claim_emit");
		expect(
			Value.Check(schema, {
				claim_id: "AB-D-001",
				fields: {},
				not_a_real_field: "x",
			}),
		).toBe(false);
	});

	test("ik_claim_emit rejects an out-of-enum tier value", () => {
		const schema = getSchema("ik_claim_emit");
		expect(
			Value.Check(schema, {
				claim_id: "AB-D-001",
				fields: {},
				tier: "secret",
			}),
		).toBe(false);
		// the two real enum members pass
		expect(
			Value.Check(schema, { claim_id: "AB-D-001", fields: {}, tier: "draft" }),
		).toBe(true);
		expect(
			Value.Check(schema, {
				claim_id: "AB-D-001",
				fields: {},
				tier: "published",
			}),
		).toBe(true);
	});

	test("ik_research_emit requires query, research_id, snapshot, snapshot_ref, source", () => {
		const schema = getSchema("ik_research_emit");
		expect(Value.Check(schema, {})).toBe(false);
		expect(
			Value.Check(schema, {
				research_id: "R-1",
				query: "what is X",
				source: "web",
				snapshot_ref: "tavily",
				snapshot: { data: [1, 2, 3] },
			}),
		).toBe(true);
	});

	test("ik_intervention_emit requires the nested intent.description", () => {
		const schema = getSchema("ik_intervention_emit");
		// intent present but missing its required `description` -> reject
		expect(
			Value.Check(schema, { intervention_id: "IV-1", intent: {} }),
		).toBe(false);
		expect(
			Value.Check(schema, {
				intervention_id: "IV-1",
				intent: { description: "raise meta budget" },
			}),
		).toBe(true);
	});
});

// --- 3. tool_call block hook ------------------------------------------------

describe("tool_call block hook (INSIGHT_KIT_RUN_DIR gate)", () => {
	test("blocks a gate tool when INSIGHT_KIT_RUN_DIR is unset", async () => {
		const fake = loadExtension();
		const hook = fake.toolCallHandlers[0];
		const result = await hook(
			toolCallEvent("ik_claim_emit", {}),
			createFakeContext(),
		);
		expect(result).toBeDefined();
		expect(result?.block).toBe(true);
		expect(result?.reason).toContain("INSIGHT_KIT_RUN_DIR");
		expect(result?.reason).toContain("ik_claim_emit");
	});

	test("passes (returns undefined) when INSIGHT_KIT_RUN_DIR is set", async () => {
		process.env.INSIGHT_KIT_RUN_DIR = "/tmp/some-run";
		const fake = loadExtension();
		const result = await fake.toolCallHandlers[0](
			toolCallEvent("ik_research_emit", {}),
			createFakeContext(),
		);
		expect(result).toBeUndefined();
	});

	test("ignores non-gate tools regardless of INSIGHT_KIT_RUN_DIR", async () => {
		const fake = loadExtension();
		// run dir unset, but `bash` is not a gate tool -> must not block
		const result = await fake.toolCallHandlers[0](
			toolCallEvent("bash", { command: "ls" }),
			createFakeContext(),
		);
		expect(result).toBeUndefined();
	});

	test("blocks every one of the four gate tools when run dir is unset", async () => {
		const fake = loadExtension();
		for (const name of GATE_TOOL_NAMES) {
			const result = await fake.toolCallHandlers[0](
				toolCallEvent(name, {}),
				createFakeContext(),
			);
			expect(result?.block).toBe(true);
		}
	});
});

// --- 4. pi.exec round-trip (stubbed) ----------------------------------------

describe("tool execute (pi.exec stubbed — invocation shape & result mapping)", () => {
	test("execute drives `uv run` with the gate argv and the JSON payload on argv", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => okExec("claim"));
		const tool = fake.tools.get("ik_claim_emit");
		const params = { claim_id: "AB-D-001", fields: { rev: { value: 1 } } };
		await tool?.execute("call-1", params, undefined, undefined, createFakeContext());

		expect(fake.execCalls.length).toBe(1);
		const call = fake.execCalls[0];
		expect(call.command).toBe("uv");
		// argv: run python -m insight_kit.platform.gate.cli emit-claim --payload <json>
		expect(call.args.slice(0, 6)).toEqual([
			"run",
			"python",
			"-m",
			"insight_kit.platform.gate.cli",
			"emit-claim",
			"--payload",
		]);
		// the LLM params are serialized verbatim as the last argv element
		expect(JSON.parse(call.args[6])).toEqual(params);
	});

	test("each tool maps to its own emit-<type> subcommand", async () => {
		const fake = loadExtension();
		fake.setExecStub((c) => okExec(c.args[4].replace("emit-", "")));
		const expected: Record<string, string> = {
			ik_claim_emit: "emit-claim",
			ik_intervention_emit: "emit-intervention",
			ik_research_emit: "emit-research",
			ik_skill_use_emit: "emit-skill-use",
		};
		for (const [name, subcommand] of Object.entries(expected)) {
			await fake.tools
				.get(name)
				?.execute("c", {}, undefined, undefined, createFakeContext());
			expect(fake.execCalls.at(-1)?.args[4]).toBe(subcommand);
		}
	});

	test("execute passes a finite timeout so a hung `uv` cannot stall pi", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => okExec("claim"));
		await fake.tools
			.get("ik_claim_emit")
			?.execute("c", {}, undefined, undefined, createFakeContext());
		const timeout = fake.execCalls[0].options?.timeout;
		expect(typeof timeout).toBe("number");
		expect(timeout).toBeGreaterThan(0);
	});

	test("execute forwards the abort signal to pi.exec", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => okExec("claim"));
		const controller = new AbortController();
		await fake.tools
			.get("ik_claim_emit")
			?.execute("c", {}, controller.signal, undefined, createFakeContext());
		expect(fake.execCalls[0].options?.signal).toBe(controller.signal);
	});

	test("on ok:true execute returns an AgentToolResult carrying the record", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => okExec("claim"));
		const result = await fake.tools
			.get("ik_claim_emit")
			?.execute("c", {}, undefined, undefined, createFakeContext());
		expect(result?.content?.[0]?.type).toBe("text");
		expect((result?.content?.[0] as { text: string }).text).toContain(
			"abc1234567890def",
		);
		// the structured record is surfaced in `details` for rendering / state
		expect((result?.details as { record_id: string }).record_id).toBe(
			"abc1234567890def",
		);
	});

	test("on ok:false execute throws the gate reject (rule_id + suggestion)", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => rejectExec());
		const tool = fake.tools.get("ik_research_emit");
		expect(
			tool?.execute("c", {}, undefined, undefined, createFakeContext()),
		).rejects.toThrow(/knowledge-snapshot-missing/);
	});

	test("execute throws when the subprocess produced no parseable output", async () => {
		const fake = loadExtension();
		fake.setExecStub(() => ({
			stdout: "",
			stderr: "uv: command not found",
			code: 127,
			killed: false,
		}));
		expect(
			fake.tools
				.get("ik_claim_emit")
				?.execute("c", {}, undefined, undefined, createFakeContext()),
		).rejects.toThrow(/no output/);
	});
});

// --- 5. tool_result tally hook ----------------------------------------------

describe("tool_result tally hook", () => {
	test("does not throw for gate-tool ok / error results, ignores non-gate tools", async () => {
		const fake = loadExtension();
		const hook = fake.toolResultHandlers[0];
		// these update internal counters; assert they run without throwing and
		// return no patch (the hook is observe-only). The handler is synchronous,
		// so await its (possibly-undefined) return rather than wrapping in a
		// promise matcher.
		expect(
			await hook(toolResultEvent("ik_claim_emit", false), createFakeContext()),
		).toBeUndefined();
		expect(
			await hook(toolResultEvent("ik_research_emit", true), createFakeContext()),
		).toBeUndefined();
		expect(
			await hook(toolResultEvent("bash", false), createFakeContext()),
		).toBeUndefined();
	});
});

// --- 6. end-to-end: real `uv run` against a real temp run dir ---------------

describe("end-to-end (real `uv run` subprocess + real temp run dir)", () => {
	const repoRoot = join(import.meta.dir, "..", "..");
	const runDirs: string[] = [];

	function freshRunDir(): string {
		const d = mkdtempSync(join(tmpdir(), "ik-pi-e2e-"));
		runDirs.push(d);
		return d;
	}

	afterAll(() => {
		for (const d of runDirs) rmSync(d, { recursive: true, force: true });
	});

	test("ik_claim_emit emits a real record through the L1 gate", async () => {
		const runDir = freshRunDir();
		process.env.INSIGHT_KIT_RUN_DIR = runDir;
		const fake = loadExtension();
		// no exec stub -> the fake spawns a real `uv run`
		const tool = fake.tools.get("ik_claim_emit");
		// claim_id must match ^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$
		const result = await tool?.execute(
			"e2e-claim",
			{
				claim_id: "EE-D-001",
				fields: { revenue: { value: 999, fmt_hint: "$,.0f" } },
			},
			undefined,
			undefined,
			// run uv from the repo root so the package resolves
			createFakeContext(repoRoot),
		);
		const record = result?.details as { record_id: string; record_type: string };
		expect(record.record_type).toBe("claim");
		expect(record.record_id).toMatch(/^[0-9a-f]{16}$/);
		// the gate actually wrote the content-addressed record to disk
		const onDisk = readFileSync(
			join(runDir, "records", record.record_id, "record.json"),
			"utf8",
		);
		expect(JSON.parse(onDisk).claim_id).toBe("EE-D-001");
	}, 30_000);

	test("ik_research_emit with an empty snapshot is rejected by the gate (V2)", async () => {
		process.env.INSIGHT_KIT_RUN_DIR = freshRunDir();
		const fake = loadExtension();
		const tool = fake.tools.get("ik_research_emit");
		// snapshot:{} passes CLI arg-validation but the gate rejects it (V20).
		// The reject must surface as a thrown Error carrying the rule_id, so the
		// LLM sees a zero-partial-write failure it can correct.
		expect(
			tool?.execute(
				"e2e-research-reject",
				{
					research_id: "E2E-R-001",
					query: "what is the conversion rate",
					source: "web",
					snapshot_ref: "tavily",
					snapshot: {},
				},
				undefined,
				undefined,
				createFakeContext(repoRoot),
			),
		).rejects.toThrow(/knowledge-snapshot-missing/);
	}, 30_000);

	test("ik_skill_use_emit emits a real record end-to-end", async () => {
		const runDir = freshRunDir();
		process.env.INSIGHT_KIT_RUN_DIR = runDir;
		const fake = loadExtension();
		const result = await fake.tools.get("ik_skill_use_emit")?.execute(
			"e2e-skill",
			{
				skill_use_id: "E2E-X-001",
				tool: "tavily-search",
				source: "tavily",
				snapshot_ref: "search-results",
				snapshot: { hits: [{ url: "https://example.com", title: "X" }] },
			},
			undefined,
			undefined,
			createFakeContext(repoRoot),
		);
		const record = result?.details as { record_type: string };
		expect(record.record_type).toBe("skill_use");
	}, 30_000);
});
