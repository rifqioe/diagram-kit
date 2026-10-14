"""Excalidraw scene -> draw.io (.drawio). Works on any scene whose ids follow diagramkit's prefixes:
g-/gl- (frame + title), n-/t- (box + text), img- (icon), e-/ll- (arrow), lb-/el- (edge label bg + text), others = plain shapes.
Arrows are attached to the boxes they touch; waypoints are kept so draw.io draws the same route.
"""
from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

TOL = 3


def _html(t: str) -> str:
    return escape(t, quote=False).replace("\n", "<br>")


def _style(d: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in d.items()) + ";"


def convert_scene(ex: dict) -> str:
    els = [e for e in ex["elements"] if not e.get("isDeleted")]
    files = ex.get("files", {})
    bg = ex.get("appState", {}).get("viewBackgroundColor", "#ffffff")
    by_id = {e["id"]: e for e in els}
    texts = {e["id"]: e for e in els if e["type"] == "text"}
    node_text = {e["containerId"]: e for e in els if e["type"] == "text" and e.get("containerId")}

    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mxfile, "diagram", name="Diagram", id="diagram")
    maxx = max(e["x"] + e["width"] for e in els)
    maxy = max(e["y"] + e["height"] for e in els)
    model = ET.SubElement(diagram, "mxGraphModel", dx="0", dy="0", grid="0", gridSize="10", guides="1", tooltips="1",
                          connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth=str(int(maxx + 40)),
                          pageHeight=str(int(maxy + 40)), math="0", shadow="0")
    if bg and bg.lower() != "#ffffff":
        model.set("background", bg)
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    def vertex(cid, x, y, w, h, value, st):
        c = ET.SubElement(root, "mxCell", id=cid, value=value, style=st, vertex="1", parent="1")
        ET.SubElement(c, "mxGeometry", x=str(round(x, 1)), y=str(round(y, 1)), width=str(round(w, 1)),
                      height=str(round(h, 1)), **{"as": "geometry"})

    nodes = {}  # id -> (x, y, w, h): arrow attachment targets
    # z-order follows the scene order, except that edges go last-but-text so they sit above frames and boxes
    for e in els:
        if e["type"] != "rectangle":
            continue
        i = e["id"]
        if i.startswith("lb-"):
            continue
        dashed = e["strokeStyle"] == "dashed"
        if i.startswith("g-"):
            gl = texts.get("gl-" + i[2:])
            color = gl["strokeColor"] if gl else e["strokeColor"]
            vertex(i, e["x"], e["y"], e["width"], e["height"], _html(gl["text"]) if gl else "",
                   _style({"rounded": 1, "arcSize": 3, "whiteSpace": "wrap", "html": 1, "fillColor": "none",
                           "strokeColor": e["strokeColor"], "strokeWidth": 2, "dashed": 1, "dashPattern": "8 6",
                           "verticalAlign": "top", "align": "left", "spacingLeft": 14, "spacingTop": 4,
                           "fontSize": gl["fontSize"] if gl else 15, "fontColor": color, "container": 0}))
            continue
        t = node_text.get(i)
        has_fill = e["backgroundColor"] != "transparent"
        d = {"rounded": 1 if e.get("roundness") else 0, "arcSize": 12, "whiteSpace": "wrap", "html": 1,
             "fillColor": e["backgroundColor"] if has_fill else "none",
             "strokeColor": e["strokeColor"] if e["strokeColor"] != "transparent" else "none",
             "strokeWidth": e["strokeWidth"]}
        if dashed:
            d["dashed"] = 1
        if t:
            d.update({"fontSize": t["fontSize"], "fontColor": t["strokeColor"]})
            if t["textAlign"] != "center":
                d.update({"align": t["textAlign"], "spacingLeft": 10, "spacingRight": 10})
            if ("img-" + i[2:]) in by_id:
                d["spacingLeft"] = round(t["x"] - e["x"])
            nodes[i] = (e["x"], e["y"], e["width"], e["height"])
        vertex(i, e["x"], e["y"], e["width"], e["height"], _html(t["text"]) if t else "", _style(d))
    for e in els:  # icons
        if e["type"] == "image":
            f = files.get(e["fileId"])
            if f:
                mt, data = f["mimeType"], f["dataURL"].split(",", 1)[1]
                vertex(e["id"], e["x"], e["y"], e["width"], e["height"], "",
                       _style({"shape": "image", "verticalLabelPosition": "bottom", "verticalAlign": "top", "imageAspect": 0,
                               "aspect": "fixed", "image": f"data:{mt},{data}"}))  # draw.io style: no ';base64'

    def find_node(px, py):
        for nid, (x, y, w, h) in nodes.items():
            on_x = abs(px - x) <= TOL or abs(px - (x + w)) <= TOL
            on_y = abs(py - y) <= TOL or abs(py - (y + h)) <= TOL
            in_x = x - TOL <= px <= x + w + TOL
            in_y = y - TOL <= py <= y + h + TOL
            if (on_x and in_y) or (on_y and in_x):
                return nid, (x, y, w, h)
        return None, None

    for e in els:
        if e["type"] != "arrow":
            continue
        pts = [(e["x"] + p[0], e["y"] + p[1]) for p in e["points"]]
        sid, sb = find_node(*pts[0])
        tid, tb = find_node(*pts[-1])
        end, start = bool(e.get("endArrowhead")), bool(e.get("startArrowhead"))
        d = {"edgeStyle": "orthogonalEdgeStyle", "rounded": 0, "html": 1, "endArrow": "block" if end else "none",
             "startArrow": "block" if start else "none", "endFill": 1, "startFill": 1, "strokeColor": e["strokeColor"],
             "strokeWidth": e["strokeWidth"], "jettySize": "auto"}
        if e["strokeStyle"] == "dashed":
            d["dashed"] = 1
        if sb:
            d.update({"exitX": round((pts[0][0] - sb[0]) / sb[2], 3), "exitY": round((pts[0][1] - sb[1]) / sb[3], 3),
                      "exitDx": 0, "exitDy": 0})
        if tb:
            d.update({"entryX": round((pts[-1][0] - tb[0]) / tb[2], 3), "entryY": round((pts[-1][1] - tb[1]) / tb[3], 3),
                      "entryDx": 0, "entryDy": 0})
        c = ET.SubElement(root, "mxCell", id=e["id"], value="", style=_style(d), edge="1", parent="1")
        if sid:
            c.set("source", sid)
        if tid:
            c.set("target", tid)
        g = ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        if not sid:
            ET.SubElement(g, "mxPoint", x=str(round(pts[0][0], 1)), y=str(round(pts[0][1], 1)), **{"as": "sourcePoint"})
        if not tid:
            ET.SubElement(g, "mxPoint", x=str(round(pts[-1][0], 1)), y=str(round(pts[-1][1], 1)), **{"as": "targetPoint"})
        if len(pts) > 2:
            arr = ET.SubElement(g, "Array", **{"as": "points"})
            for x, y in pts[1:-1]:
                ET.SubElement(arr, "mxPoint", x=str(round(x, 1)), y=str(round(y, 1)))
    for e in els:  # free text: title, subtitle, divider/legend labels, edge labels
        if e["type"] != "text" or e.get("containerId") or e["id"].startswith("gl-"):
            continue
        d = {"text": "", "html": 1, "whiteSpace": "wrap", "fontSize": e["fontSize"], "fontColor": e["strokeColor"],
             "align": e["textAlign"], "verticalAlign": "middle"}
        if e["id"].startswith("el-"):
            lb = by_id.get("lb-" + e["id"][3:])
            d["labelBackgroundColor"] = lb["backgroundColor"] if lb else bg
        vertex(e["id"], e["x"], e["y"], e["width"], e["height"], _html(e["text"]), _style(d))
    ET.indent(mxfile)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(mxfile, encoding="unicode") + "\n"


def validate(xml: str) -> list[str]:
    """Structural check: well-formed XML, unique ids, edges reference existing cells. Returns a list of problems."""
    problems = []
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError as ex:
        return [f"not well-formed XML: {ex}"]
    cells = root.findall(".//mxCell")
    ids = [c.get("id") for c in cells]
    seen = set()
    for i in ids:
        if i in seen:
            problems.append(f"duplicate id {i}")
        seen.add(i)
    for c in cells:
        for k in ("source", "target", "parent"):
            v = c.get(k)
            if v is not None and v not in seen:
                problems.append(f"cell {c.get('id')}: {k}={v} not found")
        if c.get("vertex") == "1" and c.find("mxGeometry") is None:
            problems.append(f"vertex {c.get('id')} has no geometry")
    return problems


def convert_file(path: str | Path, out: str | Path | None = None) -> Path:
    p = Path(path)
    ex = json.loads(p.read_text(encoding="utf-8"))
    xml = convert_scene(ex)
    dest = Path(out) if out else p.with_suffix(".drawio")
    dest.write_text(xml, encoding="utf-8")
    return dest


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print("wrote", convert_file(a))
