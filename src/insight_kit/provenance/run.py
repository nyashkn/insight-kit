"""Run — context manager wrapping an analyst/critic/etl invocation.

Hygiene fixes applied per docs/helpers/v2/01_gap_audit.md:
- A1  parents[3] killed → uses .insight-kit/ marker probe
- A2  RUNS_DIR resolved from kit root, single source
- A5  Run.claim(id=) → Run.claim(claim_id=)  (no shadow of builtin)
- A9  lazy run dir creation (mkdir on first emit/ingest/claim)
- G1  structlog sink to logs/run.jsonl
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import structlog

from insight_kit.provenance.claim import Claim, Confidence
from insight_kit.provenance.root import find_kit_root, kit_config, runs_dir
from insight_kit.validation import (
    check_citation_referential_integrity,
    check_claim_id_format,
    check_claim_id_namespace,
    check_claim_id_unique,
    check_critic_edges,
    check_external_caveats,
    check_input_claims_exist,
    check_supersedes_chain_integrity,
)

SCHEMA_VERSION = "2.0"

AgentKind = Literal["sub_agent", "council", "human", "dagster", "hamilton"]

logger = structlog.get_logger("insight_kit.run")


# ---------- helpers ----------

def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _git_at(cwd: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, timeout=5
        ).strip()
    except Exception:
        return "unknown"


def _pip_freeze(cwd: Path) -> str:
    """Capture deps. Best-effort; falls back to system python."""
    for cmd in (["uv", "pip", "freeze"], [sys.executable, "-m", "pip", "freeze"]):
        try:
            return subprocess.check_output(cmd, cwd=cwd, text=True, timeout=15)
        except Exception:
            continue
    return ""


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s.lower()).strip("_")


def _ext_from_content_type(content_type: str) -> str:
    """Map MIME type to file extension."""
    mapping = {
        "text/plain": "txt",
        "text/html": "html",
        "text/xml": "xml",
        "application/json": "json",
        "application/pdf": "pdf",
        "application/octet-stream": "bin",
    }
    # return mapped or last part of mime type (e.g., "json" from "application/json")
    return mapping.get(content_type.lower(), content_type.split("/")[-1] or "bin")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------- record types ----------


@dataclass
class InputRecord:
    role: str
    path: str
    sha256: str
    bytes: int
    rows: int | None = None
    snapshot_mtime: str | None = None
    kind: str | None = None  # external: "search" | "url" | "api" | "scrape"
    subkind: str | None = None  # for external sources, repeats kind
    source_id: str | None = None  # canonical id: query, URL, provider:endpoint
    content_type: str | None = None  # mime type
    confidence_override: str | None = None  # provider-specific confidence rating
    default_caveats: list[str] | None = None  # default caveats for claims citing this input

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class OutputRecord:
    path: str
    sha256: str
    layer: str = "raw"  # metric | critique | viz | raw
    rows: int | None = None
    schema: str | None = None
    duckdb_view: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ApiCall:
    service: str
    endpoint: str
    operation: str | None = None
    cost_points: int | None = None
    http_status: int | None = None
    duration_ms: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------- Run ----------


class Run:
    """Provenanced run context. Writes immutable run dir on exit."""

    def __init__(
        self,
        topic: str,
        agent: str = "human",
        agent_kind: AgentKind = "human",
        model: str | None = None,
        invoked_via: str | None = None,
        task_title: str | None = None,
        prompt: str | None = None,
        parent_run_id: str | None = None,
        runs_dir_override: Path | None = None,
        *,
        kit_start: Path | str | None = None,
    ) -> None:
        # resolve kit_start: explicit > env var > default (cwd)
        resolved_start = None
        if kit_start is not None:
            resolved_start = Path(kit_start) if isinstance(kit_start, str) else kit_start
        elif env_start := os.environ.get("INSIGHT_KIT_ROOT"):
            resolved_start = Path(env_start)

        # resolve kit root + runs dir
        self._kit_root = find_kit_root(resolved_start)
        self._runs_dir = runs_dir_override or runs_dir(resolved_start)

        self.topic = _slug(topic)
        self.agent = agent
        self.agent_kind = agent_kind
        self.model = model
        self.invoked_via = invoked_via
        self.task_title = task_title or topic
        self.prompt_hash = (
            hashlib.sha256((prompt or "").encode()).hexdigest() if prompt else None
        )
        self.parent_run_id = parent_run_id

        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        self.run_id = f"{ts}_{_slug(agent)}_{self.topic}"
        self.run_dir = self._runs_dir / self.run_id

        # subdirs computed but not yet created (lazy per A9)
        self.inputs_dir = self.run_dir / "inputs"
        self.output_dir = self.run_dir / "output"
        self.logs_dir = self.run_dir / "logs"

        self._inputs: list[InputRecord] = []
        self._outputs: list[OutputRecord] = []
        self._claims: list[Claim] = []
        self._api_calls: list[ApiCall] = []
        self._started: float | None = None
        self._started_iso: str | None = None
        self._status = "running"
        self._error: str | None = None
        self._dirs_created = False

    def __enter__(self) -> Run:
        self._started = time.monotonic()
        self._started_iso = _now_iso()
        # do NOT create dirs yet — lazy on first use
        logger.info("run.start", run_id=self.run_id, agent=self.agent, topic=self.topic)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration = time.monotonic() - (self._started or time.monotonic())
        self._status = "failed" if exc else "completed"
        self._error = repr(exc) if exc else None

        # always create run dir when there are claims; skip only when truly empty (no artifacts + no claims)
        has_content = self._dirs_created or self._claims or exc
        if not has_content:
            logger.info("run.skip_empty", run_id=self.run_id, reason="no artifacts or claims")
            return

        self._ensure_dirs()

        # env.lock + caller script
        with suppress(Exception):
            (self.run_dir / "env.lock").write_text(_pip_freeze(self._kit_root))

        main = sys.modules.get("__main__")
        if main and hasattr(main, "__file__") and main.__file__:
            with suppress(Exception):
                shutil.copy2(main.__file__, self.run_dir / "script.py")

        manifest = self._build_manifest(duration)
        (self.run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str)
        )

        # claims.jsonl (append-only stream, separate from manifest) — always written
        with (self.run_dir / "claims.jsonl").open("w") as f:
            for c in self._claims:
                f.write(json.dumps(c.to_json(), default=str) + "\n")

        # checksums for everything in run dir
        checksums = []
        for p in sorted(self.run_dir.rglob("*")):
            if p.is_file() and p.name != "checksums.sha256":
                checksums.append(f"{_sha256(p)}  {p.relative_to(self.run_dir)}")
        (self.run_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n")

        # Layer B: claim-id global uniqueness check across all runs
        if not exc:
            unique_errors = check_claim_id_unique(self._kit_root)
            if unique_errors:
                for ue in unique_errors:
                    logger.warning("run.claim_id_duplicate", error=str(ue))
                raise unique_errors[0]

        logger.info(
            "run.end",
            run_id=self.run_id,
            status=self._status,
            duration_sec=round(duration, 2),
            run_dir=str(self.run_dir),
        )

    # ---------- internals ----------

    def _ensure_dirs(self) -> None:
        if self._dirs_created:
            return
        for d in (self.run_dir, self.inputs_dir, self.output_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._dirs_created = True

    def _build_manifest(self, duration: float) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "topic": self.topic,
            "status": self._status,
            "error": self._error,
            "agent": {
                "id": self.agent,
                "kind": self.agent_kind,
                "model": self.model,
                "invoked_via": self.invoked_via,
            },
            "task": {
                "title": self.task_title,
                "prompt_hash": self.prompt_hash,
                "parent_run_id": self.parent_run_id,
            },
            "vcs": {
                "git_sha_start": _git_at(self._kit_root, ["rev-parse", "--short=12", "HEAD"]),
                "git_branch": _git_at(self._kit_root, ["rev-parse", "--abbrev-ref", "HEAD"]),
                "dirty": bool(_git_at(self._kit_root, ["status", "--porcelain"])),
            },
            "inputs": [r.to_json() for r in self._inputs],
            "outputs": [r.to_json() for r in self._outputs],
            "claims": [c.to_json() for c in self._claims],
            "api_calls": [a.to_json() for a in self._api_calls],
            "code": {
                "script_path": "script.py" if (self.run_dir / "script.py").exists() else None,
                "script_sha256": (
                    _sha256(self.run_dir / "script.py")
                    if (self.run_dir / "script.py").exists()
                    else None
                ),
                "python": platform.python_version(),
                "deps_lock": "env.lock",
            },
            "runtime": {
                "started_at": self._started_iso,
                "ended_at": _now_iso(),
                "duration_sec": round(duration, 2),
                "exit_code": 1 if self._error else 0,
                "host": f"{platform.system().lower()}-{platform.release()}",
                "user": os.environ.get("USER", "unknown"),
            },
            "annotations": [],
        }

    # ---------- instrumentation ----------

    def ingest(
        self,
        path: str | Path,
        role: str = "raw",
        loader: Callable[[Path], Any] | None = None,
    ) -> Any:
        """Register an input file; return loaded data if loader provided."""
        self._ensure_dirs()
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"input not found: {p}")

        rel_path = (
            str(p.relative_to(self._kit_root))
            if p.is_relative_to(self._kit_root)
            else str(p)
        )
        rec = InputRecord(
            role=role,
            path=rel_path,
            sha256=_sha256(p),
            bytes=p.stat().st_size,
            snapshot_mtime=datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
            .astimezone()
            .isoformat(timespec="seconds"),
        )

        link = self.inputs_dir / p.name
        if not link.exists():
            try:
                link.symlink_to(p)
            except OSError:
                shutil.copy2(p, link)

        data = None
        if loader is not None:
            data = loader(p)
            with suppress(Exception):
                rec.rows = len(data)
        self._inputs.append(rec)
        return data if loader is not None else p

    def ingest_external(
        self,
        *,
        kind: str,
        source_id: str,
        content: str | bytes,
        metadata: dict | None = None,
        content_type: str = "text/plain",
        confidence_override: str | None = None,
        caveats: list[str] | None = None,
    ) -> InputRecord:
        """Ingest external source (search, URL, API, scrape); snapshot + hash.

        Args:
            kind: "search" | "url" | "api" | "scrape"
            source_id: canonical id (query string, URL, "provider:endpoint", etc.)
            content: response/page body (str or bytes)
            metadata: provider-specific metadata (status, model, params, etc.)
            content_type: MIME type (default: text/plain)
            confidence_override: provider's confidence rating if any
            caveats: caveats list for downstream claims; defaults to
                ['external_source', 'non_audited'] if not provided.

        Returns:
            InputRecord with all external metadata populated.
        """
        # Layer-A guard: caveats must not be explicitly empty
        check_external_caveats(caveats)
        # Apply default caveats if not provided
        resolved_caveats: list[str] = (
            caveats if caveats is not None else ["external_source", "non_audited"]
        )

        self._ensure_dirs()

        # Convert content to bytes if needed
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        # Compute SHA256
        sha = hashlib.sha256(content_bytes).hexdigest()
        sha_short = sha[:12]

        # Get file extension from content type
        ext = _ext_from_content_type(content_type)

        # Create inputs/external/{kind}/ directory
        external_dir = self.inputs_dir / "external" / kind
        external_dir.mkdir(parents=True, exist_ok=True)

        # Write three files
        content_path = external_dir / f"{sha_short}.{ext}"
        sha_path = external_dir / f"{sha_short}.{ext}.sha256"
        meta_path = external_dir / f"{sha_short}.meta.json"

        # Write content
        content_path.write_bytes(content_bytes)

        # Write SHA256 file
        sha_path.write_text(f"{sha}\n")

        # Write metadata JSON
        meta = {
            "kind": kind,
            "source_id": source_id,
            "content_type": content_type,
            "sha256": sha,
            "captured_at": datetime.now(UTC).isoformat(),
        }
        if metadata is not None:
            meta["metadata"] = metadata
        if confidence_override is not None:
            meta["confidence_override"] = confidence_override

        meta_path.write_text(json.dumps(meta, indent=2, default=str))

        # Create InputRecord
        rel_path = str(content_path.relative_to(self.run_dir))
        rec = InputRecord(
            role="external",
            kind="external",
            subkind=kind,
            path=rel_path,
            sha256=sha,
            bytes=len(content_bytes),
            source_id=source_id,
            content_type=content_type,
            confidence_override=confidence_override,
            default_caveats=resolved_caveats,
        )
        self._inputs.append(rec)
        return rec

    def ingest_skill(
        self,
        *,
        skill_name: str,
        input: dict | str,
        output: str | bytes | dict,
        metadata: dict | None = None,
    ) -> InputRecord:
        """Ingest skill invocation (e.g., tavily-cli, perplexity-mcp); snapshot + hash.

        Args:
            skill_name: name of the skill (e.g., "tavily-cli", "perplexity-search")
            input: the args/prompt passed to the skill (str or dict)
            output: what the skill returned (str, bytes, or dict)
            metadata: skill version, latency, exit code, etc.

        Returns:
            InputRecord with skill provenance and default_caveats populated.
        """
        self._ensure_dirs()

        # Normalize output to bytes for hashing
        if isinstance(output, dict):
            normalized_output = json.dumps(output, sort_keys=True).encode("utf-8")
            output_ext = "json"
        elif isinstance(output, str):
            normalized_output = output.encode("utf-8")
            output_ext = "txt"
        else:  # bytes
            normalized_output = output
            output_ext = "bin"

        # Compute SHA256
        skill_sha = hashlib.sha256(normalized_output).hexdigest()
        sha_short = skill_sha[:12]

        # Create inputs/skill/{skill_name}/ directory
        skill_dir = self.inputs_dir / "skill" / _slug(skill_name)
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write three files: output, input, metadata
        output_path = skill_dir / f"{sha_short}.output.{output_ext}"
        input_path = skill_dir / f"{sha_short}.input.json"
        meta_path = skill_dir / f"{sha_short}.meta.json"

        # Write output
        output_path.write_bytes(normalized_output)

        # Write input as JSON
        if isinstance(input, dict):
            input_json = input
        else:  # str
            input_json = {"prompt": input}
        input_path.write_text(json.dumps(input_json, indent=2, default=str))

        # Write metadata JSON
        meta = {
            "skill_name": skill_name,
            "sha256": skill_sha,
            "captured_at": _now_iso(),
        }
        if metadata is not None:
            meta["metadata"] = metadata

        # Add input summary for readability
        if isinstance(input, dict):
            meta["input_summary"] = {
                k: str(v)[:100] for k, v in input.items()
            }
        else:
            meta["input_summary"] = input[:100]

        meta_path.write_text(json.dumps(meta, indent=2, default=str))

        # Create InputRecord with default_caveats for skill-based external sources
        rel_path = str(output_path.relative_to(self.run_dir))
        rec = InputRecord(
            role="skill",
            kind="skill",
            subkind=skill_name,
            path=rel_path,
            sha256=skill_sha,
            bytes=len(normalized_output),
            source_id=skill_name,
            default_caveats=["external_source", "non_audited", "skill_invoked"],
        )
        self._inputs.append(rec)
        return rec

    def ingest_search(
        self,
        *,
        query: str,
        tool: str,
        results: str | dict | list,
        metadata: dict | None = None,
    ) -> InputRecord:
        """Wraps ingest_external with kind='search', source_id=f'{tool}:{query}'.

        Args:
            query: the search query string
            tool: search tool name ("tavily", "perplexity", "brave", etc.)
            results: the raw response payload (str, dict, or list)
            metadata: optional caller-supplied metadata to merge

        Returns:
            InputRecord with kind="search" and appropriate content_type.
        """
        # Normalize results to string
        if isinstance(results, (dict, list)):
            content = json.dumps(results, sort_keys=True)
            content_type = "application/json"
        else:
            content = results
            content_type = "text/plain"

        # Build source_id
        source_id = f"{tool}:{query}"

        # Merge metadata
        meta = {"tool": tool, "query": query}
        if metadata is not None:
            meta.update(metadata)

        return self.ingest_external(
            kind="search",
            source_id=source_id,
            content=content,
            metadata=meta,
            content_type=content_type,
        )

    def ingest_url(
        self,
        *,
        url: str,
        body: str | bytes,
        fetcher: str = "requests",
        status: int | None = None,
        headers: dict | None = None,
        content_type: str = "text/html",
    ) -> InputRecord:
        """Wraps ingest_external with kind='url', source_id=url.

        Args:
            url: the URL that was fetched
            body: the response body (str or bytes)
            fetcher: tool used to fetch ("requests", "playwright", etc.)
            status: HTTP status code if available
            headers: response headers dict if available
            content_type: MIME type (default: text/html)

        Returns:
            InputRecord with kind="url" and caller-supplied content_type.
        """
        # Build metadata
        meta = {"fetcher": fetcher}
        if status is not None:
            meta["status"] = status
        if headers is not None:
            meta["headers"] = headers

        return self.ingest_external(
            kind="url",
            source_id=url,
            content=body,
            metadata=meta,
            content_type=content_type,
        )

    def ingest_api(
        self,
        *,
        provider: str,
        endpoint: str,
        response: str | bytes | dict,
        params: dict | None = None,
        status: int | None = None,
    ) -> InputRecord:
        """Wraps ingest_external with kind='api', source_id=f'{provider}:{endpoint}'.

        Args:
            provider: API provider name (e.g., "meta-graph", "stripe")
            endpoint: API endpoint path
            response: the API response (str, bytes, or dict)
            params: optional request parameters dict
            status: optional HTTP status code

        Returns:
            InputRecord with kind="api" and appropriate content_type.
        """
        # Normalize response to string
        if isinstance(response, dict):
            content = json.dumps(response, sort_keys=True)
            content_type = "application/json"
        elif isinstance(response, bytes):
            content = response
            content_type = "application/json"  # assume JSON for bytes
        else:
            content = response
            content_type = "text/plain"

        # Build source_id and metadata
        source_id = f"{provider}:{endpoint}"
        meta = {"provider": provider, "endpoint": endpoint}
        if params is not None:
            meta["params"] = params
        if status is not None:
            meta["status"] = status

        return self.ingest_external(
            kind="api",
            source_id=source_id,
            content=content,
            metadata=meta,
            content_type=content_type,
        )

    # explicit emit methods (per council Revision A · god-enum killed)

    def emit_metric(self, df: Any, name: str, duckdb_view: str | None = None) -> Path:
        """Emit a metric-tier output. Lands in output/metrics/."""
        return self._emit(df, name, layer="metrics", duckdb_view=duckdb_view)

    def emit_critique(self, df: Any, name: str, duckdb_view: str | None = None) -> Path:
        return self._emit(df, name, layer="critique", duckdb_view=duckdb_view)

    def emit_viz(self, spec: Any, name: str) -> Path:
        """Emit a viz spec as JSON (chart specs, not parquet)."""
        self._ensure_dirs()
        out_dir = self.output_dir / "viz"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{_slug(name)}.json"
        out.write_text(json.dumps(spec, indent=2, default=str))
        self._outputs.append(
            OutputRecord(
                path=str(out.relative_to(self.run_dir)),
                sha256=_sha256(out),
                layer="viz",
            )
        )
        return out

    def emit_raw(self, df: Any, name: str, duckdb_view: str | None = None) -> Path:
        return self._emit(df, name, layer="raw", duckdb_view=duckdb_view)

    def _emit(
        self,
        df: Any,
        name: str,
        layer: str,
        duckdb_view: str | None = None,
    ) -> Path:
        self._ensure_dirs()
        out_dir = self.output_dir / layer
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{_slug(name)}.parquet"

        if hasattr(df, "write_parquet"):
            df.write_parquet(out)
        elif hasattr(df, "to_parquet"):
            df.to_parquet(out)
        else:
            import pyarrow.parquet as pq
            pq.write_table(df, out)

        # content-addressed sidecar (per Sun Tzu Revision D)
        out_sha = _sha256(out)
        (out_dir / f"{_slug(name)}.parquet.sha").write_text(out_sha + "\n")

        rows = None
        cols = None
        with suppress(Exception):
            rows = len(df)
            cols = list(df.columns) if hasattr(df, "columns") else None

        schema_path = out_dir / f"{_slug(name)}.schema.json"
        schema_path.write_text(json.dumps({"columns": cols, "rows": rows}, indent=2, default=str))

        view_name = duckdb_view or f"agent_run.{layer}__{self.topic}__{_slug(name)}"

        self._outputs.append(
            OutputRecord(
                path=str(out.relative_to(self.run_dir)),
                sha256=out_sha,
                layer=layer,
                rows=rows,
                schema=str(schema_path.relative_to(self.run_dir)),
                duckdb_view=view_name,
            )
        )
        return out

    def claim(
        self,
        claim_id: str,
        statement: str,
        value: Any = None,
        unit: str | None = None,
        tier: str = "derived",
        evidence_ref: str | None = None,
        confidence: Confidence = "medium",
        caveats: list[str] | None = None,
        assumptions: list[str] | None = None,
        node_id: str | None = None,
        metric_id: str | None = None,
        period: str | None = None,
        input_claims: list[str] | None = None,
        supports: list[str] | None = None,
        refutes: list[str] | None = None,
        supersedes: str | None = None,
    ) -> Claim:
        """Emit a structured claim. claim_id (not `id`) per A5 hygiene."""
        from insight_kit.provenance.claim import ClaimValue

        # Layer-A guards — fire before any state mutation
        check_claim_id_format(claim_id)
        namespace = kit_config(self._kit_root).get("namespace", "")
        if namespace:
            check_claim_id_namespace(claim_id, namespace)
        check_critic_edges(tier, supports, refutes)
        # Layer-A: referential integrity for input_claims
        current_ids = {c.claim_id for c in self._claims}
        check_input_claims_exist(claim_id, input_claims or [], current_ids, self._kit_root)
        # M5: prevent re-superseding an already-superseded claim
        check_supersedes_chain_integrity(claim_id, supersedes, self._kit_root, current_ids)
        # M6: citation referential integrity in statement/interpretation fields
        interpretation = None  # Claim.statement is the primary text; no interpretation field yet
        check_citation_referential_integrity(statement, interpretation, current_ids, self._kit_root)

        cv = None
        if value is not None or unit is not None:
            cv = ClaimValue(n=value, unit=unit) if not isinstance(value, ClaimValue) else value

        c = Claim(
            claim_id=claim_id,
            statement=statement,
            tier=tier,  # type: ignore[arg-type]
            value=cv,
            metric_id=metric_id,
            period=period,
            run_id=self.run_id,
            node_id=node_id,
            evidence_ref=evidence_ref,
            confidence=confidence,
            assumptions=assumptions or [],
            caveats=caveats or [],
            input_claims=input_claims or [],
            supports=supports or [],
            refutes=refutes or [],
            supersedes=supersedes,
            agent_id=self.agent,
            model=self.model,
            prompt_sha=self.prompt_hash,
        )
        self._claims.append(c)
        return c

    def api_call(
        self,
        service: str,
        endpoint: str,
        operation: str | None = None,
        cost_points: int | None = None,
        http_status: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._api_calls.append(
            ApiCall(
                service=service,
                endpoint=endpoint,
                operation=operation,
                cost_points=cost_points,
                http_status=http_status,
                duration_ms=duration_ms,
            )
        )

    def note(self, markdown: str) -> None:
        """Append to NOTES.md."""
        self._ensure_dirs()
        with (self.run_dir / "NOTES.md").open("a") as f:
            f.write(markdown.rstrip() + "\n\n")


# ---------- queries ----------


def latest_completed(
    topic: str,
    within_hours: float | None = None,
    runs_dir_override: Path | None = None,
    kit_start: Path | None = None,
) -> Path | None:
    """Return path of most recent completed run for topic, or None."""
    base = runs_dir_override or runs_dir(kit_start)
    if not base.exists():
        return None
    topic_slug = _slug(topic)
    cutoff = (
        datetime.now().astimezone() - timedelta(hours=within_hours)
        if within_hours is not None
        else None
    )

    for rd in sorted(base.iterdir(), reverse=True):
        if not rd.is_dir() or not rd.name.endswith(f"_{topic_slug}"):
            continue
        mf = rd / "manifest.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text())
        except Exception:
            continue
        if data.get("status") != "completed":
            continue
        if cutoff is not None:
            ended_str = data.get("runtime", {}).get("ended_at")
            if not ended_str:
                continue
            try:
                ended = datetime.fromisoformat(ended_str)
            except ValueError:
                continue
            if ended < cutoff:
                return None  # newest is too old
        return rd
    return None
