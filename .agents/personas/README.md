# personas/

Reusable persona templates for consistent behavioral framing across delegated agents. Each `<persona>.md` defines communication style, expertise domain, constraints, and tool preferences.

Naming: `<descriptor>.md` (e.g., `senior-data-engineer.md`, `evidence-author.md`, `compliance-reviewer.md`).

## Purpose

Personas provide lightweight instruction sets for shaping how agents approach tasks. They ensure consistency when spinning up specialized roles and reduce boilerplate in individual AGENT.md profiles.

## Example structure

```
personas/
├── senior-data-engineer.md    # SQL/DuckDB expertise + optimization focus
├── evidence-author.md         # Claim authoring + provenance rigor
└── compliance-reviewer.md      # Risk/security audit perspective
```

Each persona includes: expertise areas, preferred tools, communication tone, and key constraints.
