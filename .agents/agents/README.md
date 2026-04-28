# agents/

Reusable agent profiles for delegated work. Each AGENT.md defines a specialized role for external execution: code reviewers, security auditors, performance analysts, or domain experts.

Naming: `<role>.md` (e.g., `code-reviewer.md`, `security-auditor.md`).

## Purpose

Agent profiles describe persistent personas or execution instructions that can be spawned to handle specific workstreams independently. Unlike skills (which are user-facing functions), agents execute autonomously and may require specialized permissions, tools, or context.

## Structure

```
agents/
├── code-reviewer.md      # Code review agent profile
├── security-auditor.md   # Security-focused auditor
└── README.md             # This file
```

Each profile includes: role description, capabilities, constraints, and tool requirements.
