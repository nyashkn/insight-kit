---
name: goal-management
type: skill
description: Manage the .insight-kit/goals/ lifecycle — create, queue, close, and bind goals to runs using catalog.yaml, open_queue.jsonl, and closed.jsonl.
roles_using: [operator]
metadata:
  last_verified: 2026-04-29
---

## Purpose

Goals are the planning layer above runs. A goal describes an analytical objective ("Quantify Q1 margin drivers") and tracks which runs contributed to achieving it. Without goal tracking, a sequence of related runs is just a flat list of files with no shared intent. The goals system lets the operator see which questions are open, which are closed, and which runs are evidence for a given answer.

## When to invoke

- When starting a new analytical project or sub-question.
- When a run is completed and its outputs should be linked to an open goal.
- When a goal is resolved and should be moved to `closed.jsonl`.
- When the operator needs to audit which goals have no associated runs.
- When a researcher or analyst asks "what are we trying to answer?"

## File layout

```
.insight-kit/
  goals/
    catalog.yaml          # named goal definitions (human-readable)
    open_queue.jsonl      # JSONL of open goal records (machine-readable)
    closed.jsonl          # JSONL of closed goal records
```

These files are created by `init_kit` (see `root.py`). `open_queue.jsonl` and `closed.jsonl` are empty on init.

## Goal record schema

```json
{
  "goal_id": "G-2026-001",
  "title": "Quantify Q1 gross margin drivers",
  "description": "Decompose the 3.3pp margin improvement into cost vs revenue contributions.",
  "status": "open",
  "priority": "P0",
  "created_at": "2026-04-28T09:00:00+03:00",
  "created_by": "operator",
  "linked_runs": [],
  "linked_claims": [],
  "tags": ["margin", "Q1-2026"]
}
```

## Procedure

### 1. Define a goal in catalog.yaml

```bash
cat >> .insight-kit/goals/catalog.yaml <<'EOF'

goals:
  - goal_id: G-2026-001
    title: "Quantify Q1 gross margin drivers"
    description: "Decompose the 3.3pp margin improvement into cost vs revenue contributions."
    priority: P0
    tags: [margin, Q1-2026]
EOF
```

### 2. Open the goal (push to open_queue.jsonl)

```python
import json
from datetime import datetime, timezone
from pathlib import Path

GOALS_DIR = Path(".insight-kit/goals")

def open_goal(goal_id: str, title: str, description: str,
              priority: str = "P1", tags: list[str] | None = None,
              created_by: str = "operator") -> dict:
    record = {
        "goal_id": goal_id,
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
        "linked_runs": [],
        "linked_claims": [],
        "tags": tags or [],
    }
    with (GOALS_DIR / "open_queue.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Opened goal: {goal_id}")
    return record

open_goal(
    goal_id="G-2026-001",
    title="Quantify Q1 gross margin drivers",
    description="Decompose the 3.3pp margin improvement into cost vs revenue contributions.",
    priority="P0",
    tags=["margin", "Q1-2026"],
)
```

### 3. Bind a run to an open goal

```python
import json
from pathlib import Path

GOALS_DIR = Path(".insight-kit/goals")

def bind_run_to_goal(goal_id: str, run_id: str, claim_ids: list[str] | None = None) -> None:
    queue_path = GOALS_DIR / "open_queue.jsonl"
    lines = queue_path.read_text().splitlines()
    updated = []
    found = False
    for line in lines:
        rec = json.loads(line)
        if rec["goal_id"] == goal_id:
            if run_id not in rec["linked_runs"]:
                rec["linked_runs"].append(run_id)
            if claim_ids:
                for cid in claim_ids:
                    if cid not in rec["linked_claims"]:
                        rec["linked_claims"].append(cid)
            found = True
        updated.append(json.dumps(rec))
    if not found:
        raise ValueError(f"Goal {goal_id!r} not found in open_queue.jsonl")
    queue_path.write_text("\n".join(updated) + "\n")
    print(f"Bound run {run_id} to goal {goal_id}")


# After a run completes:
bind_run_to_goal(
    goal_id="G-2026-001",
    run_id="2026-04-28_1430_analyst_revenue-analysis",
    claim_ids=["NMK-D-042", "NMK-D-043"],
)
```

