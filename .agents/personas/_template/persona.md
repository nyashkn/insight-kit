---
name: <name>
type: persona
domain: <one-line description of what this persona owns>
composes_with: [analyst, critic, researcher, renderer]  # pick the subset that applies
metadata:
  last_verified: 2026-04-29
---

# <Name> Persona

## 1. Domain Definition

### In Scope
<!-- List what this persona is responsible for analyzing, measuring, and claiming. Be specific about the data assets and business questions it owns. -->
- <topic 1>
- <topic 2>
- <topic 3>

### Out of Scope
<!-- Explicitly name adjacent domains this persona defers to, and the handoff condition. -->
- <adjacent domain> — defer to <other persona> when <condition>
- <adjacent domain> — defer to <other persona> when <condition>

### Boundary Notes
<!-- Any ambiguous boundary conditions worth calling out explicitly. -->
- <edge case 1>
- <edge case 2>

---

## 2. Glossary

Definitions below are computational, not soft synonyms. For ratio metrics, numerator/denominator/window are explicit.

| Term | Definition |
|------|------------|
| **<Term 1>** | <Precise definition. For metrics: numerator / denominator. Measurement window. Any exclusion criteria.> |
| **<Term 2>** | <Precise definition.> |
| **<Term 3>** | <Precise definition.> |
| **<Term 4>** | <Precise definition.> |
| **<Term 5>** | <Precise definition.> |
| **<Term 6>** | <Precise definition.> |
| **<Term 7>** | <Precise definition.> |
| **<Term 8>** | <Precise definition.> |
| **<Term 9>** | <Precise definition.> |
| **<Term 10>** | <Precise definition.> |

---

## 3. Common Claim Patterns

D-tier claim shapes this persona typically produces. Each pattern has an ID prefix convention and a canonical structure.

### Pattern 1: <name>
- **Shape:** `<entity> [metric] [direction] [magnitude] [window] [condition]`
- **Example:** "<Entity X's metric Y dropped Z% in window W under condition C>"
- **Confidence floor:** <high/medium/low — and why>

### Pattern 2: <name>
- **Shape:** `<entity> [metric] [direction] [magnitude] [window] [condition]`
- **Example:** "<Example claim text>"
- **Confidence floor:** <level — and why>

### Pattern 3: <name>
- **Shape:** `<entity> [comparison] [benchmark or baseline]`
- **Example:** "<Example claim text>"
- **Confidence floor:** <level>

### Pattern 4: <name>
- **Shape:** `<causal structure>`
- **Example:** "<Example claim text>"
- **Confidence floor:** <level>

---

## 4. Source Data Dependencies

Bronze and silver tables this persona draws from. Mapped to actual data assets where known.

### Bronze (raw ingest)
| Table / Parquet | Key Columns | Notes |
|-----------------|-------------|-------|
| `<table_name>` | `<col1>, <col2>` | <source system, cadence, known gaps> |

### Silver / Views
| View | Derivation | Notes |
|------|------------|-------|
| `<view_name>` | <what it computes> | <join dependencies, caveats> |

### Coverage Gaps
- <gap 1: data that would be needed but is unavailable>
- <gap 2>

---

## 5. Standard Analyses

Reproducible analyses this persona owns. Each is executable from the source data listed in Section 4.

### Analysis 1: <name>
- **Goal:** <one sentence>
- **Inputs:** `<table/view>` columns `<cols>`
- **Method:** <1-2 sentences on computation>
- **Output claim shape:** <Pattern from Section 3>

### Analysis 2: <name>
- **Goal:** <one sentence>
- **Inputs:** `<table/view>` columns `<cols>`
- **Method:** <1-2 sentences on computation>
- **Output claim shape:** <Pattern from Section 3>

### Analysis 3: <name>
- **Goal:** <one sentence>
- **Inputs:** `<table/view>` columns `<cols>`
- **Method:** <1-2 sentences on computation>
- **Output claim shape:** <Pattern from Section 3>

### Analysis 4: <name>
- **Goal:** <one sentence>
- **Inputs:** `<table/view>` columns `<cols>`
- **Method:** <1-2 sentences on computation>
- **Output claim shape:** <Pattern from Section 3>

### Analysis 5: <name>
- **Goal:** <one sentence>
- **Inputs:** `<table/view>` columns `<cols>`
- **Method:** <1-2 sentences on computation>
- **Output claim shape:** <Pattern from Section 3>

---

## 6. Anti-Patterns

Domain-specific gotchas with concrete examples. Generic warnings are not acceptable here.

### AP-1: <name>
**Problem:** <specific error pattern, with a concrete example showing how it manifests>
**Why it happens:** <root cause>
**Correct approach:** <what to do instead>

### AP-2: <name>
**Problem:** <specific error pattern>
**Why it happens:** <root cause>
**Correct approach:** <what to do instead>

### AP-3: <name>
**Problem:** <specific error pattern>
**Why it happens:** <root cause>
**Correct approach:** <what to do instead>

### AP-4: <name>
**Problem:** <specific error pattern>
**Why it happens:** <root cause>
**Correct approach:** <what to do instead>

---

## 7. Council Escalation Cues

When to call which council member. Each entry specifies the triggering condition, not a blanket "consult X for Y" rule.

| Trigger Condition | Call | Why |
|-------------------|------|-----|
| <specific condition in analysis output> | **kahneman** | <reason — typically cognitive bias in the data or analysis> |
| <specific condition> | **meadows** | <reason — feedback loops, system dynamics> |
| <specific condition> | **taleb** | <reason — tail risk, fat tails, fragility> |
| <specific condition> | **socrates** | <reason — definitional ambiguity, assumption challenge> |
| <specific condition> | **aristotle** | <reason — MECE / structure / taxonomy> |
| <specific condition> | **feynman** | <reason — first-principles, mechanism verification> |

---

## 8. Critic Stress-Tests

What the critic role should specifically challenge when wearing this persona. These are targeted probes, not generic quality checks.

### ST-1: <name>
**Probe:** <specific question the critic should ask or test>
**Expected weak point:** <where the analysis is most likely to be wrong or overclaimed>
**Pass condition:** <what a satisfactory response looks like>

### ST-2: <name>
**Probe:** <specific question>
**Expected weak point:** <where analysis is weak>
**Pass condition:** <what satisfies>

### ST-3: <name>
**Probe:** <specific question>
**Expected weak point:** <where analysis is weak>
**Pass condition:** <what satisfies>

### ST-4: <name>
**Probe:** <specific question>
**Expected weak point:** <where analysis is weak>
**Pass condition:** <what satisfies>
