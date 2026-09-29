import json
from pathlib import Path

from delstats.schema import collect_schema, inspect_match_directory, write_schema_report


FIXTURES = Path(__file__).parent / "fixtures"


def test_collect_schema_handles_nested_arrays():
    payload = json.loads((FIXTURES / "raw_shots.json").read_text(encoding="utf-8"))
    stats = collect_schema(payload)

    assert "$.match.shots" in stats
    assert "$.match.shots[].player_id" in stats
    assert stats["$.match.shots"].array_lengths == [2]
    assert stats["$.match.shots[].player_id"].occurrences == 2


def test_match_schema_report(tmp_path):
    raw_dir = tmp_path / "4411"
    raw_dir.mkdir()
    (raw_dir / "shots.json").write_bytes((FIXTURES / "raw_shots.json").read_bytes())
    (raw_dir / "shiftsSC.json").write_bytes((FIXTURES / "raw_shifts.json").read_bytes())

    report = inspect_match_directory(raw_dir)
    json_path, md_path = write_schema_report(report, output_dir=tmp_path / "schema")

    assert report["file_count"] == 2
    assert json_path.exists()
    assert md_path.exists()
    markdown = md_path.read_text(encoding="utf-8")
    assert "$.match.shots[].coordinate_x" in markdown
    assert "shiftsSC.json" in markdown
