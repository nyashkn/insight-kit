# configs/

Shared YAML configuration files for agent execution: model preferences, tool budgets, rate limits, and environment overrides.

Naming: `<domain>.yaml` or `<agent-role>.yaml` (e.g., `viz-evidence.yaml`, `claims-validation.yaml`, `model-preferences.yaml`).

## Purpose

Centralized config prevents duplication across agent profiles and allows environment-specific tuning (local dev vs. CI). Each config can override defaults for: model selection, token budgets, tool allowlists, retry policies, and timeout thresholds.

## Example structure

```
configs/
├── model-preferences.yaml    # Default Claude model versions + context limits
├── viz-evidence.yaml         # Tool budgets + Layer-check config for preflight
└── claims-validation.yaml    # Timeout + DuckDB connection settings
```

Each config includes: scope (applies to which agents/skills), parameter schema, and override rules.
