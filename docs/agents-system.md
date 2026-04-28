# Agents System

This document describes the insight-kit agents framework: a structured system for organizing multi-role work across evidence-driven analytics projects.

## Overview

The agents system defines three orthogonal dimensions:

1. **Roles** (7 canonical) — work phases and outputs. MECE: each role produces a specific tier of work (ETL, Derive, External, Challenge, Render, Eval, Ops).
2. **Personas** (composable) — domain expertise layered onto roles. Example: analyst + funnel-persona = funnel-analyst.
3. **Council** (18 members) — reasoning lenses for escalation and deliberation. Never produce claims directly; invoked by role agents for specific decisions.

**Modes** (human/worker/spike) are sub-flags passed to roles, not separate agents. They control execution style and output expectations.

---

## Roles — Canonical 7

Each role is tied to a work phase and produces specific output tiers. Roles are MECE (mutually exclusive, collectively exhaustive) within a project workflow.

| Role | Phase | Tier | Output | Modes |
|------|-------|------|--------|-------|
| **data-engineer** | Ingest/transform | ETL_R, ETL_M, ETL_C | DuckDB views, SQL blocks, schema defs | human, worker, spike |
| **analyst** | Derive descriptive | D | Claims + metrics, narrative evidence | composes with persona |
| **researcher** | External evidence | X (with caveats) | Third-party citations, fact checks | — |
| **critic** | Challenge + re-run | C + edges | Sensitivity reports, failure modes | per-run, sensitivity |
| **renderer** | Evidence pages | I, V | Markdown + components | — |
| **evaluator** | Regression + golden-set | eval-report | Accuracy metrics, golden-set validation | — |
| **operator** | Kit ops + lifecycle | — | Tier hygiene, goal state, deployments | annotation-pass, goal-mgmt |

**Output tiers:**
- **ETL_R**: raw data layer (views, imports)
- **ETL_M**: modeled layer (derived columns, aggregates)
- **ETL_C**: claim-ready layer (validated, schema-locked)
- **D**: descriptive claims (analytical insights)
- **X**: external claims (third-party or user-provided)
- **C**: critical claims (from challenge phase)
- **I**: interactive pages (Evidence markdown + components)
- **V**: visual presentations (charts, dashboards)
- **eval-report**: regression + accuracy metrics

---

## Personas — Composable Domain Expertise

Personas wrap roles with domain knowledge. A persona applies to a role (e.g., analyst) and modifies how that role approaches work.

**Pattern**: `<role> + <persona> = specialized_agent`

Example: `analyst + funnel-persona = funnel-analyst` (understands funnel metrics, conversion funnels, drop-off analysis)

### Starter Personas (6)

| Persona | Domains | Typical role pairing | Output focus |
|---------|---------|---------------------|---------------|
| funnel | Conversion, drop-off, AARRR | analyst, critic | Funnel steps, conversion rates, stage analysis |
| retention | Cohort, churn, LTV | analyst, critic | Retention curves, cohort retention, churn metrics |
| ad-spend | CAC, ROAS, attribution | analyst, critic | Channel spend, return ratios, bid optimization |
| catalog | Inventory, SKU, assortment | analyst | Product metrics, inventory health, popularity |
| acquisition | CAC, channel mix, growth | analyst, data-engineer | CAC curves, CAC payback, new cohort tracking |
| activation | Signup, onboarding, early engagement | analyst, researcher | Activation rates, feature adoption, day-1/7/30 metrics |

**Composing personas**: A project config lists personas; roles inherit them at runtime. Example:

```yaml
personas:
  - funnel
  - retention
  - ad-spend
```

An analyst invoked in this project gains domain knowledge across funnel analysis, retention mechanics, and ad-spend attribution.

---

## Council — 18 Escalation Lenses

The council is a set of reasoning personas invoked by role agents for deliberation on high-stakes decisions. Council members **never produce claims directly**; they are always invoked as consultants.

