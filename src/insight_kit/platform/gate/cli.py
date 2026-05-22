"""T18 — uv-run CLI bridge: the C4 lang seam between the L3 pi extension and L1.

The L3 pi extension is TypeScript; the L1 gate is Python. They meet here. The
extension shells out — `uv run python -m insight_kit.gate.cli <subcommand>` —
once per tool call (the audit-engine `run_check` pattern, C4). Each invocation:

  emit-claim | emit-intervention | emit-research | emit-skill-use
    - reads a JSON payload (`--payload <json>`, else stdin),
    - calls the matching ik_*_emit wrapper through the frozen gate (I.emit, V1),
    - prints exactly one JSON line to stdout:
        {"ok": true,  "record": {...RecordRef...}}   on success
        {"ok": false, "error":  {rule_id,message,suggestion}}  on a gate reject
    - exit 0 = emitted, 1 = gate reject (V2), 2 = CLI/usage error.

  export-schema
    - prints the pydantic-derived, $defs-inlined JSON Schema for each of the
      four tool param shapes. This is the single schema source (C5): the TS
      TypeBox `parameters` are generated from this output, never hand-kept.

Each invocation is a fresh process, so RunState is rehydrated from the run
directory's records.jsonl — the claim_id-unique-in-run guard then holds across
the whole pi session, not just one subprocess call.

V5 — this module imports neither `hamilton` nor `pi`: it is pure Python over the
gate. The pi dependency lives entirely on the TypeScript side of the seam.

Cites: C4, C5, I.emit, V1, V2, V5.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.runstate import RecordRef, RunState
from insight_kit.platform.gate.schema import (
    ClaimRecord,
    InterventionRecord,
    ResearchRecord,
    SkillUseRecord,
)
from insight_kit.platform.gate.store import index_path, resolve_run_dir

# Exit codes — the TS extension branches on these.
EXIT_OK = 0
EXIT_REJECT = 1
EXIT_USAGE = 2

# subcommand -> emit wrapper. Wrapper kwargs are bound from the payload dict.
_EMIT_WRAPPERS = {
    "emit-claim": ik_claim_emit,
    "emit-intervention": ik_intervention_emit,
    "emit-research": ik_research_emit,
    "emit-skill-use": ik_skill_use_emit,
}


# ---------------------------------------------------------------------------
# RunState rehydration — claim_id-unique-in-run must hold across subprocesses
# ---------------------------------------------------------------------------


def _rehydrate_run_state(run_dir: Path) -> RunState:
    """Rebuild RunState.records from the run dir's records.jsonl index.

    Every CLI invocation is a fresh process — without this, the duplicate
    claim_id guard would only see records emitted within the single subprocess
    call (always zero). Rehydrating from the on-disk index makes the guard span
    the whole pi session. Index rows are projections, so the reconstructed
    RecordRefs carry only what the guard needs (record_type + claim_id).
    """
    run_state = RunState(run_dir=run_dir)
    idx = index_path(run_dir)
    if not idx.exists():
        return run_state
    for line in idx.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a corrupt index row must not block a fresh emit
        ref = RecordRef(
            record_id=row.get("record_id", ""),
            record_type=row.get("record_type", ""),
            record_fingerprint=row.get("record_fingerprint", ""),
            run_dir=run_dir,
        )
        if row.get("record_type") == "claim" and row.get("claim_id"):
            object.__setattr__(ref, "_claim_id", row["claim_id"])
        run_state.records.append(ref)
    return run_state


# ---------------------------------------------------------------------------
# emit-* subcommands
# ---------------------------------------------------------------------------


def _error_dict(exc: Exception) -> dict[str, Any]:
    """Serialize a LayerAValidationError (or any exception) to a JSON-safe dict."""
    return {
        "rule_id": getattr(exc, "rule_id", "validation-error"),
        "message": getattr(exc, "message", None) or str(exc),
        "suggestion": getattr(exc, "suggestion", None),
    }


def run_emit(subcommand: str, payload: dict[str, Any], run_dir: Path) -> tuple[int, dict[str, Any]]:
    """Route one emit payload through the gate. Returns (exit_code, result_dict).

    A gate reject (V2 — zero partial write) surfaces as exit 1 + a structured
    error; a payload that does not match the wrapper signature is exit 2.
    """
    wrapper = _EMIT_WRAPPERS[subcommand]
    run_state = _rehydrate_run_state(run_dir)
    try:
        ref = wrapper(**payload, run_state=run_state, run_dir=run_dir)
    except LayerAValidationError as exc:
        return EXIT_REJECT, {"ok": False, "error": _error_dict(exc)}
    except TypeError as exc:
        # Payload keys do not match the wrapper signature — a CLI contract error,
        # not a gate reject.
        return EXIT_USAGE, {
            "ok": False,
            "error": {
                "rule_id": "cli-usage",
                "message": f"payload does not match {subcommand} parameters: {exc}",
                "suggestion": "Check the payload keys against `export-schema`.",
            },
        }
    return EXIT_OK, {"ok": True, "record": ref.to_dict()}


# ---------------------------------------------------------------------------
# export-schema — pydantic JSON Schema -> tool param schema (C5)
# ---------------------------------------------------------------------------

# Model fields injected by _record_emit — callers never set them, so they are
# stripped from the tool param schema the LLM sees.
_INJECTED_FIELDS = frozenset({"data_fingerprint_source", "snapshot_fingerprint"})

_INPUT_DATA_PROP = {
    "type": "object",
    "description": (
        "Optional registered-upstream fingerprint dict for input provenance "
        "(V13). Omit for draft records with no registered upstream."
    ),
}


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every $ref/$defs into a self-contained schema.

    Pydantic emits nested models as `#/$defs/...` references. TypeBox's runtime
    validator is happiest with a ref-free schema, so the generated `parameters`
    must be self-contained. Sibling keys on a $ref node (e.g. description) are
    merged over the resolved definition.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                resolved = resolve(copy.deepcopy(defs.get(ref_name, {})))
                siblings = {k: resolve(v) for k, v in node.items() if k != "$ref"}
                return {**resolved, **siblings}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve({k: v for k, v in schema.items() if k != "$defs"})


def _param_schema(
    model: type,
    *,
    add_snapshot: bool = False,
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Derive a tool param schema from a pydantic record model (C5).

    - $defs inlined to a ref-free schema,
    - emit-injected fields and the fixed `record_type` discriminant dropped,
    - `input_data` added (a wrapper kwarg, not a model field),
    - `snapshot` added + required for knowledge records (T22/V20 wrapper kwarg),
    - fields in `optional` removed from `required` (the wrapper defaults them).
    """
    raw = _inline_defs(model.model_json_schema())
    props = {
        name: spec
        for name, spec in raw.get("properties", {}).items()
        if name not in _INJECTED_FIELDS and name != "record_type"
    }
    required = [
        name
        for name in raw.get("required", [])
        if name in props and name not in optional
    ]
    props["input_data"] = dict(_INPUT_DATA_PROP)
    if add_snapshot:
        props["snapshot"] = {
            "type": "object",
            "description": (
                "T22/V20 — captured-results payload (query/tool/source/timestamp "
                "+ data). Required and non-empty; persisted + content-addressed."
            ),
        }
        required.append("snapshot")
    return {
        "type": "object",
        "properties": props,
        "required": sorted(required),
        "additionalProperties": False,
    }


