/**
 * T18 — pure L3<->L1 seam logic for the insight-kit pi extension.
 *
 * Zero external imports — this module is fully self-contained so it unit-tests
 * with `bun test` without resolving the globally installed pi packages. The
 * extension entry point (../extensions/insight-kit.ts) supplies the pi runtime;
 * this file owns the wire contract (C4).
 */

/**
 * The subset of pi's `ExecResult` the seam reads. pi's real `ExecResult` is a
 * structural superset (it also carries `killed`), so it satisfies this without
 * a pi import — keeping this module dependency-free and testable.
 */
export interface GateExecResult {
	stdout: string;
	stderr: string;
	code: number;
}

/** The four typed-record kinds the L1 gate accepts. */
export type GateRecordType = "claim" | "intervention" | "research" | "skill_use";

/** LLM-facing tool name -> gate record type (I.emit — one wrapper per type). */
export const GATE_TOOL_RECORD_TYPE: Record<string, GateRecordType> = {
	ik_claim_emit: "claim",
	ik_intervention_emit: "intervention",
	ik_research_emit: "research",
	ik_skill_use_emit: "skill_use",
};

export const GATE_TOOL_NAMES = Object.keys(GATE_TOOL_RECORD_TYPE);

/** Gate record type -> `insight_kit.platform.gate.cli` subcommand. */
const CLI_SUBCOMMAND: Record<GateRecordType, string> = {
	claim: "emit-claim",
	intervention: "emit-intervention",
	research: "emit-research",
	skill_use: "emit-skill-use",
};

/** True iff `name` is one of the four insight-kit emit tools. */
export function isGateTool(name: string): boolean {
	return name in GATE_TOOL_RECORD_TYPE;
}

/** Build the `uv run` argv that drives one gate emit (the C4 lang seam). */
export function gateArgv(recordType: GateRecordType, payloadJson: string): string[] {
	return [
		"run",
		"python",
		"-m",
		"insight_kit.platform.gate.cli",
		CLI_SUBCOMMAND[recordType],
		"--payload",
		payloadJson,
	];
}

/** Successful emit — a content-addressed record reference. */
export interface GateOk {
	ok: true;
	record: {
		record_id: string;
		record_type: string;
		record_fingerprint: string;
		run_dir: string;
	};
}

/** A gate reject (V2 — zero partial write) or a CLI usage error. */
export interface GateError {
	ok: false;
	error: { rule_id: string; message: string; suggestion?: string | null };
}

export type GateResult = GateOk | GateError;

/**
 * Parse a gate CLI `ExecResult` into a `GateResult`.
 *
 * The CLI always prints exactly one self-describing JSON line — `ok` tells
 * success from reject, independent of the exit code. Throws only when the
 * subprocess produced no parseable line at all (e.g. `uv` itself failed).
 */
export function parseGateResult(exec: GateExecResult): GateResult {
	const line = exec.stdout
		.trim()
		.split("\n")
		.map((l: string) => l.trim())
		.filter(Boolean)
		.pop();
	if (!line) {
		throw new Error(
			`insight-kit gate produced no output (exit ${exec.code}): ` +
				`${exec.stderr.trim() || "<no stderr>"}`,
		);
	}
	let parsed: unknown;
	try {
		parsed = JSON.parse(line);
	} catch {
		throw new Error(`insight-kit gate emitted non-JSON (exit ${exec.code}): ${line}`);
	}
	if (typeof parsed !== "object" || parsed === null || !("ok" in parsed)) {
		throw new Error(`insight-kit gate emitted an unrecognised result: ${line}`);
	}
	return parsed as GateResult;
}

/**
 * Render a `GateError` as the message thrown from a tool `execute`.
 *
 * pi convention: a tool signals failure by throwing, not by encoding an error
 * in its content — this gives the model the rule_id and the fix suggestion.
 */
export function gateErrorMessage(recordType: GateRecordType, err: GateError["error"]): string {
	const suffix = err.suggestion ? ` — ${err.suggestion}` : "";
	return `insight-kit gate rejected the ${recordType} [${err.rule_id}]: ${err.message}${suffix}`;
}
