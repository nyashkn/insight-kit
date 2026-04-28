/**
 * M12-A Spike: @duckdb/node-api under Bun runtime
 *
 * Tests: import DuckDBInstance via createRequire (NAPI), create in-memory DB,
 * execute SELECT 1, verify result, close.
 */

import { createRequire } from 'node:module';
import * as path from 'node:path';

async function main() {
  try {
    console.log('Bun version:', Bun.version);

    // ---- Attempt to load @duckdb/node-api via createRequire ----
    // Use same pattern as viz/core/checks/sqlBlocks.ts line ~30
    // Location: nairomarket/growth_insights/reports/node_modules/@duckdb/node-api
    const reportsDir = '/Users/njui/Documents/dev_work/naisiae_lema/nairomarket/growth_insights/reports';
    const modulePath = path.join(reportsDir, 'node_modules', '@duckdb', 'node-api');

    console.log(`Loading @duckdb/node-api from: ${modulePath}`);

    const req = createRequire(import.meta.url);
    const duckdb = req(modulePath) as {
      DuckDBInstance: {
        create: (path: string) => Promise<any>;
      };
    };

    console.log('✓ Successfully loaded @duckdb/node-api');

    // ---- Create in-memory DB ----
    console.log('Creating in-memory DuckDB instance...');
    const instance = await duckdb.DuckDBInstance.create(':memory:');
    console.log('✓ Instance created');

    // ---- Get connection ----
    const con = await (instance as any).connect();
    console.log('✓ Connection established');

    // ---- Execute SELECT 1 ----
    console.log('Executing SELECT 1...');
    const result = await con.runAndReadAll('SELECT 1 AS result');
    console.log('✓ Query executed');

    // ---- Verify result ----
    console.log('Result type:', typeof result);
    console.log('Result keys:', result ? Object.keys(result as object) : 'null');

    // Check the chunks structure
    const chunks = (result as any).chunks;
    if (chunks && chunks.length > 0) {
      console.log('Chunks[0] keys:', Object.keys(chunks[0]));
      console.log('Chunks[0]:', JSON.stringify(chunks[0], null, 2));
    }

    // Count rows from chunkSizeRuns
    const chunkSizeRuns = (result as any).chunkSizeRuns;
    const totalRows = chunkSizeRuns?.reduce((sum: number, run: any) => sum + (run.rowCount || 0), 0) ?? 0;

    if (totalRows > 0 && (result as any).done_) {
      console.log(`✓ Query returned ${totalRows} row(s) and completed`);
    } else {
      throw new Error(`Query returned no rows or did not complete. totalRows=${totalRows}, done=${(result as any).done_}`);
    }

    // ---- Close ----
    con.disconnectSync();
    console.log('✓ Connection closed');

    console.log('\n✓✓✓ PASS ✓✓✓');
    process.exit(0);
  } catch (err) {
    console.error('\n✗✗✗ FAIL ✗✗✗');
    console.error('Error:', err instanceof Error ? err.message : String(err));
    console.error('Stack:', err instanceof Error ? err.stack : '');
    process.exit(1);
  }
}

main();
