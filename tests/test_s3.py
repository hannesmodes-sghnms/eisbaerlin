from pathlib import Path

from delstats.s3 import parse_list_objects_xml


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_list_objects_xml_uses_last_key_as_marker_when_needed():
    xml = (FIXTURES / "list_objects_page1.xml").read_text(encoding="utf-8")
    objects, truncated, marker = parse_list_objects_xml(xml)

    assert [x.key for x in objects] == [
        "league-team-matches/2026/1/1.json",
        "league-team-matches/2026/1/2.json",
    ]
    assert objects[0].size == 1234
    assert truncated is True
    assert marker == "league-team-matches/2026/1/2.json"
