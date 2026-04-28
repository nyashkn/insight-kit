import { spawn, type ChildProcess } from 'node:child_process';
import { open, readFile } from 'node:fs/promises';

export interface DevServer {
  proc: ChildProcess;
  baseUrl: string;
  logPath: string;
  stop(): Promise<void>;
}

/**
 * Spawn `npx evidence dev --port <port> --strictPort` in reportsDir.
 * Polls the log file every 2 s for "ready" or "listening" substrings.
 * Mirrors the Python start_dev_server() logic.
 */
export async function startDevServer(opts: {
  reportsDir: string;
  port: number;
  env?: Record<string, string>;
  readyTimeoutMs?: number;
  logPath?: string;
}): Promise<DevServer> {
  const {
    reportsDir,
    port,
    env: extraEnv,
    readyTimeoutMs = 60_000,
    logPath = `/tmp/preflight_dev_${port}.log`,
  } = opts;

  // 1. Open log file for write
  const logFh = await open(logPath, 'w');

  // 2. Spawn the dev server — stdout + stderr both go to the log file
  const proc = spawn(
    'npx',
    ['evidence', 'dev', '--port', String(port), '--strictPort'],
    {
      cwd: reportsDir,
      env: { ...process.env, ...extraEnv },
      stdio: ['ignore', logFh.fd, logFh.fd],
      detached: true,
    },
  );

  await logFh.close();

  // 3. Poll log file every 2 s for ready signals
  const deadline = Date.now() + readyTimeoutMs;

  await new Promise<void>((resolve, reject) => {
    let settled = false;

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearInterval(interval);
      fn();
    };

    const interval = setInterval(async () => {
      // Check if process already exited
      if (proc.exitCode !== null) {
        // Read last 30 lines from log for diagnostics
        let tail = '';
        try {
          const content = await readFile(logPath, 'utf8');
          tail = content.split('\n').slice(-30).join('\n');
        } catch {
          // ignore read error
        }
        settle(() => reject(new Error(`Dev server exited early (code ${proc.exitCode}). Last log:\n${tail}`)));
        return;
      }

      if (Date.now() > deadline) {
        settle(() => resolve()); // timed out but proc is still running — continue anyway (mirrors Python)
        return;
      }

      try {
        const content = await readFile(logPath, 'utf8');
        const lower = content.toLowerCase();
        if (lower.includes('ready') || lower.includes('listening')) {
          settle(() => resolve());
        }
      } catch {
        // log not yet flushed — ignore
      }
    }, 2_000);

    // Also resolve on proc error (e.g. ENOENT for npx)
    proc.on('error', (err) => {
      settle(() => reject(err));
    });
  });

  const baseUrl = `http://localhost:${port}`;

  return {
    proc,
    baseUrl,
    logPath,
    async stop() {
      if (proc.exitCode === null) {
        try {
          // Kill the entire process group (matches Python os.killpg pattern)
          process.kill(-(proc.pid!), 'SIGTERM');
        } catch {
          proc.kill('SIGTERM');
        }
        await new Promise<void>((resolve) => {
          const t = setTimeout(() => { proc.kill('SIGKILL'); resolve(); }, 10_000);
          proc.on('close', () => { clearTimeout(t); resolve(); });
        });
      }
    },
  };
}