**Canonical 18 members:**

| Name | Lens | Use cases |
|------|------|-----------|
| ada | Systems & complexity | Dependency chains, edge-case interactions |
| aristotle | Logic & categorization | Schema design, MECE frameworks, entity modeling |
| aurelius | Wisdom & balance | Trade-offs, stakeholder alignment |
| feynman | First-principles thinking | Root-cause analysis, explaining mechanisms |
| kahneman | Behavioral & cognitive bias | Statistical fallacies, sampling issues, bias detection |
| karpathy | Neural patterns & learning | Feature importance, signal quality, ML fundamentals |
| lao-tzu | Systems & inversion | Non-obvious solutions, what not to do |
| machiavelli | Power & incentives | Gaming risk, stakeholder incentives, guardrails |
| meadows | Leverage & feedback loops | System dynamics, bottleneck identification |
| munger | Mental models & inversion | Multi-disciplinary thinking, inversion checks |
| musashi | Strategy & precision | Execution focus, timing, decisive action |
| rams | Simplicity & clarity | Signal-to-noise, communication clarity |
| socrates | Questioning & rigor | Assumptions, logical consistency, missing data |
| sun-tzu | Strategy & adversarial | Competitive context, defensive postures |
| sutskever | Deep learning & scaling | Model capacity, feature engineering, data patterns |
| taleb | Risk & antifragility | Tail risks, optionality, robustness |
| torvalds | Pragmatism & shipping | Shipping velocity, technical debt trade-offs |
| watts | Networks & emergence | System composition, unintended consequences |

**Invocation pattern:**
```
When a role agent encounters a decision point (e.g., "should we include outliers?"), 
it may escalate to the council:
  - Call council member (e.g., kahneman for bias checks)
  - Get structured feedback
  - Incorporate into role output or recommend alternative path
```

---

## Skills — 14 Total

Skills are reusable function bundles. Each skill is mapped to roles that use it. Skills can be local (project), global (user ~/.claude/skills/), or from domain bundles.

### Skill → Role Mapping

| Skill | Primary Roles | Type | Location |
|-------|---------------|------|----------|
| preflight | renderer, operator | validation | local |
| viz-evidence-authoring | renderer, analyst | component authoring | local |
| claim-authoring | analyst, critic | claim gen/review | local |
| ingest-flow | data-engineer | ETL pipeline | local |
| bun-monorepo-setup | operator, data-engineer | tooling | local |
| evidence-dev | analyst, renderer | Evidence.dev framework | global |
| evidence-dashboards | analyst, renderer | dashboard layouts | global |
| agent-browser | all roles | multi-tool orchestration | global |
| council | all roles (escalation) | reasoning lenses | global |
| create-skill | operator | skill creation | global |
| layer-a-validation | evaluator | test harness | local |
| eval-protocol | evaluator | golden-set validation | local |

**Operational Runbooks** (formerly skills, now docs):
- `docs/agents-bootstrap.md` — Bootstrap the insight-kit agent council from scratch
- `docs/goal-management.md` — Manage the .insight-kit/goals/ lifecycle

**Resolution order** (at runtime when role X needs skill Y):
1. `<repo>/.agents/skills/Y/` (local, highest priority)
2. `~/.claude/skills/Y/` (global user skills)
3. Domain bundle (from config)
4. Fail with suggestion: `ik agents add-skill Y`

---

## Config-Driven Mapping

All roles, personas, and skills are declared in `.agents/config.yaml`. Projects define which roles, personas, and skills they activate.

### Schema Overview

