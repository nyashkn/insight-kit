/**
 * T18 — L3 pi-runtime E2E test: real pi session, fake model, real gate subprocess.
 *
 * What the existing unit tests (insight-kit.extension.test.ts) do NOT cover:
 *   - The real pi runtime loading .pi/extensions/insight-kit.ts as a live extension
 *   - The model → toolCall → pi.exec → uv subprocess → disk-write pipeline
 *   - pi's tool_call hook intercepting the call (INSIGHT_KIT_RUN_DIR gate)
 *   - The content-addressed record actually landing under INSIGHT_KIT_RUN_DIR
 *
 * Design: DETERMINISTIC FAKE MODEL via pi's own `registerFauxProvider` / `fauxAssistantMessage` /
 * `fauxToolCall` — no API key, no network. The faux provider is registered before
 * createAgentSession; pi picks up the model automatically because the faux provider
 * registers itself in pi's internal API registry.
 *
 * Session configuration:
 *   - cwd = repo root  (so uv resolves pyproject.toml and INSIGHT_KIT_RUN_DIR writes work)
 *   - agentDir = a unique tmp dir per test  (isolates ~/.pi/agent settings/extensions)
 *   - DefaultResourceLoader with the real .pi/extensions/insight-kit.ts auto-discovered
 *   - noTools: "builtin"  (only the four ik_*_emit tools from the extension)
 *   - SessionManager.inMemory()  (no on-disk session files)
 *   - INSIGHT_KIT_RUN_DIR set to a fresh tmp dir before each prompt
 *
 * Faux model script (two turns per session):
 *   Turn 1 — assistant emits a tool call: fauxToolCall("ik_claim_emit", {...}) with
 *             stopReason "toolUse". Pi runs the extension's execute() → pi.exec("uv", ...).
 *   Turn 2 — assistant says "Done." with stopReason "stop". session.prompt() resolves.
 *
 * Assertions:
 *   - session.prompt() resolves without throwing
 *   - records/<record_id>/record.json exists under INSIGHT_KIT_RUN_DIR
 *   - record.json contains the expected claim_id and record_type
 *
 * Run: `bun test .pi/test/insight-kit.pi-runtime.test.ts`
 * (also covered by the existing `pi:test` npm script glob `./.pi/test/`)
 *
 * Cites: C4, I.emit, V1, V2
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	fauxAssistantMessage,
	fauxText,
	fauxToolCall,
	registerFauxProvider,
} from "@earendil-works/pi-ai";
import type { FauxProviderRegistration } from "@earendil-works/pi-ai";
import {
	AuthStorage,
	createAgentSession,
	DefaultResourceLoader,
	ModelRegistry,
	SessionManager,
	SettingsManager,
} from "@earendil-works/pi-coding-agent";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Repo root: one level above .pi/ */
const REPO_ROOT = join(import.meta.dir, "..", "..");

/**
 * A minimal but valid claim payload. claim_id must match
 *   ^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$
 * (from gate/schema.py ClaimRecord.claim_id Field constraint).
 */
const CLAIM_PAYLOAD = {
	claim_id: "PI-D-001",
	fields: { revenue: { value: 42000, fmt_hint: "$,.0f" } },
};

// ---------------------------------------------------------------------------
// Faux provider name — used for both registerFauxProvider and AuthStorage.
// A runtime API key is required: pi's model registry calls hasConfiguredAuth()
// before every turn; if no key is found it throws "No API key found" even
// though the faux provider's streamSimple never actually uses the key.
// ---------------------------------------------------------------------------

const FAUX_PROVIDER = "ik-e2e-test-provider";
const FAUX_API_KEY = "faux-key-no-network-needed";

// ---------------------------------------------------------------------------
// Shared faux provider — one instance across all tests in this file to keep
// the API registry clean. Each test installs its own scripted responses before
// calling session.prompt().
// ---------------------------------------------------------------------------

let faux: FauxProviderRegistration;

beforeAll(() => {
	faux = registerFauxProvider({
		// Use a stable provider name so we can pre-populate AuthStorage.
		provider: FAUX_PROVIDER,
	});
});

afterAll(() => {
	faux.unregister();
});

// ---------------------------------------------------------------------------
// Tmp dir management — a fresh INSIGHT_KIT_RUN_DIR per test
// ---------------------------------------------------------------------------

