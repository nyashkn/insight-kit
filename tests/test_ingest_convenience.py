"""Tests for Run.ingest_search, ingest_url, ingest_api convenience wrappers."""

import json

import pytest

from insight_kit.provenance.run import Run


@pytest.fixture
def run(kit_tmp, monkeypatch):
    """Create a Run instance in a temporary kit."""
    # Create a Run in the temp kit and yield it for use in tests
    runs_dir = kit_tmp / "runs"
    with Run(
        topic="test_convenience",
        agent="test",
        runs_dir_override=runs_dir,
        kit_start=kit_tmp,
    ) as r:
        yield r


def test_ingest_search_dict_results(run):
    """Test ingest_search with dict results → JSON serialized, kind=search."""
    results = {"title": "Test Result", "url": "https://example.com", "snippet": "A test"}
    rec = run.ingest_search(
        query="test query",
        tool="tavily",
        results=results,
    )

    assert rec.kind == "external"
    assert rec.subkind == "search"
    assert rec.source_id == "tavily:test query"
    assert rec.content_type == "application/json"
    assert rec.role == "external"
    assert rec.sha256 is not None
    assert rec.bytes > 0

    # Verify content is JSON serialized (read from the path stored in InputRecord)
    content_path = run.run_dir / rec.path
    assert content_path.exists()
    content = json.loads(content_path.read_text())
    assert content == results


def test_ingest_search_str_results(run):
    """Test ingest_search with str results → text/plain content_type."""
    results_str = "This is a plain text search result"
    rec = run.ingest_search(
        query="another query",
        tool="perplexity",
        results=results_str,
    )

    assert rec.kind == "external"
    assert rec.subkind == "search"
    assert rec.source_id == "perplexity:another query"
    assert rec.content_type == "text/plain"
    assert rec.bytes == len(results_str.encode("utf-8"))


def test_ingest_url_html_body(run):
    """Test ingest_url with HTML body → content saved verbatim."""
    html_body = "<html><head><title>Test</title></head><body>Hello</body></html>"
    rec = run.ingest_url(
        url="https://example.com/page",
        body=html_body,
        status=200,
    )

    assert rec.kind == "external"
    assert rec.subkind == "url"
    assert rec.source_id == "https://example.com/page"
    assert rec.content_type == "text/html"
    assert rec.role == "external"

    # Verify metadata contains status and fetcher
    external_dir = run.inputs_dir / "external" / "url"
    meta_files = list(external_dir.glob("*.meta.json"))
    assert len(meta_files) > 0
    meta = json.loads(meta_files[0].read_text())
    assert meta["metadata"]["status"] == 200
    assert meta["metadata"]["fetcher"] == "requests"


def test_ingest_url_bytes_body(run):
    """Test ingest_url with bytes body."""
    bytes_body = b"\x89PNG\r\n\x1a\n..."  # Fake PNG header
    rec = run.ingest_url(
        url="https://example.com/image.png",
        body=bytes_body,
        fetcher="playwright",
        status=200,
        content_type="image/png",
    )

    assert rec.kind == "external"
    assert rec.subkind == "url"
    assert rec.content_type == "image/png"
    assert rec.bytes == len(bytes_body)

    # Verify metadata
    external_dir = run.inputs_dir / "external" / "url"
    meta_files = list(external_dir.glob("*.meta.json"))
    meta = json.loads(meta_files[0].read_text())
    assert meta["metadata"]["fetcher"] == "playwright"


def test_ingest_api_dict_response_with_params(run):
    """Test ingest_api with dict response + params → metadata.params present."""
    response = {"data": {"id": "123", "status": "active"}, "success": True}
    params = {"user_id": "456", "limit": 10}

    rec = run.ingest_api(
        provider="meta-graph",
        endpoint="/v1/users",
        response=response,
        params=params,
        status=200,
    )

    assert rec.kind == "external"
    assert rec.subkind == "api"
    assert rec.source_id == "meta-graph:/v1/users"
    assert rec.content_type == "application/json"

    # Verify metadata
    external_dir = run.inputs_dir / "external" / "api"
    meta_files = list(external_dir.glob("*.meta.json"))
    assert len(meta_files) > 0
    meta = json.loads(meta_files[0].read_text())
    assert meta["metadata"]["provider"] == "meta-graph"
    assert meta["metadata"]["endpoint"] == "/v1/users"
    assert meta["metadata"]["params"] == params
    assert meta["metadata"]["status"] == 200


def test_ingest_api_non_2xx_status(run):
    """Test ingest_api with non-2xx status → status captured in metadata."""
    response = {"error": "Unauthorized", "code": "UNAUTHORIZED"}
    rec = run.ingest_api(
        provider="stripe",
        endpoint="/v1/charges",
        response=response,
        status=401,
    )

    assert rec.kind == "external"
    assert rec.subkind == "api"
    assert rec.source_id == "stripe:/v1/charges"

    # Verify metadata includes error status
    external_dir = run.inputs_dir / "external" / "api"
    meta_files = list(external_dir.glob("*.meta.json"))
    meta = json.loads(meta_files[0].read_text())
    assert meta["metadata"]["status"] == 401


def test_ingest_search_with_caller_metadata(run):
    """Test ingest_search merges caller-supplied metadata."""
    results = {"results": []}
    caller_metadata = {"latency_ms": 250, "model": "tavily-pro"}

    run.ingest_search(
        query="test",
        tool="tavily",
        results=results,
        metadata=caller_metadata,
    )

    external_dir = run.inputs_dir / "external" / "search"
    meta_files = list(external_dir.glob("*.meta.json"))
    meta = json.loads(meta_files[0].read_text())
    assert meta["metadata"]["query"] == "test"
    assert meta["metadata"]["tool"] == "tavily"
    assert meta["metadata"]["latency_ms"] == 250
    assert meta["metadata"]["model"] == "tavily-pro"