```yaml
version: 1                    # (immutable)
project: <slug>              # project identifier
roles: [role1, role2, ...]    # subset of canonical 7
personas: [persona1, ...]     # domain personas (optional)
skills:
  local: [skill1, ...]        # project-specific
  global: [skill1, ...]       # shared across projects
  domain_bundles: [...]       # optional domain collections
council:
  required: N                  # target council size
  source: <uri>               # council repo
  members: [ada, ...]         # canonical list (18 total allowed)
bootstrap:
  on_init: true|false         # run bootstrap on project init
  symlink_to_user: true|false # symlink skills to ~/.claude/skills/
  pull_missing_council: true  # fetch missing council members
  fail_on_missing_global: false  # warn-only or fail-hard on missing global skills
```

### Example Configs

#### insight-kit (meta-tool)

```yaml
version: 1
project: insight-kit
roles:
  - data-engineer    # infra/ETL
  - operator         # kit ops
personas: []         # no domain personas — generic
skills:
  local:
    - preflight
    - viz-evidence-authoring
    - claim-authoring
    - ingest-flow
    - bun-monorepo-setup
  global:
    - evidence-dev
    - evidence-dashboards
    - agent-browser
    - council
    - create-skill
  domain_bundles: []
council:
  required: 18
  source: https://github.com/0xNyk/council-of-high-intelligence
  members: [ada, aristotle, aurelius, feynman, kahneman, karpathy,
            lao-tzu, machiavelli, meadows, munger, musashi, rams,
            socrates, sun-tzu, sutskever, taleb, torvalds, watts]
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
```

#### Full Multi-Role Project (dockblocks-ops example)

```yaml
version: 1
project: dockblocks-ops
roles:
  - data-engineer
  - analyst
  - researcher
  - critic
  - renderer
  - evaluator
  - operator
personas:
  - funnel
  - retention
skills:
  local:
    - dockblocks-etl
    - funnel-claims
    - retention-metrics
  global:
    - evidence-dev
    - evidence-dashboards
    - agent-browser
    - council
    - create-skill
  domain_bundles:
    - analytics-bundle
council:
  required: 18
  source: https://github.com/0xNyk/council-of-high-intelligence
  members: [ada, aristotle, aurelius, feynman, kahneman, karpathy,
            lao-tzu, machiavelli, meadows, munger, musashi, rams,
            socrates, sun-tzu, sutskever, taleb, torvalds, watts]
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
```

---

## Bootstrap Flow

The bootstrap process initializes the agents system for a project. It ensures council members are present, skills are resolvable, and symlinks are created.

**Trigger**: `ik agents bootstrap` (or on project init if `bootstrap.on_init: true`)

### Bootstrap Sequence

```
┌─────────────────────────────────────────────────┐
│ 1. Read .agents/config.yaml                     │
│    (parse roles, personas, skills, council)     │
└───────────┬─────────────────────────────────────┘
            │
┌───────────v─────────────────────────────────────┐
│ 2. Validate config schema                       │
│    (reject if roles invalid, council > 30, etc) │
└───────────┬─────────────────────────────────────┘
            │
┌───────────v─────────────────────────────────────┐
│ 3. Resolve council members                      │
│    - if missing: pull from source (if enabled)  │
│    - if pull fails: warn or fail (per config)   │
└───────────┬─────────────────────────────────────┘
            │
┌───────────v─────────────────────────────────────┐
│ 4. Resolve skills                               │
│    - check local/, then ~/.claude/skills/       │
│    - if missing & !fail_on_missing: warn        │
│    - if missing & fail_on_missing: fail         │
└───────────┬─────────────────────────────────────┘
            │
┌───────────v─────────────────────────────────────┐
│ 5. Symlink skills to ~/.claude/skills/          │
│    (if symlink_to_user: true)                   │
│    - skip if already present (no overwrite)     │
└───────────┬─────────────────────────────────────┘
            │
┌───────────v─────────────────────────────────────┐
│ 6. Write marker file                            │
│    .agents/.bootstrap-complete (timestamp)      │
│    Report: N skills linked, M council present   │
└─────────────────────────────────────────────────┘
```