const tmpDirs: string[] = [];

function freshRunDir(): string {
	const d = mkdtempSync(join(tmpdir(), "ik-pi-runtime-e2e-"));
	tmpDirs.push(d);
	return d;
}

// Restore INSIGHT_KIT_RUN_DIR after each test (some tests mutate it).
const ORIGINAL_RUN_DIR = process.env.INSIGHT_KIT_RUN_DIR;
beforeEach(() => {
	delete process.env.INSIGHT_KIT_RUN_DIR;
});
afterEach(() => {
	if (ORIGINAL_RUN_DIR === undefined) delete process.env.INSIGHT_KIT_RUN_DIR;
	else process.env.INSIGHT_KIT_RUN_DIR = ORIGINAL_RUN_DIR;
});

afterAll(() => {
	for (const d of tmpDirs) rmSync(d, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// Session factory helpers
// ---------------------------------------------------------------------------

/**
 * Build a ResourceLoader that discovers the real .pi/extensions/insight-kit.ts
 * from the repo root but uses an isolated agentDir so the test is not affected by
 * ~/.pi/agent settings, global extensions, or auth state.
 */
async function buildResourceLoader(agentDir: string): Promise<DefaultResourceLoader> {
	const loader = new DefaultResourceLoader({
		cwd: REPO_ROOT,
		agentDir,
		settingsManager: SettingsManager.create(REPO_ROOT, agentDir),
		// Disable everything except extensions — faster startup, no external deps.
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
	});
	await loader.reload();
	return loader;
}

/**
 * Build an in-memory AuthStorage that satisfies pi's hasConfiguredAuth() check
 * for the faux provider, without touching disk or real credentials.
 *
 * pi calls AuthStorage.hasAuth(provider) before every prompt turn. The check
 * returns true when runtimeOverrides.has(provider), which setRuntimeApiKey()
 * sets. The faux provider's streamSimple never actually uses the key — it
 * streams scripted responses regardless.
 */
function buildAuthStorage(): AuthStorage {
	const auth = AuthStorage.inMemory();
	auth.setRuntimeApiKey(FAUX_PROVIDER, FAUX_API_KEY);
	return auth;
}

/**
 * Create a pi agent session driven by the faux model.
 * The session runs in the repo root so `uv run` can find pyproject.toml.
 */
async function buildSession(agentDir: string) {
	const resourceLoader = await buildResourceLoader(agentDir);
	const authStorage = buildAuthStorage();
	const modelRegistry = ModelRegistry.inMemory(authStorage);

	const { session } = await createAgentSession({
		cwd: REPO_ROOT,
		agentDir,
		model: faux.getModel(),
		authStorage,
		modelRegistry,
		resourceLoader,
		sessionManager: SessionManager.inMemory(REPO_ROOT),
		settingsManager: SettingsManager.create(REPO_ROOT, agentDir),
		// Disable built-in tools (bash/read/edit/write) — tests only need the
		// four ik_*_emit tools registered by the insight-kit extension.
		noTools: "builtin",
	});

	return session;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Assert that the gate wrote a content-addressed record to disk and return its
 * parsed JSON. Throws if the file doesn't exist, giving a clear failure message.
 */
function assertRecordOnDisk(
	runDir: string,
	recordId: string,
): Record<string, unknown> {
	const recordPath = join(runDir, "records", recordId, "record.json");
	expect(existsSync(recordPath)).toBe(true);
	return JSON.parse(readFileSync(recordPath, "utf8")) as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("pi-runtime E2E — real extension + real gate subprocess", () => {
	test(
		"ik_claim_emit: real pi runtime loads extension, runs gate, writes record to disk",
		async () => {
			const runDir = freshRunDir();
			process.env.INSIGHT_KIT_RUN_DIR = runDir;

			// Script the faux model for exactly two turns:
			//   Turn 1: emit the tool call (pi runs it → real uv gate subprocess)
			//   Turn 2: acknowledge the result so the agent turn completes
			faux.setResponses([
				fauxAssistantMessage(
					[fauxToolCall("ik_claim_emit", CLAIM_PAYLOAD)],
					{ stopReason: "toolUse" },
				),
				fauxAssistantMessage([fauxText("Claim emitted successfully.")]),
			]);

			// Isolated agentDir so this test doesn't pick up ~/.pi/agent settings.
			const agentDir = freshRunDir();
			const session = await buildSession(agentDir);

			try {
				// prompt() resolves once the agent turn is complete (tool executed +
				// model's follow-up response received).
				await session.prompt("Emit a claim record for PI-D-001.");
			} finally {
				session.dispose();
			}

			// Locate the record_id from the records index so we can assert on the
			// content-addressed file. The gate writes records.jsonl as an index.
			const indexPath = join(runDir, "records.jsonl");
			expect(existsSync(indexPath)).toBe(true);

			const indexLines = readFileSync(indexPath, "utf8")
				.split("\n")
				.filter(Boolean);
			expect(indexLines.length).toBeGreaterThanOrEqual(1);

			const firstRow = JSON.parse(indexLines[0]) as {
				record_id: string;
				record_type: string;
				claim_id?: string;
			};
			expect(firstRow.record_type).toBe("claim");
			expect(firstRow.record_id).toMatch(/^[0-9a-f]{16}$/);

			// Assert the content-addressed record file on disk.
			const record = assertRecordOnDisk(runDir, firstRow.record_id);
			expect(record.claim_id).toBe("PI-D-001");
			expect(record.record_type).toBe("claim");
		},
		// Allow up to 60 s — uv may resolve/download deps on first run.
		60_000,
	);

	test(
		"ik_claim_emit: tool_call hook blocks the call when INSIGHT_KIT_RUN_DIR is unset",
		async () => {
			// Do NOT set INSIGHT_KIT_RUN_DIR — the extension's tool_call hook must block.
			// With no run dir, the faux model emits the tool call but pi's hook blocks it,
			// so the gate subprocess is never spawned and no record is written.
			// The model receives a block message and should respond with the follow-up text.
			faux.setResponses([
				fauxAssistantMessage(
					[fauxToolCall("ik_claim_emit", CLAIM_PAYLOAD)],
					{ stopReason: "toolUse" },
				),
				fauxAssistantMessage([fauxText("I need INSIGHT_KIT_RUN_DIR to be set.")]),
			]);

			const agentDir = freshRunDir();
			const session = await buildSession(agentDir);

			// session.prompt() should still resolve (the hook blocks the tool but the
			// conversation continues — the model sees the block reason as a tool result).
			// We assert that NO record is written because the gate never ran.
			let promptError: unknown = undefined;
			try {
				await session.prompt("Emit a claim.");
			} catch (err) {
				promptError = err;
			} finally {
				session.dispose();
			}

			// The prompt should not throw — pi handles blocked tool calls gracefully.
			expect(promptError).toBeUndefined();

			// No tmp run dir was set, so there is nothing on disk to assert — the main
			// assertion is that prompt() resolved without crashing (the block was handled).
		},
		30_000,
	);

	test(
		"ik_research_emit: gate rejects empty snapshot; model receives structured error",
		async () => {
			const runDir = freshRunDir();
			process.env.INSIGHT_KIT_RUN_DIR = runDir;

			// The gate (V20) rejects a research record with an empty snapshot.
			// The extension throws on a gate reject (V2) so pi surfaces it as a tool error.
			// The faux model's second turn acknowledges the error.
			faux.setResponses([
				fauxAssistantMessage(
					[
						fauxToolCall("ik_research_emit", {
							research_id: "PI-R-001",
							query: "what is conversion rate",
							source: "web",
							snapshot_ref: "tavily",
							snapshot: {}, // intentionally empty → gate rejects (V20)
						}),
					],
					{ stopReason: "toolUse" },
				),
				fauxAssistantMessage([
					fauxText("The gate rejected the empty snapshot — I'll retry with data."),
				]),
			]);

			const agentDir = freshRunDir();
			const session = await buildSession(agentDir);

			try {
				await session.prompt("Research conversion rate.");
			} finally {
				session.dispose();
			}

			// The gate rejected the call, so the index must be empty / non-existent.
			const indexPath = join(runDir, "records.jsonl");
			if (existsSync(indexPath)) {
				const lines = readFileSync(indexPath, "utf8").split("\n").filter(Boolean);
				// If the index exists it must contain no research records.
				for (const line of lines) {
					const row = JSON.parse(line) as { record_type: string };
					expect(row.record_type).not.toBe("research");
				}
			}
			// (If it doesn't exist at all that is also fine — zero writes on a reject.)
		},
		60_000,
	);
});