def export_schemas() -> dict[str, Any]:
    """The four tool param schemas, keyed by record type (C5 single source)."""
    return {
        "claim": _param_schema(ClaimRecord),
        "intervention": _param_schema(InterventionRecord),
        "research": _param_schema(ResearchRecord, add_snapshot=True, optional=("timestamp",)),
        "skill_use": _param_schema(SkillUseRecord, add_snapshot=True, optional=("timestamp",)),
    }


# ---------------------------------------------------------------------------
# argparse entry point
# ---------------------------------------------------------------------------


def _emit_json(obj: dict[str, Any]) -> None:
    """Write one compact JSON line to stdout — the seam's wire format."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="insight_kit.gate.cli",
        description="L1 typed-record gate — uv-run CLI bridge for the L3 pi extension (C4).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in _EMIT_WRAPPERS:
        p = sub.add_parser(name, help=f"{name} through the L1 gate")
        p.add_argument("--payload", help="JSON payload object; if omitted, read from stdin")
        p.add_argument("--run-dir", help="run directory; overrides INSIGHT_KIT_RUN_DIR")
    sp = sub.add_parser("export-schema", help="print the four tool param schemas (C5)")
    sp.add_argument("--out", help="write to this file instead of stdout")

    args = parser.parse_args(argv)

    if args.command == "export-schema":
        rendered = json.dumps(export_schemas(), indent=2, sort_keys=True)
        if args.out:
            Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        else:
            sys.stdout.write(rendered + "\n")
        return EXIT_OK

    # emit-* — read + parse payload.
    raw = args.payload if args.payload is not None else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_json(
            {"ok": False, "error": {"rule_id": "cli-usage", "message": f"invalid JSON payload: {exc}"}}
        )
        return EXIT_USAGE
    if not isinstance(payload, dict):
        _emit_json(
            {"ok": False, "error": {"rule_id": "cli-usage", "message": "payload must be a JSON object"}}
        )
        return EXIT_USAGE

    try:
        run_dir = resolve_run_dir(Path(args.run_dir) if args.run_dir else None)
    except ValueError as exc:
        _emit_json({"ok": False, "error": {"rule_id": "cli-usage", "message": str(exc)}})
        return EXIT_USAGE

    code, result = run_emit(args.command, payload, run_dir)
    _emit_json(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
