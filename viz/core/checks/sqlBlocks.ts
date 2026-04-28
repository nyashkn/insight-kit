/**
 * L1 — SQL Block Validation
 *
 * Walks pagesDir/**\/*.md, extracts fenced ```sql <name>` blocks, and executes
 * each against an in-memory DuckDB session. Mirrors Python layer1() and
 * load_source_views() in growth_insights/scripts/preflight_check.py.
 */

import type { Finding, CheckContext } from '@insight-kit/viz-core/types';
import { createRequire } from 'node:module';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

// Mirror Python SQL_FENCE_RE (re.DOTALL flag = [\s\S] in JS)
const SQL_FENCE_RE = /```sql\s+(\w+)\s*\n([\s\S]*?)```/g;
// Skip blocks with Evidence template expressions: ${varname}
const EVIDENCE_EXPR_RE = /\$\{[^}]+\}/;

/**
 * Recursively walk a directory and return all file paths matching the given
 * extension. Uses fs.readdir with recursive:true (Node 18.17+).
 */
async function walkFiles(dir: string, ext: string): Promise<string[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(dir, { recursive: true }) as string[];
  } catch {
    return [];
  }
  return entries
    .filter(e => e.endsWith(ext))
    .map(e => path.join(dir, e));
}

/**
 * Return the 1-based line number at a character offset within content.
 * Mirrors Python: content[:start_char].count("\n") + 1
 */
function lineAt(content: string, offset: number): number {
  return content.slice(0, offset).split('\n').length;
}

export async function checkSqlBlocks(ctx: CheckContext): Promise<Finding[]> {
  const findings: Finding[] = [];

  // ---- Load DuckDB via createRequire from caller-supplied path ----
  const modulePath =
    ctx.duckdbModulePath ??
    path.join(ctx.reportsDir, 'node_modules', '@duckdb', 'node-api');

  let duckdb: { DuckDBInstance: { create: (path: string) => Promise<unknown> } };
  try {
    const req = createRequire(import.meta.url);
    duckdb = req(modulePath) as typeof duckdb;
  } catch (err) {
    findings.push({
      layer: 1,
      rule: 'duckdb-load-failed',
      severity: 'error',
      hint: `Could not load @duckdb/node-api from ${modulePath}: ${String(err)}`,
    });
    return findings;
  }

  // ---- Build in-memory session ----
  // @duckdb/node-api v1 API: DuckDBInstance.create(':memory:')
  let instance: Awaited<ReturnType<typeof duckdb.DuckDBInstance.create>>;
  try {
    instance = await duckdb.DuckDBInstance.create(':memory:');
  } catch (err) {
    findings.push({
      layer: 1,
      rule: 'duckdb-connect-failed',
      severity: 'error',
      hint: String(err),
    });
    return findings;
  }

  // We need the raw connection for execute calls
  // @duckdb/node-api exposes instance.connect() -> connection
  const con = await (instance as unknown as { connect: () => Promise<{
    run: (sql: string) => Promise<unknown>;
    runAndReadAll: (sql: string) => Promise<unknown>;
    disconnectSync: () => void;
  }> }).connect();

  async function exec(sql: string): Promise<void> {
    await con.runAndReadAll(sql);
  }

  // ---- ATTACH persistent duckdb (read-only) if it exists ----
  if (ctx.duckdbPath) {
    try {
      await fs.access(ctx.duckdbPath);
      await exec(`ATTACH '${ctx.duckdbPath}' AS nairomarket_db (READ_ONLY)`);
      await exec(`CREATE SCHEMA IF NOT EXISTS nairomarket`);
      // Mirror views from attached db into nairomarket schema
      const viewsResult = await con.runAndReadAll(
        `SELECT table_name FROM information_schema.tables ` +
        `WHERE table_catalog = 'nairomarket_db' AND table_type = 'VIEW'`
      ) as { toRows: () => Array<Record<string, string>> };
      const rows = viewsResult.toRows();
      for (const row of rows) {
        const vname = row['table_name'];
        try {
          await exec(
            `CREATE OR REPLACE VIEW nairomarket.${vname} AS ` +
            `SELECT * FROM nairomarket_db.${vname}`
          );
        } catch {
          // Non-fatal — view may already exist or have conflicts
        }
      }
    } catch {
      // DuckDB file not found or attach failed — non-fatal warning
    }
  }

  // ---- Register source SQL views (mirrors load_source_views) ----
  // Collect names already exposed to avoid infinite-recursion
  let attachedViewNames = new Set<string>();
  try {
    const namesResult = await con.runAndReadAll(
      `SELECT table_name FROM information_schema.tables ` +
      `WHERE table_schema = 'nairomarket' AND table_type = 'VIEW'`
    ) as { toRows: () => Array<Record<string, string>> };
    attachedViewNames = new Set(namesResult.toRows().map(r => r['table_name']));
  } catch {
    // ignore
  }

  // Walk sources dir for *.sql files
  const sourcesDir = ctx.sourcesDir;
  const sqlFiles = await walkFiles(sourcesDir, '.sql');
  for (const sqlFile of sqlFiles.sort()) {
    const rawName = path.basename(sqlFile, '.sql');
    if (attachedViewNames.has(rawName)) continue;
    const viewName = `nairomarket.${rawName}`;
    try {
      let src = await fs.readFile(sqlFile, 'utf8');
      src = src.replace(/\$\{PROJECT_ROOT\}/g, ctx.projectRoot);
      try {
        await exec(`CREATE SCHEMA IF NOT EXISTS nairomarket`);
      } catch {
        // already exists
      }
      await exec(`CREATE OR REPLACE VIEW ${viewName} AS ${src}`);
    } catch {
      // Source view failures are non-fatal
    }
  }

  // ---- Walk pages and validate SQL blocks ----
  const pagesFilter = ctx.pagesFilter;
  let mdFiles = await walkFiles(ctx.pagesDir, '.md');
  mdFiles.sort();

  if (pagesFilter && pagesFilter.length > 0) {
    mdFiles = mdFiles.filter(f => pagesFilter.some(pf => f.includes(pf)));
  }

  for (const mdPath of mdFiles) {
    const relPath = path.relative(ctx.projectRoot, mdPath);
    let content: string;
    try {
      content = await fs.readFile(mdPath, 'utf8');
    } catch {
      continue;
    }

    SQL_FENCE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SQL_FENCE_RE.exec(content)) !== null) {
      const blockName = match[1];
      const sqlBody = match[2];
      const startChar = match.index;
      const lineNo = lineAt(content, startChar);

      // Skip Evidence template syntax
      if (EVIDENCE_EXPR_RE.test(sqlBody)) continue;
      if (!sqlBody.trim()) continue;

      try {
        await exec(sqlBody);
      } catch (err) {
        const errMsg = String(err).split('\n')[0];
        findings.push({
          layer: 1,
          rule: 'sql-block-syntax',
          severity: 'error',
          file: relPath,
          line: lineNo,
          snippet: `\`${blockName}\``,
          hint: errMsg,
        });
      }
    }
  }

  con.disconnectSync();
  return findings;
}
