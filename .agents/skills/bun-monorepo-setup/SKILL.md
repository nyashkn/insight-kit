---
name: bun-monorepo-setup
type: skill
description: Set up or extend the Bun workspace monorepo for insight-kit viz layers, including biome.json lint config, bunfig.toml, bun.lock, and the M12-B playbook for adding a new viz layer package.
roles_using: [data-engineer, operator]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  bun: "1.3.x"
metadata:
  last_verified: 2026-04-29
---

## Purpose

The viz layer is a Bun workspace (`"workspaces": ["viz/*"]`). Adding a new renderer (e.g., a second Evidence-based dashboard, a React component library, a CLI tool) requires registering it as a workspace package, wiring it into the root `biome.json` lint scope, and ensuring `bun.lock` stays consistent. Doing this incorrectly produces silent type errors or packages that fail `bun run --filter '*' typecheck`.

## When to invoke

- When adding a new `viz/<layer>/` package (M12-B playbook).
- When `bun run lint` fails with a file path not covered by `biome.json`.
- When a new workspace package is not picked up by `bun run --filter '*' test`.
- When migrating from npm/pnpm to Bun on an existing viz package.
- When updating the Bun version specified in `packageManager`.

## Procedure

### 1. Verify the current workspace root

```bash
cd /path/to/insight-kit
cat package.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['workspaces'], d['packageManager'])"
# → ['viz/*'] bun@1.3.12
```

The root `package.json` is private (`"private": true`) and must not be published.

### 2. Create the new package directory

```bash
mkdir -p viz/<new-layer>
```

Replace `<new-layer>` with the package name, e.g., `viz/dashboard-ops`.

### 3. Write the package's `package.json`

```json
{
  "name": "@insight-kit/<new-layer>",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "test": "bun test",
    "build": "bun run build:main"
  },
  "dependencies": {},
  "devDependencies": {
    "typescript": "^5.7.0"
  }
}
```

### 4. Add a `tsconfig.json` inheriting from the workspace root

```json
{
  "extends": "../../tsconfig.json",
  "compilerOptions": {
    "rootDir": ".",
    "outDir": "dist"
  },
  "include": ["**/*.ts", "**/*.svelte"]
}
```

If there is no root `tsconfig.json`, create one at the repo root:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "skipLibCheck": true
  }
}
```

### 5. Confirm biome.json covers the new package

Check `/path/to/insight-kit/biome.json`:

```json
"files": {
  "include": [
    "viz/**/*.ts",
    "viz/**/*.svelte",
    "viz/**/*.js",
    "viz/**/*.mjs",
    "viz/**/*.json"
  ]
}
```

The glob `viz/**/*` already covers all sub-packages. No change needed unless you add a new file extension (e.g., `.jsx`).

To add `.jsx` coverage:

```json
"include": [
  "viz/**/*.ts",
  "viz/**/*.tsx",
  "viz/**/*.jsx",
  "viz/**/*.svelte",
  "viz/**/*.js",
  "viz/**/*.mjs",
  "viz/**/*.json"
]
```

### 6. Install and lock dependencies

```bash
bun install
```

This regenerates `bun.lock`. Commit both `package.json` changes and `bun.lock`:

```bash
git add viz/<new-layer>/package.json viz/<new-layer>/tsconfig.json bun.lock
```

### 7. Verify the new package is discovered

```bash
bun run --filter '*' typecheck
bun run --filter '@insight-kit/<new-layer>' typecheck
```

Both must exit 0.

### 8. Run the full lint suite

```bash
bun run lint
# → biome check .  (must exit 0)
```

### 9. (M12-B) Wiring a new Evidence-based viz layer

If the new layer is an Evidence project:

```bash
cd viz/<new-layer>
bunx degit evidence-dev/template .
bun install
```

Then add an Evidence-specific build script to the package `scripts`:

```json
"build:evidence": "evidence build",
"dev": "evidence dev"
```

The root workspace does not run Evidence-specific commands via `--filter` (Evidence dev server is not a test runner). Run Evidence commands directly inside `viz/<new-layer>/`.

Add the Evidence build output to `.gitignore`:

```
viz/<new-layer>/.evidence/
viz/<new-layer>/build/
```

## Acceptance criteria

- `bun run --filter '*' typecheck` exits 0 with the new package included.
- `bun run lint` exits 0 (biome covers new `.ts` files).
- `bun.lock` is up-to-date and committed.
- `bun run --filter '@insight-kit/<new-layer>' test` exits 0 (even if no tests yet — empty test suite passes).

## Common pitfalls

**`bun.lock` out of date:** After editing any `package.json`, always run `bun install` before committing. A stale `bun.lock` causes CI to fail with a lockfile mismatch error.

**`"type": "module"` missing:** Without `"type": "module"`, `.js` files are treated as CommonJS and `import` statements fail at runtime.

**biome formatter uses tabs, not spaces:** The project `biome.json` sets `"indentStyle": "tab"`. Do not override to spaces in a package-local biome config — this creates lint conflicts across the workspace.

**`extends` path in tsconfig wrong:** If `viz/<new-layer>/tsconfig.json` has `"extends": "../../tsconfig.json"` but the root has no `tsconfig.json`, `tsc` exits with a resolution error. Create the root config first.

**Evidence `.svelte-kit/` and `build/` in biome scope:** The `biome.json` `ignore` list excludes `**/.svelte-kit/**` and `**/build/**`. Do not remove these entries or biome will attempt to lint generated files and fail.

**`bun run --filter '*' test` fails on packages with no test files:** Add a placeholder: `touch viz/<new-layer>/index.test.ts`. Bun treats a directory with no test files as a pass, but some versions print warnings.

## Examples

### Check which packages are in the workspace

```bash
bun pm ls --filter '*' 2>/dev/null || bun workspaces list 2>/dev/null || cat package.json | python3 -c "import json,sys; [print(w) for w in json.load(sys.stdin)['workspaces']]"
```

### Add a shared utility package

```bash
mkdir -p viz/shared-utils
cat > viz/shared-utils/package.json <<'EOF'
{
  "name": "@insight-kit/shared-utils",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": { "typecheck": "tsc --noEmit", "test": "bun test" },
  "devDependencies": { "typescript": "^5.7.0" }
}
EOF
bun install
bun run --filter '@insight-kit/shared-utils' typecheck
```

## Related skills

- `preflight` — validate Evidence build after adding a new viz layer.
- `evidence-page-creation` — author pages inside the new Evidence package.
- `layer-a-validation` — Python-side validation is separate; this skill covers the JS/TS layer only.
