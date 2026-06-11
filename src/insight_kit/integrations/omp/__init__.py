"""insight_kit.integrations.omp — omp 15.2.4 session JSONL parser.

omp writes session files as hidden `.tmp` dot-files in the --session-dir.
This module reverse-engineers that on-disk layout into typed turns that any
post-run telemetry/scoring harness can consume.

Public surface:
    from insight_kit.integrations.omp.session_parser import (
        parse_session, find_session_file, ParsedTurn, ParsedToolCall,
    )
"""
from __future__ import annotations

from insight_kit.integrations.omp.session_parser import (
    ParsedToolCall,
    ParsedTurn,
    find_session_file,
    parse_session,
)

__all__ = ["ParsedToolCall", "ParsedTurn", "find_session_file", "parse_session"]
