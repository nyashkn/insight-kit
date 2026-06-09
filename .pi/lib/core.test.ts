/**
 * T18 — unit tests for the L3<->L1 seam logic (C4).
 *
 * Run: `bun test .pi/lib/core.test.ts`. core.ts is dependency-free, so this
 * runs without resolving the pi runtime.
 */
import { describe, expect, test } from "bun:test";
import {
	GATE_TOOL_NAMES,
	GATE_TOOL_RECORD_TYPE,
	type GateExecResult,
	gateArgv,
	gateErrorMessage,
	isGateTool,
	parseGateResult,
} from "./core.ts";

function mkExec(stdout: string, stderr = "", code = 0): GateExecResult {
	return { stdout, stderr, code };
}

const OK_LINE = JSON.stringify({
	ok: true,
	record: {
		record_id: "abc1234567890def",
		record_type: "claim",
		record_fingerprint: "f".repeat(64),
		run_dir: "/run",
	},
});
const ERR_LINE = JSON.stringify({
	ok: false,
	error: { rule_id: "coverage-warning-missing", message: "thin coverage", suggestion: "add one" },
});

describe("tool registry", () => {
	test("four gate tools map to the four record types", () => {
		expect(GATE_TOOL_NAMES.sort()).toEqual(
			["ik_claim_emit", "ik_intervention_emit", "ik_research_emit", "ik_skill_use_emit"].sort(),
		);
		expect(GATE_TOOL_RECORD_TYPE.ik_claim_emit).toBe("claim");
		expect(GATE_TOOL_RECORD_TYPE.ik_skill_use_emit).toBe("skill_use");
	});

	test("isGateTool recognises only the gate tools", () => {
		expect(isGateTool("ik_claim_emit")).toBe(true);
		expect(isGateTool("ik_research_emit")).toBe(true);
		expect(isGateTool("bash")).toBe(false);
		expect(isGateTool("read")).toBe(false);
	});
});

describe("gateArgv", () => {
	test("claim emit drives `uv run` + the emit-claim subcommand", () => {
		expect(gateArgv("claim", '{"claim_id":"X"}')).toEqual([
			"run",
			"python",
			"-m",
			"insight_kit.platform.gate.cli",
			"emit-claim",
			"--payload",
			'{"claim_id":"X"}',
		]);
	});

	test("each record type maps to its hyphenated subcommand", () => {
		expect(gateArgv("intervention", "{}")[4]).toBe("emit-intervention");
		expect(gateArgv("research", "{}")[4]).toBe("emit-research");
		expect(gateArgv("skill_use", "{}")[4]).toBe("emit-skill-use");
	});
});

describe("parseGateResult", () => {
	test("parses an ok result", () => {
		const r = parseGateResult(mkExec(`${OK_LINE}\n`));
		expect(r.ok).toBe(true);
		if (r.ok) expect(r.record.record_id).toBe("abc1234567890def");
	});

	test("parses a gate-reject result (ok:false)", () => {
		const r = parseGateResult(mkExec(`${ERR_LINE}\n`, "", 1));
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.error.rule_id).toBe("coverage-warning-missing");
	});

	test("uses the LAST json line when the subprocess prints extra lines", () => {
		const r = parseGateResult(mkExec(`some log noise\n${OK_LINE}\n`));
		expect(r.ok).toBe(true);
	});

	test("throws with stderr when the subprocess produced no output", () => {
		expect(() => parseGateResult(mkExec("", "uv: command not found", 127))).toThrow(
			/no output.*uv: command not found/,
		);
	});

	test("throws when the gate emits non-JSON", () => {
		expect(() => parseGateResult(mkExec("Traceback (most recent call last)"))).toThrow(
			/non-JSON/,
		);
	});

	test("throws when the JSON lacks an `ok` field", () => {
		expect(() => parseGateResult(mkExec('{"unexpected":1}'))).toThrow(/unrecognised/);
	});
});

describe("gateErrorMessage", () => {
	test("includes record type, rule_id, message and suggestion", () => {
		const msg = gateErrorMessage("claim", {
			rule_id: "coverage-warning-missing",
			message: "thin coverage",
			suggestion: "add a coverage_warning",
		});
		expect(msg).toContain("claim");
		expect(msg).toContain("coverage-warning-missing");
		expect(msg).toContain("thin coverage");
		expect(msg).toContain("add a coverage_warning");
	});

	test("omits the suggestion clause when there is none", () => {
		const msg = gateErrorMessage("research", {
			rule_id: "knowledge-snapshot-missing",
			message: "no snapshot",
		});
		expect(msg).toContain("knowledge-snapshot-missing");
		expect(msg.endsWith("no snapshot")).toBe(true);
	});
});
