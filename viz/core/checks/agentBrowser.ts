import { spawn } from 'node:child_process';

export interface AbResult {
  code: number;
  output: string;
}

/**
 * Run `agent-browser --session <session> <args...>` and return exit code + combined stdout/stderr.
 * On ENOENT (binary missing) returns { code: 127, output: 'agent-browser not found in PATH' }.
 */
export async function ab(
  session: string,
  args: string[],
  opts?: { timeoutMs?: number; stdin?: string; binPath?: string },
): Promise<AbResult> {
  const bin = opts?.binPath ?? 'agent-browser';
  const timeoutMs = opts?.timeoutMs ?? 30_000;

  return new Promise<AbResult>((resolve) => {
    let child;
    try {
      child = spawn(bin, ['--session', session, ...args], {
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (err: unknown) {
      const e = err as NodeJS.ErrnoException;
      if (e.code === 'ENOENT') {
        resolve({ code: 127, output: 'agent-browser not found in PATH' });
      } else {
        resolve({ code: 1, output: String(e.message ?? err) });
      }
      return;
    }

    let output = '';
    child.stdout?.on('data', (chunk: Buffer) => { output += chunk.toString(); });
    child.stderr?.on('data', (chunk: Buffer) => { output += chunk.toString(); });

    // Write stdin if provided
    if (opts?.stdin != null) {
      child.stdin?.write(opts.stdin);
      child.stdin?.end();
    } else {
      child.stdin?.end();
    }

    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
    }, timeoutMs);

    child.on('error', (err: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      if (err.code === 'ENOENT') {
        resolve({ code: 127, output: 'agent-browser not found in PATH' });
      } else {
        resolve({ code: 1, output: String(err.message) });
      }
    });

    child.on('close', (code: number | null) => {
      clearTimeout(timer);
      if (timedOut) {
        resolve({ code: 1, output: output + `\nagent-browser timeout after ${timeoutMs}ms` });
      } else {
        resolve({ code: code ?? 1, output });
      }
    });
  });
}

/** Verify agent-browser exists at the given path (or PATH if unspecified). */
export async function checkAgentBrowserAvailable(binPath?: string): Promise<boolean> {
  const result = await ab('__probe__', ['--version'], {
    binPath,
    timeoutMs: 5_000,
  });
  // code 127 means ENOENT; any other code means it ran (even if --version fails, binary exists)
  return result.code !== 127;
}
