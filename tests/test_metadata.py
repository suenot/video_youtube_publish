import json
from metadata import cap_tags, load_metadata


def test_cap_tags_stops_before_budget():
    # aaaa=4 fits; bbbb would be 4+1+4=9 > budget 8 -> stops at ["aaaa"]
    assert cap_tags(["aaaa", "bbbb", "cccc"], budget=8) == ["aaaa"]


def test_cap_tags_keeps_all_when_under_budget():
    assert cap_tags(["a", "b"], budget=480) == ["a", "b"]


def test_load_metadata_from_json(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"title": "T", "description": "D", "tags": ["x", "y"]}))
    m = load_metadata(str(p), "", "", "")
    assert m == {"title": "T", "description": "D", "tags": ["x", "y"]}


def test_cli_overrides_and_title_truncation(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"title": "old", "description": "D", "tags": ["x"]}))
    long = "z" * 130
    m = load_metadata(str(p), long, "", "a, b ,")
    assert len(m["title"]) == 100
    assert m["tags"] == ["a", "b"]


def test_angle_brackets_are_replaced_with_fullwidth():
    from metadata import strip_angle_brackets

    assert strip_angle_brackets("PBO > 0.05") == "PBO ＞ 0.05"
    assert strip_angle_brackets("a <b> c") == "a ＜b＞ c"
    assert strip_angle_brackets("no brackets") == "no brackets"


def test_norm_ignores_punctuation_and_case():
    """The duplicate check compares titles by letters and digits only, so
    Studio's rendering of quotes and spacing cannot hide an existing upload."""
    from publish import _norm
    assert _norm("Fixed Script or Free Agent? Pick Wrong #Shorts") == \
        _norm("fixed script  or free-agent pick wrong  shorts")
    assert _norm("") == ""
