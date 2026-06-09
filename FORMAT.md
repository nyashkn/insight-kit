# FORMAT — ck spec encoding

caveman. terse. fragments OK. drop articles/filler. code, paths, identifiers verbatim.

## SPEC.md sections

- §G — goal. 1-3 lines, what the thing does.
- §C — constraints. `Cn`, stated or implied limits.
- §I — interfaces. `I.name`, external surfaces — APIs, CLIs, files, env.
- §V — invariants. `Vn`, must-hold properties. test-checkable.
- §T — tasks. pipe table, ordered, build units.
- §R — risks. `RTn`, known risks + resolved-by refs. (extension; optional)
- §B — bugs. pipe table, one row per bug hit.

## §T table

fenced block. cols: `id | st | desc | cites`
- `st` glyph — `.` todo · `~` wip · `x` done
- `cites` — comma list of §V / §C / §I deps. e.g. `V2,I.emit`
- `id` monotonic `T1..` — never reuse.

## §B table

fenced block. cols: `id | date | cause | fix`
- `id` monotonic `B1..` — never reuse. every bug gets a row.

## rules

- numbering monotonic across all sections. never reuse `Vn` / `Tn` / `Bn` / `RTn`.
- `/ck:spec` sole mutator of SPEC.md.
- `amend` touches only the named section — never silently rewrite others.
- preserve paths, code, identifiers verbatim — caveman compresses prose, not symbols.
- no auto-build after spec — `/ck:build` invoked explicitly.
