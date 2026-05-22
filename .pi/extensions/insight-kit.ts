/**
 * T18 — L3 pi extension: the insight-kit L1 typed-record gate, exposed to pi.
 *
 * Registers the four ik_*_emit tools (I.emit — one typed wrapper per record
 * type). Each tool's `parameters` is the pydantic-derived schema (C5, see
 * ../lib/schema.generated.ts) wrapped as a TypeBox schema. `execute` shells out
 * to the L1 gate via `uv run` (C4 — the lang seam; the gate stays pure Python)
 * and either returns the content-addressed record or throws the gate's reject
 * reason so the model sees it (V2 — a reject is a zero-partial-write failure).
 *
 * Hooks:
 *  - tool_call   gates an emit — blocks when INSIGHT_KIT_RUN_DIR is unset (the
 *                gate would reject anyway; blocking early is a faster, clearer
 *                signal than a subprocess round-trip).
 *  - tool_result observes — the L3-side mirror of RunState's accept/reject tally.
 *
 * This file is the ONLY pi-aware module; all wire logic lives in ../lib/core.ts
 * so it can be unit-tested without the pi runtime. Cites: C4, C5, I.emit, V1, V2.
 */
import type {
	AgentToolResult,
	ExtensionAPI,
	ToolCallEvent,
	ToolResultEvent,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
	GATE_TOOL_RECORD_TYPE,
	type GateRecordType,
	gateArgv,
	gateErrorMessage,
	isGateTool,
	parseGateResult,
} from "../lib/core.ts";
import { recordParamSchemas } from "../lib/schema.generated.ts";

/** A gate emit is a quick subprocess; cap it so a hung `uv` cannot stall pi. */
const GATE_EXEC_TIMEOUT_MS = 60_000;

const TOOL_DESCRIPTION: Record<GateRecordType, string> = {
	claim:
		"Emit a typed `claim` record — an analytical assertion (named field values " +
		"with optional fmt_hints) — through the insight-kit L1 gate. The gate " +
		"validates, content-addresses, and immutably stores it. A published-tier " +
		"claim with thin coverage or an incomplete fingerprint set is downgraded " +
		"or rejected. Use draft tier unless the full provenance set is present.",
	intervention:
		"Emit a typed `intervention` record — an outside-world action — through the " +
		"insight-kit L1 gate. Carries `intent` (what was decided) and `realized` " +
		"(the actual external result). A published intervention is rejected unless " +
		"`realized` is present with status applied/partial/failed (V19).",
	research:
		"Emit a typed `research` record — a knowledge-acquisition result from " +
		"external research — through the insight-kit L1 gate. Requires a non-empty " +
		"`snapshot` of the captured results; the gate persists and content-" +
		"addresses it (V20). Cite this record from any claim it informs.",
	skill_use:
		"Emit a typed `skill_use` record — a knowledge-acquisition result from a " +
		"tool/skill invocation — through the insight-kit L1 gate. Requires a non-" +
		"empty `snapshot` of the captured results (V20). Cite this record from any " +
		"claim it informs.",
};

export default function insightKitExtension(pi: ExtensionAPI): void {
	// --- tool_call gate: an emit needs a run directory to write into ---
	pi.on("tool_call", (event: ToolCallEvent) => {
		if (isGateTool(event.toolName) && !process.env.INSIGHT_KIT_RUN_DIR) {
			return {
				block: true,
				reason:
					`${event.toolName}: INSIGHT_KIT_RUN_DIR is not set. The L1 gate has ` +
					"no run directory to write the record into — set it before emitting.",
			};
		}
	});

	// --- tool_result observability: L3-side mirror of accept/reject counts ---
	let emitted = 0;
	let rejected = 0;
	pi.on("tool_result", (event: ToolResultEvent) => {
		if (!isGateTool(event.toolName)) return;
		if (event.isError) rejected += 1;
		else emitted += 1;
		// Quiet by default — opt in with INSIGHT_KIT_DEBUG so RPC / non-interactive
		// runs are not spammed on every emit.
		if (process.env.INSIGHT_KIT_DEBUG) {
			console.error(
				`[insight-kit] gate emits this session: ${emitted} ok / ${rejected} rejected`,
			);
		}
	});

	// --- the four typed-emit tools (I.emit) ---
	for (const [toolName, recordType] of Object.entries(GATE_TOOL_RECORD_TYPE)) {
		pi.registerTool({
			name: toolName,
			label: toolName,
			description: TOOL_DESCRIPTION[recordType],
			parameters: Type.Unsafe<Record<string, unknown>>(recordParamSchemas[recordType]),
			async execute(_toolCallId, params, signal): Promise<AgentToolResult<unknown>> {
				const exec = await pi.exec("uv", gateArgv(recordType, JSON.stringify(params)), {
					signal,
					timeout: GATE_EXEC_TIMEOUT_MS,
				});
				const result = parseGateResult(exec);
				if (!result.ok) {
					// pi convention: a tool signals failure by throwing, not by
					// encoding an error in `content`. This carries the V2 reject
					// (rule_id + suggestion) back to the model.
					throw new Error(gateErrorMessage(recordType, result.error));
				}
				return {
					content: [
						{
							type: "text",
							text:
								`Emitted ${result.record.record_type} ${result.record.record_id} ` +
								`(record_fingerprint ${result.record.record_fingerprint}).`,
						},
					],
					details: result.record,
				};
			},
		});
	}
}