**Output**:
```
Bootstrap complete: 18/18 council members, 14/14 skills resolved
Symlinked 14 skills to ~/.claude/skills/
Council source: github.com/0xNyk/council-of-high-intelligence
```

---

## Modes — Execution Flags

Modes are sub-flags passed to roles to control execution style and output expectations. They modify how a role approaches work, not which role is selected.

| Mode | Meaning | Applies to | Example |
|------|---------|-----------|---------|
| **human** | Interactive, human-in-loop decision gates | analyst, critic, researcher | "analyst --mode human" — ask before publishing claims |
| **worker** | Autonomous, self-directed execution | data-engineer, renderer, operator | "data-engineer --mode worker" — build views without prompts |
| **spike** | Time-boxed exploration, loose output | all roles | "analyst --mode spike" — 30-min exploration, draft claims |

**Mode patterns**:
- `--mode human` implies checkpoints and decision gates (prefer for critic, researcher)
- `--mode worker` implies batch execution, minimal interaction (prefer for data-engineer, renderer)
- `--mode spike` implies time constraint and draft quality (experimental, ad-hoc)

---

## CLI Reference

All agent operations go through the `ik agents` command family.

### Commands

```bash
# Initialize project with bootstrap
ik agents bootstrap

# Validate config and report resolution
ik agents check

# Add a new role to config
ik agents add <role>

# Add a new persona to config
ik agents add-persona <persona-name> [--role <role>]

# Pull council members from source
ik agents pull-council [--member ada,aristotle,...]

# Symlink skills to user home
ik agents symlink-skills

# List active roles, personas, skills
ik agents ls

# Show skill resolution order
ik agents resolve-skill <skill-name>
```

### Examples

```bash
# Add analyst role to existing project
ik agents add analyst

# Add retention persona to analyst
ik agents add-persona retention --role analyst

# Pull all 18 council members
ik agents pull-council

# Check which project skill "preflight" resolves to
ik agents resolve-skill preflight
```

---

## Adding a New Role

Roles are fixed (canonical 7). If you believe a new role is needed, follow this checklist:

1. **Verify MECE**: Does it overlap with existing roles? (Roles must be mutually exclusive.)
2. **Define output tier**: What distinct output tier does it produce?
3. **Propose to team**: Roles are structural; add via community discussion.
4. **Update schema**: Patch `config.schema.json` enum for roles.
5. **Add CLI entry**: Extend `ik agents add` to recognize the new role.
6. **Document**: Add row to Roles table in this file.

---

## Adding a New Persona

Personas are composable. To add a new domain persona:

1. **Name the domain**: e.g., "churn-prevention", "acquisition-funnel"
2. **Identify typical roles**: Which roles (analyst, critic, data-engineer) work in this domain?
3. **Define key concepts**: List 3-5 core metrics or patterns (e.g., funnel → "drop-off rates", "conversion steps")
4. **Create persona file**: `.agents/personas/<name>.md` with:
   - Domain description
   - Key metrics/patterns
   - Typical questions
   - Related skills (if any)
5. **Add to config**: Include in `personas:` list
6. **Document**: Add row to Personas table above

**Example persona file** (`.agents/personas/churn-prevention.md`):
```markdown
# Churn Prevention Persona

## Domain
Customer retention and churn analysis. Focus: why do customers leave, and how to prevent it?

## Key metrics
- Churn rate (%, by cohort)
- Reasons for churn (NPS, survey)
- Win-back rates
- LTV impact

## Questions
- What cohorts are churning fastest?
- Is churn correlated with engagement drop?
- Do win-back campaigns work?

## Related skills
- churn-sql-views (DuckDB views for cohort analysis)
- nps-integration (integrating survey data)
```

---

## Adding a New Skill

Skills are self-contained function bundles. To create a new skill:

1. **Identify scope**: Single concern (e.g., "DuckDB view generation", "claim validation", "page rendering")
2. **Create directory**: `.agents/skills/<skill-name>/`
3. **Write SKILL.md**: Document:
   - Name and description
   - When to use (role + context)
   - Quick start (example invocation)
   - Layer reference (if multi-layer validation)
   - Interpreting findings
   - Common failures + fixes
   - Exit codes
   - Options/flags
4. **Add implementation**: Scripts, templates, or instruction sets
5. **Link to roles**: Update Skill → Role Mapping table
6. **Test**: Manual verification that the skill works
7. **Update config**: Add to `skills.local` or `skills.global`

**Example skill structure**:
```
.agents/skills/churn-cohort-sql/
├── SKILL.md                 # documentation (required)
├── templates/
│   ├── base-cohort-view.sql
│   └── churn-rate-calc.sql
├── validation/
│   └── churn-sanity-checks.py
└── examples/
    └── retail-churn-setup.sql
```

---

## Anti-Patterns

Common system-level mistakes to avoid:

### Anti-Pattern 1: Creating an agent for every domain
**Wrong**: "funnel-agent", "retention-agent", "ad-spend-agent"
**Right**: Single analyst role + compose with funnel/retention/ad-spend personas
**Why**: Reduces duplication; personas are lightweight, agents are heavy.

### Anti-Pattern 2: Making council members produce claims
**Wrong**: Invoking socrates to generate a fact claim
**Right**: Invoke socrates for questioning assumptions; role agent generates the claim
**Why**: Council members are lenses; claims come from role agents.

### Anti-Pattern 3: Bypassing config in favor of hardcoded paths
**Wrong**: Role script directly checks `~/.claude/skills/preflight/`
**Right**: Config → skill resolution → role receives resolved path
**Why**: Config is the single source of truth; enables portability and audit.

### Anti-Pattern 4: Stateful council membership
**Wrong**: Council members added/removed dynamically per-project
**Right**: Council is fixed (18 members, immutable list)
**Why**: Consistency; council is a shared resource across projects.

### Anti-Pattern 5: Skills as roles
**Wrong**: "create-skill-agent" or "build-etl-agent" as standalone roles
**Right**: Skills are tools invoked by roles (e.g., data-engineer uses ingest-flow skill)
**Why**: Separation of concerns; roles are phases, skills are tools.

---

## Migration Path — Adopting for Existing Projects

If you have an existing project with ad-hoc agent_runs/ or hardcoded agent scripts, adopt the system gradually:

### Phase 1: Assess Current State (Week 1)
1. List all current agent types (e.g., "SQL ETL agent", "claim reviewer")
2. Map each to a canonical role (data-engineer, analyst, critic, etc.)
3. Identify domain patterns (funnel? retention? ad-spend?)
4. Audit existing skills (one-off scripts vs. reusable patterns)

### Phase 2: Create Config (Week 1-2)
1. Create `.agents/config.yaml` with canonical roles from phase 1
2. Add personas for domain patterns identified
3. List existing skills in `skills.local`
4. Declare council membership

### Phase 3: Symlink Skills (Week 2)
1. Organize existing scripts into `.agents/skills/<name>/` subdirectories
2. Add `SKILL.md` to each (document when/how to use)
3. Run `ik agents bootstrap` to symlink
4. Test skill resolution: `ik agents resolve-skill <name>`

### Phase 4: Migrate Agent Runs (Week 3-4)
1. Convert ad-hoc agent invocations to role + mode (e.g., "analyst --mode human")
2. Replace hardcoded paths with skill references
3. Update CI/CD to call `ik agents bootstrap` before role invocations
4. Retire old agent_runs/ structure (keep as archive)

### Phase 5: Validate (Week 4)
1. Run full workflow end-to-end with config-driven roles
2. Verify council resolution
3. Spot-check skill paths
4. Document any custom extensions or deviations

**Checkpoints**:
- Day 3: config.yaml written and valid
- Day 7: skills reorganized and .agents/skills/ populated
- Day 14: one full workflow (ETL + analysis) working with new system
- Day 21: all legacy hardcoded paths replaced

