"""Unit tests for Run.ingest_skill — skill output provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from insight_kit import Run
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


def test_dict_output_json_serialized_deterministically(kit: Path):
    """Dict output → JSON serialized with sort_keys=True + hashed deterministically."""
    output_dict = {"results": [1, 2, 3], "query": "test"}

    with Run(topic="skill_test", agent="tester") as r:
        rec = r.ingest_skill(
            skill_name="test-skill",
            input="query text",
            output=output_dict,
        )

    # Verify record created
    assert rec.skill_name if hasattr(rec, "skill_name") else rec.subkind == "test-skill"

    # Find the skill outputs dir
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1
    skill_dir = runs[0] / "inputs" / "skill" / "test-skill"
    assert skill_dir.exists()

    # Find .json output file
    json_files = list(skill_dir.glob("*.output.json"))
    assert len(json_files) == 1

    # Verify content matches
    output_content = json_files[0].read_text()
    assert json.loads(output_content) == output_dict

    # Verify SHA matches deterministic serialization
    expected_json = json.dumps(output_dict, sort_keys=True)
    expected_sha = hashlib.sha256(expected_json.encode()).hexdigest()
    assert rec.sha256 == expected_sha


def test_str_output_utf8_encoded(kit: Path):
    """Str output → utf-8 encoded + hashed."""
    output_str = "This is a test output from the skill"

    with Run(topic="skill_test", agent="tester") as r:
        rec = r.ingest_skill(
            skill_name="search-skill",
            input="search query",
            output=output_str,
        )

    # Verify record
    assert rec.subkind == "search-skill"

    # Find the runs dir
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    skill_dir = runs[0] / "inputs" / "skill" / "search-skill"

    # Find .txt output file
    txt_files = list(skill_dir.glob("*.output.txt"))
    assert len(txt_files) == 1

    # Verify content
    output_content = txt_files[0].read_text()
    assert output_content == output_str

    # Verify SHA
    expected_sha = hashlib.sha256(output_str.encode()).hexdigest()
    assert rec.sha256 == expected_sha


def test_bytes_output_as_is(kit: Path):
    """Bytes output → as-is + hashed."""
    output_bytes = b"Binary output from skill execution"

    with Run(topic="skill_test", agent="tester") as r:
        rec = r.ingest_skill(
            skill_name="binary-skill",
            input="binary input",
            output=output_bytes,
        )

    # Verify record
    assert rec.subkind == "binary-skill"

    # Find the runs dir
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    skill_dir = runs[0] / "inputs" / "skill" / "binary-skill"

    # Find .bin output file
    bin_files = list(skill_dir.glob("*.output.bin"))
    assert len(bin_files) == 1

    # Verify content
    output_content = bin_files[0].read_bytes()
    assert output_content == output_bytes

    # Verify SHA
    expected_sha = hashlib.sha256(output_bytes).hexdigest()
    assert rec.sha256 == expected_sha


def test_skill_name_input_output_in_metadata(kit: Path):
    """skill_name + input + output all recorded in meta.json."""
    skill_name = "tavily-cli"
    input_data = "ROAS benchmarks Africa"
    output_data = {"results": [{"url": "example.com", "title": "ROAS"}]}

    with Run(topic="skill_test", agent="tester") as r:
        rec = r.ingest_skill(
            skill_name=skill_name,
            input=input_data,
            output=output_data,
            metadata={"latency_ms": 500, "model": "tavily-search-v2"},
        )

    # Find metadata file
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    skill_dir = runs[0] / "inputs" / "skill" / "tavily-cli"
    meta_files = list(skill_dir.glob("*.meta.json"))
    assert len(meta_files) == 1

    meta_content = json.loads(meta_files[0].read_text())

    # Verify metadata structure
    assert meta_content["skill_name"] == skill_name
    assert meta_content["sha256"] == rec.sha256
    assert "captured_at" in meta_content
    assert "input_summary" in meta_content
    assert meta_content["input_summary"] == input_data

    # Verify nested metadata
    assert meta_content["metadata"]["latency_ms"] == 500
    assert meta_content["metadata"]["model"] == "tavily-search-v2"


def test_idempotent_same_output_same_sha(kit: Path):
    """Two calls with same output → same sha (idempotent)."""
    output_data = {"query": "test", "results": 42}

    with Run(topic="skill_test", agent="tester") as r:
        rec1 = r.ingest_skill(
            skill_name="search",
            input="query1",
            output=output_data,
        )
        rec2 = r.ingest_skill(
            skill_name="search",
            input="query2",  # different input
            output=output_data,  # same output
        )

    # Same output → same SHA
    assert rec1.sha256 == rec2.sha256


def test_default_caveats_on_input_record(kit: Path):
    """default_caveats present on InputRecord."""
    with Run(topic="skill_test", agent="tester") as r:
        rec = r.ingest_skill(
            skill_name="external-api",
            input="test input",
            output="test output",
        )

    # Verify default_caveats
    assert rec.default_caveats == ["external_source", "non_audited", "skill_invoked"]


def test_dict_input_recorded_as_json(kit: Path):
    """Dict input recorded in input.json file."""
    input_dict = {"query": "test", "depth": "advanced", "max_results": 5}
    output = "skill output"

    with Run(topic="skill_test", agent="tester") as r:
        r.ingest_skill(
            skill_name="api-skill",
            input=input_dict,
            output=output,
        )

    # Find input file
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    skill_dir = runs[0] / "inputs" / "skill" / "api-skill"
    input_files = list(skill_dir.glob("*.input.json"))
    assert len(input_files) == 1

    # Verify input JSON content
    input_content = json.loads(input_files[0].read_text())
    assert input_content == input_dict


def test_lazy_mkdir_skill(kit: Path):
    """Lazy mkdir triggered on ingest_skill."""
    with Run(topic="skill_test", agent="tester") as r:
        r.ingest_skill(
            skill_name="test",
            input="input",
            output="output",
        )

    # Verify run dir was created
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "inputs" / "skill" / "test").exists()


def test_multiple_skills_separate_dirs(kit: Path):
    """Multiple skills stored in separate directories."""
    with Run(topic="skill_test", agent="tester") as r:
        r.ingest_skill(skill_name="skill-a", input="input_a", output="output_a")
        r.ingest_skill(skill_name="skill-b", input="input_b", output="output_b")

    # Verify separate dirs
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    skill_base = runs[0] / "inputs" / "skill"
    assert (skill_base / "skill-a").exists()
    assert (skill_base / "skill-b").exists()
