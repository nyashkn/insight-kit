/**
 * T18 — a hand-rolled fake `ExtensionAPI` for testing `../extensions/insight-kit.ts`
 * in-process, without the pi runtime, an LLM, or a real session.
 *
 * Why a fake and not pi's SDK: the extension's default export is just a factory
 * `(pi: ExtensionAPI) => void` that calls `pi.registerTool` and `pi.on`. Driving
 * it through `createAgentSession` + `runPrintMode` would need a real model (API
 * key) or a mock-model scaffold pi does not export, plus a full ResourceLoader.
 * The fake instead *captures* every `registerTool` definition and every `on`
 * handler, so a test can invoke a tool's `execute` or a hook handler directly
 * and assert on the result — the same pattern pi-subagents uses in
 * `test/support/mock-pi.ts` + its `index-child-registration.test.ts`.
 *
 * `pi.exec` is the one piece that talks to the outside world. The fake lets a
 * test either (a) stub it with a scripted `ExecResult` (deterministic, no
 * subprocess) or (b) leave it as a real `child_process` spawn so an end-to-end
 * test can drive a real `uv run` against a temp run dir.
 */
import { spawn } from "node:child_process";
import type {
	ExtensionAPI,
	ExtensionContext,
	ToolCallEvent,
	ToolCallEventResult,
	ToolDefinition,
	ToolResultEvent,
} from "@earendil-works/pi-coding-agent";

/**
 * pi's `tool_result` handler return type. pi does not export
 * `ToolResultEventResult` from the package root, so the shape is mirrored here.
 * The insight-kit `tool_result` hook is observe-only and returns nothing, so
 * only the optional patch fields matter for typing the captured handler.
 */
interface ToolResultEventResult {
	content?: unknown[];
	details?: unknown;
	isError?: boolean;
}

/** A single recorded `pi.exec` invocation — lets tests assert the argv shape. */
export interface RecordedExec {
	command: string;
	args: string[];
	options?: { signal?: AbortSignal; timeout?: number; cwd?: string };
}

/** What `pi.exec` resolves to. Mirrors pi's `ExecResult` structurally. */
export interface FakeExecResult {
	stdout: string;
	stderr: string;
	code: number;
	killed: boolean;
}

/** A scripted `pi.exec` implementation: receives the call, returns a result. */
export type ExecStub = (call: RecordedExec) => FakeExecResult | Promise<FakeExecResult>;

export interface FakeExtensionAPI {
	/** The object to pass to the extension's default export. */
	readonly pi: ExtensionAPI;
	/** Every tool registered via `pi.registerTool`, keyed by tool name. */
	readonly tools: Map<string, ToolDefinition>;
	/** Every `tool_call` handler registered via `pi.on("tool_call", ...)`. */
	readonly toolCallHandlers: Array<
		(event: ToolCallEvent, ctx: ExtensionContext) =>
			| ToolCallEventResult
			| undefined
			| void
			| Promise<ToolCallEventResult | undefined | void>
	>;
	/** Every `tool_result` handler registered via `pi.on("tool_result", ...)`. */
	readonly toolResultHandlers: Array<
		(event: ToolResultEvent, ctx: ExtensionContext) =>
			| ToolResultEventResult
			| undefined
			| void
			| Promise<ToolResultEventResult | undefined | void>
	>;
	/** Ordered log of every `pi.exec` call the extension made. */
	readonly execCalls: RecordedExec[];
	/** Install a scripted `pi.exec`. When unset, `pi.exec` spawns for real. */
	setExecStub(stub: ExecStub): void;
}

/** Real `pi.exec`: spawn a subprocess, collect stdout/stderr, mirror pi's shape. */
function realExec(call: RecordedExec): Promise<FakeExecResult> {
	return new Promise((resolve, reject) => {
		const child = spawn(call.command, call.args, {
			cwd: call.options?.cwd,
			stdio: ["ignore", "pipe", "pipe"],
		});
		let stdout = "";
		let stderr = "";
		let killed = false;
		child.stdout.on("data", (c) => {
			stdout += c.toString();
		});
		child.stderr.on("data", (c) => {
			stderr += c.toString();
		});
		const timer = call.options?.timeout
			? setTimeout(() => {
					killed = true;
					child.kill("SIGTERM");
				}, call.options.timeout)
			: undefined;
		const onAbort = () => {
			killed = true;
			child.kill("SIGTERM");
		};
		call.options?.signal?.addEventListener("abort", onAbort);
		child.on("error", (err) => {
			if (timer) clearTimeout(timer);
			call.options?.signal?.removeEventListener("abort", onAbort);
			reject(err);
		});
		child.on("close", (code) => {
			if (timer) clearTimeout(timer);
			call.options?.signal?.removeEventListener("abort", onAbort);
			resolve({ stdout, stderr, code: code ?? -1, killed });
		});
	});
}