### 4. Close a goal

```python
import json
from datetime import datetime, timezone
from pathlib import Path

GOALS_DIR = Path(".insight-kit/goals")

def close_goal(goal_id: str, resolution: str, closed_by: str = "operator") -> None:
    queue_path = GOALS_DIR / "open_queue.jsonl"
    closed_path = GOALS_DIR / "closed.jsonl"

    lines = queue_path.read_text().splitlines()
    remaining = []
    closed_rec = None

    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["goal_id"] == goal_id:
            rec["status"] = "closed"
            rec["resolution"] = resolution
            rec["closed_at"] = datetime.now(timezone.utc).isoformat()
            rec["closed_by"] = closed_by
            closed_rec = rec
        else:
            remaining.append(line)

    if closed_rec is None:
        raise ValueError(f"Goal {goal_id!r} not found in open_queue.jsonl")

    queue_path.write_text("\n".join(remaining) + ("\n" if remaining else ""))
    with closed_path.open("a") as f:
        f.write(json.dumps(closed_rec) + "\n")
    print(f"Closed goal: {goal_id}")


close_goal(
    goal_id="G-2026-001",
    resolution="Margin decomposition complete; NMK-D-042 and NMK-D-043 constitute the answer.",
    closed_by="analyst",
)
```

### 5. Audit open goals with no linked runs

```python
import json
from pathlib import Path

GOALS_DIR = Path(".insight-kit/goals")
queue_path = GOALS_DIR / "open_queue.jsonl"

orphan_goals = []
for line in queue_path.read_text().splitlines():
    if not line.strip():
        continue
    rec = json.loads(line)
    if not rec.get("linked_runs"):
        orphan_goals.append(rec["goal_id"])

print(f"Open goals with no linked runs: {orphan_goals}")
```

## Acceptance criteria

- `open_queue.jsonl` is valid JSONL (each line parseable as JSON).
- Every open goal has a `goal_id` matching `^G-\d{4}-\d{3,}$` convention (by convention, not enforced).
- `closed.jsonl` contains a `closed_at` field on every record.
- Audit of orphan goals returns 0 after a completed run is bound.
- `open_queue.jsonl` does not contain closed goals (they must be removed on close).

## Common pitfalls

**Not removing from open_queue on close:** A naive implementation appends to `closed.jsonl` but forgets to remove the record from `open_queue.jsonl`. Use the `close_goal` function above which rewrites the queue without the closed record.

**Multiple goals with the same goal_id:** JSONL format does not enforce uniqueness. Check before opening: `grep '"G-2026-001"' .insight-kit/goals/open_queue.jsonl` must return 0 lines before opening a new goal with that ID.

**Binding a run to a closed goal:** `bind_run_to_goal` searches only `open_queue.jsonl`. If the goal is already closed and you need to retroactively link a run, edit `closed.jsonl` directly.

**Large open_queue.jsonl:** JSONL rewrite is O(n) — fine for hundreds of goals, but not for thousands. If the queue exceeds 10k records, consider archiving old closed records to a yearly file.

## Examples

### List all open goal titles

```bash
python3 -c "
import json
for line in open('.insight-kit/goals/open_queue.jsonl'):
    line = line.strip()
    if line:
        r = json.loads(line)
        print(f\"[{r['priority']}] {r['goal_id']}: {r['title']}\")
"
```

### Show goals linked to a specific run

```bash
RUN_ID="2026-04-28_1430_analyst_revenue-analysis"
python3 -c "
import json
for path in ['.insight-kit/goals/open_queue.jsonl', '.insight-kit/goals/closed.jsonl']:
    for line in open(path):
        line = line.strip()
        if line:
            r = json.loads(line)
            if '${RUN_ID}' in r.get('linked_runs', []):
                print(r['goal_id'], '-', r['title'])
"
```

## Related skills

- `ingest-flow` — bind the run after ingest completes.
- `eval-protocol` — verify that closed goals have stable supporting claims.
- `agents-bootstrap` — goals catalog is checked during project initialization.
