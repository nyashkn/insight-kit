// Generator CLI modules — exported as namespaces for direct consumers
// Note: build_provenance and build_indexes are CLI-only scripts with no named exports
// Re-export as modules for documentation; direct invocation via bun CLI
export * as buildProvenance from '@insight-kit/viz-evidence/generators/build_provenance.ts';
export * as buildIndexes from '@insight-kit/viz-evidence/generators/build_indexes.ts';
