import json
from pathlib import Path

import pytest

from diagramkit import drawio, hld, seq
from diagramkit.core import SpecError, load_spec, to_svg, write_outputs
from diagramkit.route import seg_hits

EX = Path(__file__).parent.parent / "examples"
ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#888"/></svg>'


@pytest.mark.parametrize("name", ["login-sequence.yaml", "checkout-sequence.json"])
def test_seq_examples(name, tmp_path):
    d = seq.build(load_spec(EX / name), "t")
    files = write_outputs(d, tmp_path)
    assert {f.suffix for f in files} >= {".excalidraw", ".svg", ".drawio"}
    assert drawio.validate((tmp_path / "t.drawio").read_text(encoding="utf-8")) == []


def test_hld_example_no_collisions(tmp_path):
    d = hld.build(load_spec(EX / "checkout-hld.yaml"), "t", base_dir=EX)
    assert d.warnings == []
    xml = drawio.convert_scene(d.scene())
    assert drawio.validate(xml) == []


def test_edges_never_enter_other_boxes():
    spec = load_spec(EX / "checkout-hld.yaml")
    d = hld.build(spec, "t", base_dir=EX)
    boxes = {e["id"][2:]: e for e in d.elements if e["type"] == "rectangle" and e["id"].startswith("n-")}
    for a in (e for e in d.elements if e["type"] == "arrow" and e["id"].startswith("e-")):
        pts = [tuple(p) for p in a["customData"]["route"]]
        assert len(pts) <= 4  # at most 3 segments
        for b in boxes.values():
            r = (b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"])
            for p, q in zip(pts, pts[1:]):
                assert not seg_hits(p, q, r, -1.0)


def test_via_and_icon(tmp_path):
    (tmp_path / "i.svg").write_text(ICON)
    spec = {"zones": [{"id": "z", "label": "Z", "cols": 2}],
            "nodes": [{"id": "a", "zone": "z", "label": "A", "icon": "i.svg"}, {"id": "b", "zone": "z", "label": "B"},
                      {"id": "c", "zone": "z", "label": "C", "col": 0, "row": 1}],
            "edges": [{"from": "a", "to": "c", "via": [[30, 140]]}, "a->b: x"]}
    d = hld.build(spec, "t", base_dir=tmp_path)
    assert any(e["type"] == "image" for e in d.elements)


def test_bad_icon_is_warning_not_crash(tmp_path):
    spec = {"zones": [{"id": "z", "label": "Z"}], "nodes": [{"id": "a", "zone": "z", "label": "A", "icon": "missing.png"}]}
    d = hld.build(spec, "t", base_dir=tmp_path)
    assert d.warnings and "icon skipped" in d.warnings[0]


@pytest.mark.parametrize("bad", [
    {"participants": ["a"], "steps": [{"msg": "a->zzz: hi"}]},
    {"participants": ["a"], "steps": [{"oops": 1}]},
    {"participants": ["a"]},
])
def test_seq_errors(bad):
    with pytest.raises(SpecError):
        seq.build(bad)


def test_themes_and_svg_escape():
    spec = {"title": "a < b & c", "participants": ["a", "b"], "steps": ["a->b: x < y"]}
    for t in ("default", "mono", "dark"):
        svg = to_svg(seq.build(spec, "t", theme=t))
        assert "a &lt; b &amp; c" in svg
    xml = drawio.convert_scene(seq.build(spec, "t").scene())
    assert drawio.validate(xml) == []


def test_builtin_icons_all_load():
    from diagramkit.core import list_icons, load_icon

    names = list_icons()
    assert len(names) >= 15
    for n in names:
        mt, du = load_icon(f"builtin:{n}", color="#123456")
        assert mt == "image/svg+xml" and du.startswith("data:image/svg+xml;base64,")
    with pytest.raises(ValueError):
        load_icon("builtin:nope")


def test_hld_example_has_icons():
    d = hld.build(load_spec(EX / "checkout-hld.yaml"), "t", base_dir=EX)
    assert sum(1 for e in d.elements if e["type"] == "image") >= 10
    assert d.warnings == []


@pytest.mark.parametrize("o,lo,hi", [("landscape", 1.2, 3.0), ("portrait", 0.4, 1.0)])
def test_hld_orientation_changes_shape_without_collisions(o, lo, hi):
    d = hld.build(load_spec(EX / "checkout-hld.yaml"), "t", base_dir=EX, orientation=o)
    assert lo <= d.width / d.height <= hi
    assert d.warnings == []


def test_convert_roundtrip(tmp_path):
    from diagramkit.cli import main

    d = hld.build(load_spec(EX / "checkout-hld.yaml"), "a", base_dir=EX)
    write_outputs(d, tmp_path, formats=("excalidraw",))
    assert main(["convert", str(tmp_path / "a.excalidraw"), "portrait", "-o", str(tmp_path), "-f", "svg,drawio"]) == 0
    assert (tmp_path / "a-portrait.svg").exists()
    sd = seq.build(load_spec(EX / "login-sequence.yaml"), "s")
    write_outputs(sd, tmp_path, formats=("excalidraw",))
    assert main(["convert", str(tmp_path / "s.excalidraw"), "landscape", "-o", str(tmp_path), "-f", "svg"]) == 0


def test_seq_orientation():
    sp = load_spec(EX / "login-sequence.yaml")
    ls = seq.build(sp, "t", orientation="landscape")
    pt = seq.build(sp, "t", orientation="portrait")
    assert ls.width / ls.height > pt.width / pt.height


def test_jumps_arc_and_none():
    spec = {"zones": [{"id": "z", "label": "Z", "cols": 3}],
            "nodes": [{"id": i, "zone": "z", "label": i.upper()} for i in "abcdef"],
            "edges": [{"from": "a", "to": "c", "via": [[0, 0]]}, "a->f", "c->d"]}
    spec["edges"] = [{"from": "d", "to": "f", "from_side": "top", "to_side": "top"}, {"from": "b", "to": "e", "label": ""}]
    on = hld.build(spec, "t")
    off = hld.build({**spec, "jumps": "none"}, "t")
    n_on = sum(len(e["points"]) for e in on.elements if e["type"] == "arrow")
    n_off = sum(len(e["points"]) for e in off.elements if e["type"] == "arrow")
    assert n_on >= n_off
    assert all("route" in e["customData"] for e in on.elements if e["type"] == "arrow" and e["id"].startswith("e-"))
    xml = drawio.convert_scene(on.scene())
    assert "jumpStyle=arc" in xml and drawio.validate(xml) == []
    assert "jumpStyle" not in drawio.convert_scene(off.scene())


def test_add_jumps_geometry():
    from diagramkit.route import add_jumps

    h = [(0, 50), (200, 50)]
    v = [(100, 0), (100, 100)]
    a, b = add_jumps([h, v])
    assert b == [(100, 0), (100, 100)]
    assert len(a) > 4 and min(p[1] for p in a) < 50  # arc rises above the line
    assert a[0] == (0, 50) and a[-1] == (200, 50)


def test_seq_frame_contains_wide_note():
    spec = {"participants": ["a", "b"], "steps": [
        {"frame": "alt  x", "steps": [
            "a->b: hi",
            {"note": "a very long note text that is wider than the frame padding allows for sure", "over": ["a"]}]}]}
    d = seq.build(spec, "t")
    frame = next(e for e in d.elements if e["id"].startswith("g-fr"))
    note = next(e for e in d.elements if e["id"].startswith("n-nt"))
    assert frame["x"] <= note["x"] and note["x"] + note["width"] <= frame["x"] + frame["width"]


def test_seq_frame_label_has_background_plate():
    d = seq.build({"participants": ["a", "b"], "steps": [{"frame": "loop  x", "steps": ["a->b: hi"]}]}, "t")
    assert any(e["id"].startswith("glb-") for e in d.elements)


def test_hld_unlinked_rows_pack_tighter_than_linked():
    spec = {"zones": [{"id": "z", "label": "Z"}],
            "nodes": [{"id": n, "zone": "z", "label": n} for n in "abcd"],
            "edges": ["a->b: linked"]}  # a-b linked, b-c and c-d not
    d = hld.build(spec, "t")
    y = {e["id"]: e["y"] for e in d.elements if e["id"] in ("n-a", "n-b", "n-c", "n-d")}
    h = {e["id"]: e["height"] for e in d.elements if e["id"] in ("n-a", "n-b", "n-c", "n-d")}
    linked_gap = y["n-b"] - (y["n-a"] + h["n-a"])
    tight_gap = y["n-d"] - (y["n-c"] + h["n-c"])
    assert tight_gap < linked_gap


def _node_boxes(d):
    return {e["id"][2:]: e for e in d.elements if e["type"] == "rectangle" and e["id"].startswith("n-")}


def test_hld_narrow_gap_edge_is_straight():
    spec = {"title": "t", "layout": {"node_gap_x": 24},
            "zones": [{"id": "z", "label": "Z", "cols": 2}],
            "nodes": [{"id": "a", "zone": "z", "label": "A"}, {"id": "b", "zone": "z", "label": "B"}],
            "edges": [{"from": "a", "to": "b", "from_side": "right", "to_side": "left"}]}
    d = hld.build(spec, "t")
    assert d.warnings == []
    arrow = next(e for e in d.elements if e["type"] == "arrow")
    assert len(arrow["customData"]["route"]) == 2  # direct line, no U-shape detour


def test_hld_fully_pinned_zones_are_not_reflowed():
    zones = [{"id": f"z{i}", "label": f"Z{i}", "row": 0, "col": i} for i in range(5)]
    nodes = [{"id": f"n{i}", "zone": f"z{i}", "label": f"N{i}"} for i in range(5)]
    d = hld.build({"title": "t", "columns": 5, "zones": zones, "nodes": nodes}, "t", orientation="portrait")
    ys = {round(b["y"]) for b in _node_boxes(d).values()}
    assert len(ys) == 1  # all five zones stay in one row even though portrait was requested


def test_hld_short_zone_fills_its_grid_cell():
    spec = {"title": "t", "columns": 2,
            "zones": [{"id": "tall", "label": "Tall", "row": 0, "col": 0}, {"id": "short", "label": "Short", "row": 0, "col": 1}],
            "nodes": [{"id": "a", "zone": "tall", "label": "A"}, {"id": "b", "zone": "tall", "label": "B"},
                      {"id": "c", "zone": "tall", "label": "C"}, {"id": "s", "zone": "short", "label": "S"}]}
    d = hld.build(spec, "t")
    boxes = _node_boxes(d)
    groups = {e["id"]: e for e in d.elements if e["id"].startswith("g-")}
    g = groups["g-short"]
    s = boxes["s"]
    top_gap = s["y"] - g["y"]
    bottom_gap = (g["y"] + g["height"]) - (s["y"] + s["height"])
    assert abs((top_gap - hld.LAYOUT["zone_header"]) - (bottom_gap - hld.LAYOUT["zone_pad"])) < 2  # centered between header and bottom padding


def test_auto_icon_falls_back_to_builtin_when_offline(monkeypatch, tmp_path):
    from diagramkit import logos
    monkeypatch.setenv("DIAGRAMKIT_OFFLINE", "1")
    monkeypatch.setattr(logos, "CACHE", tmp_path)
    assert logos.auto_icon("Primary database") == "builtin:database"
    assert logos.auto_icon("Shopper") == "builtin:user"
    assert logos.auto_icon("Quantum flux") is None
    assert logos.logo_slug("NGINX API Gateway") == "nginx"
    assert logos.logo_slug("PostgreSQL\npg_vector") == "postgresql"


def test_auto_icon_uses_cached_logo(monkeypatch, tmp_path):
    from diagramkit import logos
    monkeypatch.setenv("DIAGRAMKIT_OFFLINE", "1")
    monkeypatch.setattr(logos, "CACHE", tmp_path)
    (tmp_path / "redis.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
    assert logos.auto_icon("Redis cache").endswith("redis.svg")


def test_hld_icon_none_and_icons_none_disable_auto(monkeypatch, tmp_path):
    from diagramkit import logos
    monkeypatch.setenv("DIAGRAMKIT_OFFLINE", "1")
    monkeypatch.setattr(logos, "CACHE", tmp_path)
    spec = {"title": "t", "zones": [{"id": "z", "label": "Z"}],
            "nodes": [{"id": "a", "zone": "z", "label": "Database"}, {"id": "b", "zone": "z", "label": "Database", "icon": "none"}]}
    d = hld.build(spec, "t")
    imgs = {e["id"] for e in d.elements if e["type"] == "image"}
    assert imgs == {"img-a"}
    d2 = hld.build({**spec, "icons": "none"}, "t")
    assert not [e for e in d2.elements if e["type"] == "image"]


def test_hld_gutter_grows_with_edge_count():
    def gap(n_edges):
        nodes = [{"id": f"a{i}", "zone": "l", "label": f"A{i}"} for i in range(n_edges)]
        nodes += [{"id": f"b{i}", "zone": "r", "label": f"B{i}"} for i in range(n_edges)]
        edges = [{"from": f"a{i}", "to": f"b{(i + 1) % n_edges}"} for i in range(n_edges)]
        spec = {"title": "t", "columns": 2, "zones": [{"id": "l", "label": "L", "row": 0, "col": 0}, {"id": "r", "label": "R", "row": 1, "col": 1}],
                "nodes": nodes, "edges": edges}
        g = {e["id"]: e for e in hld.build(spec, "t").elements if e["id"].startswith("g-")}
        return g["g-r"]["x"] - (g["g-l"]["x"] + g["g-l"]["width"])

    assert gap(6) > gap(1) + 40  # six diagonal edges need more room than one
