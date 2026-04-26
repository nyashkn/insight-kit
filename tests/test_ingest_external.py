"""Unit tests for Run.ingest_external method."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit import Run
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config
from insight_kit.provenance.run import _sha256


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


def test_ingest_external_search_string_content(kit: Path):
    """Test basic search ingest with string content."""
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="search",
            source_id="what is machine learning",
            content="Machine learning is a subset of AI...",
        )

    # Verify InputRecord
    assert rec.role == "external"
    assert rec.kind == "external"
    assert rec.subkind == "search"
    assert rec.source_id == "what is machine learning"
    assert rec.content_type == "text/plain"
    assert rec.bytes == len("Machine learning is a subset of AI...")
    assert len(rec.sha256) == 64  # SHA256 hex length

    # Verify files were created
    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "search"
    assert external_dir.exists()

    # Check content file
    sha_short = rec.sha256[:12]
    content_file = external_dir / f"{sha_short}.txt"
    assert content_file.exists()
    assert content_file.read_text() == "Machine learning is a subset of AI..."

    # Check SHA256 file
    sha_file = external_dir / f"{sha_short}.txt.sha256"
    assert sha_file.exists()
    assert sha_file.read_text().strip() == rec.sha256

    # Check metadata file
    meta_file = external_dir / f"{sha_short}.meta.json"
    assert meta_file.exists()
    meta = json.loads(meta_file.read_text())
    assert meta["kind"] == "search"
    assert meta["source_id"] == "what is machine learning"
    assert meta["content_type"] == "text/plain"
    assert meta["sha256"] == rec.sha256
    assert "captured_at" in meta


def test_ingest_external_url_html(kit: Path):
    """Test URL ingest with HTML content."""
    html_content = "<html><body>Hello</body></html>"
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="url",
            source_id="https://example.com",
            content=html_content,
            content_type="text/html",
        )

    assert rec.subkind == "url"
    assert rec.content_type == "text/html"

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "url"
    sha_short = rec.sha256[:12]
    content_file = external_dir / f"{sha_short}.html"
    assert content_file.exists()
    assert content_file.read_text() == html_content


def test_ingest_external_api_json_metadata(kit: Path):
    """Test API ingest with JSON content and dict metadata."""
    json_content = '{"status": "ok", "data": [1, 2, 3]}'
    metadata = {"status_code": 200, "provider": "anthropic", "model": "claude-3"}
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="api",
            source_id="anthropic:messages",
            content=json_content,
            content_type="application/json",
            metadata=metadata,
        )

    assert rec.subkind == "api"
    assert rec.content_type == "application/json"

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "api"
    sha_short = rec.sha256[:12]
    content_file = external_dir / f"{sha_short}.json"
    assert content_file.exists()

    meta_file = external_dir / f"{sha_short}.meta.json"
    meta = json.loads(meta_file.read_text())
    assert meta["metadata"] == metadata


def test_ingest_external_bytes_content(kit: Path):
    """Test ingest with binary/bytes content."""
    binary_data = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="scrape",
            source_id="http://example.com/image.png",
            content=binary_data,
            content_type="application/octet-stream",
        )

    assert rec.subkind == "scrape"
    assert rec.bytes == len(binary_data)

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "scrape"
    sha_short = rec.sha256[:12]
    content_file = external_dir / f"{sha_short}.bin"
    assert content_file.exists()
    assert content_file.read_bytes() == binary_data


def test_ingest_external_sha256_matches_file(kit: Path):
    """Test that SHA256 in record/meta matches actual file."""
    content = "test content for hashing"
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="search",
            source_id="test",
            content=content,
        )

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "search"
    sha_short = rec.sha256[:12]
    content_file = external_dir / f"{sha_short}.txt"

    # Compute SHA256 of actual file
    actual_sha = _sha256(content_file)
    assert actual_sha == rec.sha256

    # Verify meta.json also has matching SHA
    meta_file = external_dir / f"{sha_short}.meta.json"
    meta = json.loads(meta_file.read_text())
    assert meta["sha256"] == rec.sha256


def test_ingest_external_different_content_different_paths(kit: Path):
    """Test that different content produces different SHAs and paths."""
    with Run(topic="t", agent="a") as r:
        rec1 = r.ingest_external(
            kind="search",
            source_id="query1",
            content="content A",
        )
        rec2 = r.ingest_external(
            kind="search",
            source_id="query2",
            content="content B",
        )

    assert rec1.sha256 != rec2.sha256
    assert rec1.path != rec2.path

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "search"
    assert (external_dir / f"{rec1.sha256[:12]}.txt").exists()
    assert (external_dir / f"{rec2.sha256[:12]}.txt").exists()


def test_ingest_external_identical_content_same_path_idempotent(kit: Path):
    """Test that identical content produces same SHA and path (idempotent)."""
    content = "identical content"
    with Run(topic="t", agent="a") as r:
        rec1 = r.ingest_external(
            kind="search",
            source_id="query1",
            content=content,
        )
        rec2 = r.ingest_external(
            kind="search",
            source_id="query2",
            content=content,  # same content
        )

    assert rec1.sha256 == rec2.sha256
    # Both should reference the same file (idempotent)
    assert rec1.path == rec2.path


def test_ingest_external_confidence_override(kit: Path):
    """Test that confidence_override is captured."""
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="api",
            source_id="provider:endpoint",
            content="response data",
            confidence_override="high",
        )

    assert rec.confidence_override == "high"

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    external_dir = run_dir / "inputs" / "external" / "api"
    sha_short = rec.sha256[:12]
    meta_file = external_dir / f"{sha_short}.meta.json"
    meta = json.loads(meta_file.read_text())
    assert meta["confidence_override"] == "high"


def test_ingest_external_appears_in_manifest(kit: Path):
    """Test that external ingests appear in manifest."""
    with Run(topic="t", agent="a") as r:
        r.ingest_external(
            kind="search",
            source_id="test query",
            content="result",
        )

    run_dir = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    inputs = manifest["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["role"] == "external"
    assert inputs[0]["kind"] == "external"
    assert inputs[0]["subkind"] == "search"
    assert inputs[0]["source_id"] == "test query"