---

## Quick Reference

**3-role starter config** (analyst + critic + data-engineer):
```yaml
version: 1
project: my-project
roles: [data-engineer, analyst, critic]
personas: [funnel]
skills:
  local: [ingest-flow, claim-authoring]
  global: [evidence-dev, council, agent-browser]
  domain_bundles: []
council: {required: 18, source: https://github.com/0xNyk/council-of-high-intelligence, members: [ada, ...]}
bootstrap: {on_init: true, symlink_to_user: true, pull_missing_council: true, fail_on_missing_global: false}
```

**Invoke a role with mode**:
```bash
ik analyst --mode human --persona funnel
ik critic --mode sensitivity  # re-run with sensitivity analysis
ik data-engineer --mode worker  # batch ETL
```

**Check system health**:
```bash
ik agents check
ik agents ls
ik agents resolve-skill preflight
```

---

## AGENT.md Frontmatter — `personas_compatible`

Each role's `AGENT.md` declares which personas it can be composed with via a `personas_compatible:` array in the YAML frontmatter. This is derived by inverting the `composes_with` field in each persona's `persona.md`.

**Location**: `.agents/agents/<role>/AGENT.md`

**Field placement**: immediately before `metadata:` in the frontmatter block.

**Example** (analyst role):

```yaml
---
name: analyst
role: analyst
description: Derive descriptive and predictive claims ...
phase: derive
tier_produces: [D]
modes: []
personas_compatible: [acquisition, activation, ad-spend, catalog, funnel, retention]
metadata:
  last_verified: 2026-04-29
---
```

**Inversion table** (as of 2026-04-29):

| Role | personas_compatible |
|------|---------------------|
| analyst | acquisition, activation, ad-spend, catalog, funnel, retention |
| critic | acquisition, activation, ad-spend, catalog, funnel, retention |
| researcher | acquisition, activation, ad-spend, catalog, funnel, retention |
| renderer | acquisition, ad-spend, catalog, retention |
| data-engineer | *(none)* |
| evaluator | *(none)* |
| operator | *(none)* |

The `personas_compatible` field is informational (not schema-validated). It ensures the persona axis is no longer orphaned from the role axis — consumers can look up which roles a persona applies to without re-reading every `persona.md`.

---

## Config — `default_role_for` Routing Block

`config.yaml` may declare an optional `default_role_for` block that maps work-phase keywords to a default role. This lets orchestrators and CLI tools route a task to the right role without requiring a user to name the role explicitly.

**Location**: `.agents/config.yaml` (top-level, optional)

**Example**:

```yaml
default_role_for:
  ingest: data-engineer
  analysis: analyst
  visualization: renderer
  validation: critic
  evaluation: evaluator
  orchestration: operator
  hypothesis: researcher
```

**Constraints**:
- Keys are free-form phase keywords (e.g., `ingest`, `analysis`, `visualization`).
- Values must be one of the 7 canonical role names: `data-engineer`, `analyst`, `researcher`, `critic`, `renderer`, `evaluator`, `operator`.
- Each value must also appear in the project's `roles:` list — you cannot route to a role that is not active in the project.
- The block is entirely optional; `AgentsConfig.default_role_for` is `None` when absent.

**Schema**: `config.schema.json` enforces value enum (7 canonical roles) via `additionalProperties: { type: "string", enum: [...] }`.

**Runtime validation** (`validate_config`): after schema check, each value is verified to be present in the project's `roles` list. A value that passes the schema enum but is not in `roles` raises `ConfigError`.

---

## See Also

- `.agents/SETUP.md` — symlink instructions
- `.agents/config.schema.json` — canonical schema
- `src/insight_kit/provenance/run.py` — Run API + tier definitions
- `viz/core/pageTypeRules.ts` — PAGE_TYPE_RULES (renderer role context)
