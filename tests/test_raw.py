import json
from pathlib import Path

from delstats.raw import RawMatchDownloader, local_relative_path, resource_keys_from_manifest


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, payload: bytes):
        self.status_code = 200
        self.content = payload
        self.headers = {
            "ETag": '"abc123"',
            "Last-Modified": "Tue, 29 Sep 2026 06:00:00 GMT",
        }


class FakeHttp:
    def get(self, url: str, **kwargs):
        if url.endswith("shiftsSC.json"):
            return FakeResponse((FIXTURES / "raw_shifts.json").read_bytes())
        if url.endswith("faceoffs.json"):
            return FakeResponse((FIXTURES / "raw_faceoffs.json").read_bytes())
        if url.endswith("visualization/shots/4411.json"):
            return FakeResponse((FIXTURES / "raw_shots.json").read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")


def test_resource_keys_include_verified_shots():
    payload = {
        "all_keys": [
            "matches/4411/shiftsSC.json",
            "matches/4411/faceoffs.json",
        ],
        "shot_key": "visualization/shots/4411.json",
        "shot_exists": True,
    }
    assert resource_keys_from_manifest(payload) == [
        "matches/4411/faceoffs.json",
        "matches/4411/shiftsSC.json",
        "visualization/shots/4411.json",
    ]


def test_local_relative_path_preserves_match_hierarchy():
    assert local_relative_path(4411, "matches/4411/team-stats/3.json") == Path(
        "team-stats/3.json"
    )
    assert local_relative_path(4411, "visualization/shots/4411.json") == Path(
        "shots.json"
    )


def test_download_match_from_manifest(tmp_path):
    manifest = tmp_path / "match_4411_resources.json"
    manifest.write_text(
        json.dumps(
            {
                "match_id": 4411,
                "all_keys": [
                    "matches/4411/shiftsSC.json",
                    "matches/4411/faceoffs.json",
                ],
                "shot_key": "visualization/shots/4411.json",
                "shot_exists": True,
            }
        ),
        encoding="utf-8",
    )

    output_manifest, result = RawMatchDownloader(http=FakeHttp()).download_from_manifest(
        manifest, output_dir=tmp_path / "raw"
    )

    assert output_manifest.exists()
    assert result.match_id == 4411
    assert len(result.resources) == 3
    assert (tmp_path / "raw/4411/shiftsSC.json").exists()
    assert (tmp_path / "raw/4411/faceoffs.json").exists()
    assert (tmp_path / "raw/4411/shots.json").exists()
    assert all(r.sha256 for r in result.resources)