/**
 * Build a fake `ExtensionAPI`. Unknown methods are no-ops (the insight-kit
 * extension only touches `on`, `registerTool` and `exec`) so the surface stays
 * minimal yet the cast to `ExtensionAPI` is honest about what is exercised.
 */
export function createFakeExtensionAPI(): FakeExtensionAPI {
	const tools = new Map<string, ToolDefinition>();
	const toolCallHandlers: FakeExtensionAPI["toolCallHandlers"] = [];
	const toolResultHandlers: FakeExtensionAPI["toolResultHandlers"] = [];
	const execCalls: RecordedExec[] = [];
	let execStub: ExecStub | undefined;

	const api = {
		on(event: string, handler: unknown): void {
			if (event === "tool_call") {
				toolCallHandlers.push(
					handler as FakeExtensionAPI["toolCallHandlers"][number],
				);
			} else if (event === "tool_result") {
				toolResultHandlers.push(
					handler as FakeExtensionAPI["toolResultHandlers"][number],
				);
			}
			// other lifecycle events: the insight-kit extension registers none.
		},
		registerTool(tool: ToolDefinition): void {
			if (tools.has(tool.name)) {
				throw new Error(`fake pi: tool '${tool.name}' registered twice`);
			}
			tools.set(tool.name, tool);
		},
		async exec(
			command: string,
			args: string[],
			options?: RecordedExec["options"],
		): Promise<FakeExecResult> {
			const call: RecordedExec = { command, args, options };
			execCalls.push(call);
			if (execStub) return await execStub(call);
			return await realExec(call);
		},
	};

	return {
		// The extension only uses `on` / `registerTool` / `exec`; the Proxy makes
		// any other access a harmless no-op so the cast is safe at runtime.
		pi: new Proxy(api, {
			get(target, prop) {
				if (prop in target) return target[prop as keyof typeof target];
				return () => undefined;
			},
		}) as unknown as ExtensionAPI,
		tools,
		toolCallHandlers,
		toolResultHandlers,
		execCalls,
		setExecStub(stub: ExecStub): void {
			execStub = stub;
		},
	};
}

/**
 * A minimal `ExtensionContext` stub. The insight-kit tool `execute` never reads
 * `ctx` (it captures `pi` from the factory closure), and the hooks read only
 * `event` — so an empty-ish ctx is sufficient. Unknown access is a no-op.
 */
export function createFakeContext(cwd = process.cwd()): ExtensionContext {
	const ctx = {
		cwd,
		hasUI: false,
		signal: undefined,
		ui: new Proxy({}, { get: () => () => undefined }),
		isIdle: () => true,
		hasPendingMessages: () => false,
	};
	return new Proxy(ctx, {
		get(target, prop) {
			if (prop in target) return target[prop as keyof typeof target];
			return () => undefined;
		},
	}) as unknown as ExtensionContext;
}

/** Build a `tool_call` event for `toolName` with the given LLM-supplied input. */
export function toolCallEvent(
	toolName: string,
	input: Record<string, unknown>,
	toolCallId = "test-call",
): ToolCallEvent {
	return { type: "tool_call", toolCallId, toolName, input } as ToolCallEvent;
}

/** Build a `tool_result` event for `toolName` (used to drive the tally hook). */
export function toolResultEvent(
	toolName: string,
	isError: boolean,
	toolCallId = "test-call",
): ToolResultEvent {
	return {
		type: "tool_result",
		toolCallId,
		toolName,
		input: {},
		content: [{ type: "text", text: "" }],
		isError,
		details: undefined,
	} as ToolResultEvent;
}
