---
description: Manage the insight-kit goal lifecycle (new, status, close)
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: <new|status|close> [topic]
---

Manage goals in `.insight-kit/goals/` following the goal lifecycle defined in `docs/goal-management.md`.

Parse `$ARGUMENTS`: first token = SUBCOMMAND (`new`, `status`, or `close`), remaining tokens = TOPIC (optional).

---

### `new [topic]`

Create a new goal entry.

1. If TOPIC is empty, prompt the user: "What is the goal topic or question?".
2. Read `.insight-kit/goals/catalog.yaml` (create if missing) to determine the next goal ID.
3. Prompt for: goal statement, success criteria (bullet list), linked claims (optional), target date (optional).
4. Append the new goal to `catalog.yaml` with status `open`.
5. Append a goal-opened event to `.insight-kit/goals/open_queue.jsonl`.
6. Print the new goal ID and statement.

---

### `status [topic]`

Show current goal status.

1. Read `.insight-kit/goals/catalog.yaml` and `.insight-kit/goals/open_queue.jsonl`.
2. If TOPIC is provided, filter to goals whose topic contains TOPIC.
3. Print a summary table:
   ```
   ID       Topic              Status   Claims  Target
   ──────   ─────────────────  ──────   ──────  ──────
   G-001    march_revenue      open     3       2026-05-01
   G-002    churn_analysis     open     0       —
   ```
4. Flag goals with zero claims as needing attention.

---

### `close <topic>`

Close an open goal.

1. TOPIC is required for `close`. If missing, list open goals and ask the user to specify.
2. Find the matching goal in `catalog.yaml`. If ambiguous, list matches and ask user to confirm.
3. Prompt for: outcome summary (1-2 sentences), final claim IDs supporting closure.
4. Update the goal status to `closed` in `catalog.yaml`.
5. Append a goal-closed event to `.insight-kit/goals/closed.jsonl`.
6. Print a closure summary.

---

For goal lifecycle rules, see `docs/goal-management.md`.
