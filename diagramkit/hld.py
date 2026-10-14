"""HLD / architecture diagrams from a spec: zones on a grid, nodes in a grid inside each zone, auto-routed edges."""
from __future__ import annotations

import re

from .core import (Diagram, SpecError, arrow_el, base, block_width, box_with_text, get_theme, need, register_icon, text_el,
                   text_width, wrap_text)
from .route import EdgeIn, Router

_EDGE = re.compile(r"^\s*([\w.\-]+?)\s*(-->|->)\s*([\w.\-]+)\s*(?::\s*(.*))?$", re.S)
SIDES = ("top", "right", "bottom", "left")

LAYOUT = {"node_gap_x": 60, "node_gap_y": 64, "zone_gap_x": 120, "zone_gap_y": 110, "zone_pad": 26, "zone_header": 46,
          "margin": 60, "top": 100, "min_node_w": 150, "min_node_h": 56}


def _cells(items, ncols, where, get_rc, get_span):
    """Assign (row, col) to items; explicit when given, else first free cell in row-major order."""
    used, pos = set(), {}
    for it in items:
        r, c = get_rc(it)
        if (r is None) != (c is None):
            raise SpecError(f"{where} '{it['id']}': give both row and col, or neither")
        if r is not None:
            span = get_span(it)
            if c + span > ncols:
                raise SpecError(f"{where} '{it['id']}': col {c} + span {span} exceeds {ncols} columns")
            cells = {(r, c + k) for k in range(span)}
            if cells & used:
                raise SpecError(f"{where} '{it['id']}': grid cell already taken")
            used |= cells
            pos[it["id"]] = (r, c)
    for it in items:
        if it["id"] in pos:
            continue
        span = get_span(it)
        if span > ncols:
            raise SpecError(f"{where} '{it['id']}': span {span} exceeds {ncols} columns")
        r = 0
        while True:
            for c in range(ncols - span + 1):
                cells = {(r, c + k) for k in range(span)}
                if not cells & used:
                    used |= cells
                    pos[it["id"]] = (r, c)
                    break
            if it["id"] in pos:
                break
            r += 1
    return pos


def _parse_edge(e, k):
    if isinstance(e, str):
        e = {"edge": e}
    if "edge" in e:
        m = _EDGE.match(e["edge"])
        if not m:
            raise SpecError(f"edges[{k}]: expected 'a->b: label' or 'a-->b: label', got {e['edge']!r}")
        d = {"from": m.group(1), "to": m.group(3), "label": (m.group(4) or "").strip(), "dashed": m.group(2) == "-->"}
        d.update({kk: v for kk, v in e.items() if kk != "edge"})
        return d
    return dict(e)


def build(spec: dict, name: str = "hld", theme=None, base_dir=".") -> Diagram:
    th = get_theme(theme if theme is not None else spec.get("theme"))
    L = {**LAYOUT, **(spec.get("layout") or {})}
    warnings: list[str] = []
    files: dict = {}

    zones = need(spec, "zones", "spec")
    nodes = need(spec, "nodes", "spec")
    zid = {}
    for k, z in enumerate(zones):
        i = str(need(z, "id", f"zones[{k}]"))
        if i in zid:
            raise SpecError(f"zones: duplicate id '{i}'")
        z["id"] = i
        zid[i] = z
    nid = {}
    for k, n in enumerate(nodes):
        i = str(need(n, "id", f"nodes[{k}]"))
        if i in nid:
            raise SpecError(f"nodes: duplicate id '{i}'")
        n["id"] = i
        z = need(n, "zone", f"node '{i}'")
        if z not in zid:
            raise SpecError(f"node '{i}': unknown zone '{z}' (known: {', '.join(zid)})")
        nid[i] = n

    # ------------------------------------------------------------------ node sizes + per-zone grid
    FS = 13
    sizes = {}
    for n in nodes:
        label = wrap_text(need(n, "label", f"node '{n['id']}'"))
        n["_label"] = label
        icon = 52 if n.get("icon") else 0
        w = n.get("w") or max(L["min_node_w"], block_width(label, FS) + 36 + icon)
        h = n.get("h") or max(L["min_node_h"], len(label.split("\n")) * FS * 1.25 + 30)
        sizes[n["id"]] = (w, h)

    zlayout = {}
    for z in zones:
        zn = [n for n in nodes if n["zone"] == z["id"]]
        ncols = int(z.get("cols", 1))
        pos = _cells(zn, ncols, "node", lambda n: (n.get("row"), n.get("col")), lambda n: int(n.get("colspan", 1)))
        nrows = max([pos[n["id"]][0] for n in zn] + [-1]) + 1
        colw = [0.0] * ncols
        for n in zn:
            if int(n.get("colspan", 1)) == 1:
                colw[pos[n["id"]][1]] = max(colw[pos[n["id"]][1]], sizes[n["id"]][0])
        for c in range(ncols):
            colw[c] = colw[c] or L["min_node_w"]
        for n in zn:  # wide nodes: grow the spanned columns when too narrow
            sp = int(n.get("colspan", 1))
            if sp > 1:
                c0 = pos[n["id"]][1]
                have = sum(colw[c0:c0 + sp]) + L["node_gap_x"] * (sp - 1)
                if sizes[n["id"]][0] > have:
                    for c in range(c0, c0 + sp):
                        colw[c] += (sizes[n["id"]][0] - have) / sp
        rowh = [0.0] * nrows
        for n in zn:
            r = pos[n["id"]][0]
            rowh[r] = max(rowh[r], sizes[n["id"]][1])
        framed = z.get("frame", True)
        pad = L["zone_pad"] if framed else 0
        head = L["zone_header"] if framed else 0
        cw = sum(colw) + L["node_gap_x"] * (ncols - 1)
        ch = sum(rowh) + L["node_gap_y"] * max(nrows - 1, 0)
        wz = max(cw + 2 * pad, text_width(str(z.get("label", "")), 15) + 40 if framed else 0)
        zlayout[z["id"]] = dict(pos=pos, colw=colw, rowh=rowh, pad=pad, head=head, w=wz, h=ch + head + pad, framed=framed, nodes=zn)

    # ------------------------------------------------------------------ zones on the grid
    zcols = int(spec.get("columns") or min(len(zones), 3) or 1)
    zpos = _cells(zones, max(zcols, max([int(z.get("col", 0)) + 1 for z in zones] + [1])), "zone",
                  lambda z: (z.get("row"), z.get("col")), lambda z: 1)
    ncz = max(c for _, c in zpos.values()) + 1
    nrz = max(r for r, _ in zpos.values()) + 1
    cellw, cellh = [0.0] * ncz, [0.0] * nrz
    for z in zones:
        r, c = zpos[z["id"]]
        cellw[c] = max(cellw[c], zlayout[z["id"]]["w"])
        cellh[r] = max(cellh[r], zlayout[z["id"]]["h"])
    M = L["margin"]
    xs = [M + sum(cellw[:c]) + L["zone_gap_x"] * c for c in range(ncz)]
    ys = [L["top"] + sum(cellh[:r]) + L["zone_gap_y"] * r for r in range(nrz)]
    gw = xs[-1] + cellw[-1] + M
    gh = ys[-1] + cellh[-1] + M

    groups, node_els, label_els = [], [], []
    rects, soft = {}, []
    for z in zones:
        zl = zlayout[z["id"]]
        r, c = zpos[z["id"]]
        zx, zy, zw, zh = xs[c], ys[r], cellw[c], cellh[r]
        fill, stroke = th.color(z.get("color", "gray"))
        if zl["framed"]:
            groups.append(base("rectangle", "g-" + z["id"], zx, zy, zw, zh, strokeColor=stroke, strokeStyle="dashed",
                               roundness={"type": 3}))
            lab = wrap_text(z.get("label", z["id"]))
            lw = text_width(lab, 15) + 6
            label_els.append(text_el("gl-" + z["id"], zx + 14, zy + 8, lab, 15, color=stroke, align="left", w=lw, h=20))
            soft.append((zx + 10, zy + 6, zx + 18 + lw, zy + 30))
        # stretch columns to the zone width, center content
        pad = zl["pad"]
        extra = zw - 2 * pad - (sum(zl["colw"]) + L["node_gap_x"] * (len(zl["colw"]) - 1))
        colw = [w + extra / len(zl["colw"]) for w in zl["colw"]]
        colx = [zx + pad + sum(colw[:k]) + L["node_gap_x"] * k for k in range(len(colw))]
        rowy = [zy + zl["head"] + sum(zl["rowh"][:k]) + L["node_gap_y"] * k for k in range(len(zl["rowh"]))]
        for n in zl["nodes"]:
            rr, cc = zl["pos"][n["id"]]
            sp = int(n.get("colspan", 1))
            wcell = sum(colw[cc:cc + sp]) + L["node_gap_x"] * (sp - 1)
            w, h = sizes[n["id"]]
            w = wcell if not n.get("w") else min(w, wcell)
            x = colx[cc] + (wcell - w) / 2
            y = rowy[rr] + (zl["rowh"][rr] - h) / 2
            nfill, nstroke = th.color(n.get("color", z.get("color", "gray")))
            icon_id = register_icon(files, n["icon"], base_dir, warnings) if n.get("icon") else None
            off = 52 if icon_id else 0
            align = n.get("align", "center")
            node_els += box_with_text(n["id"], x, y, w, h, n["_label"], nfill, nstroke, fs=FS, text_color=th.text,
                                      dashed=bool(n.get("dashed")), text_x=x + off, text_w=w - off, align=align)
            if icon_id:
                node_els.append(base("image", "img-" + n["id"], x + 10, y + h / 2 - 17, 34, 34, fileId=icon_id, status="saved",
                                     scale=[1, 1], groupIds=["grp-" + n["id"]], strokeColor="transparent"))
            rects[n["id"]] = (x, y, x + w, y + h)

    # ------------------------------------------------------------------ edges
    edges_in, raw_edges = [], []
    for k, e in enumerate(spec.get("edges") or []):
        d = _parse_edge(e, k)
        a, b = need(d, "from", f"edges[{k}]"), need(d, "to", f"edges[{k}]")
        for end in (a, b):
            if end not in rects:
                raise SpecError(f"edges[{k}]: unknown node '{end}'")
        for key in ("from_side", "to_side"):
            if d.get(key) and d[key] not in SIDES:
                raise SpecError(f"edges[{k}]: {key} must be one of {SIDES}")
        via = [tuple(v) for v in d.get("via", [])]
        edges_in.append(EdgeIn(f"{k}", a, b, wrap_text(d.get("label", "")), via, d.get("from_side"), d.get("to_side")))
        raw_edges.append(d)
    router = Router(rects, (M / 2, L["top"] - 20, gw - M / 2, gh - M / 2 + 10), soft)
    routes = router.route_all(edges_in)

    edge_els = []
    maxx, maxy = gw, gh
    for k, (rt, d) in enumerate(zip(routes, raw_edges)):
        head = d.get("arrow", "end")
        edge_els.append(arrow_el(f"e-{k}", rt.pts, th.edge, dashed=bool(d.get("dashed")), head=head))
        warnings += rt.problems
        for p in rt.pts:
            maxx, maxy = max(maxx, p[0] + M / 2), max(maxy, p[1] + M / 2)
        if rt.label_box:
            x0, y0, x1, y1 = rt.label_box
            label_els.append(base("rectangle", f"lb-{k}", x0, y0, x1 - x0, y1 - y0, backgroundColor=th.bg, strokeColor="transparent"))
            label_els.append(text_el(f"el-{k}", x0 + 1, y0 + 1, rt.edge.label, 11, color=th.msg_text, w=x1 - x0 - 2, h=y1 - y0 - 2))

    # ------------------------------------------------------------------ legend
    legend = spec.get("legend")
    items = []
    if isinstance(legend, dict):
        items = [{"color": c, "label": t} for c, t in legend.items()]
    elif isinstance(legend, list):
        items = [{"color": i["color"], "label": i["label"], "dashed": i.get("dashed", False)} for i in legend]
    ly = gh + 10
    if items:
        lx = M
        for k, it in enumerate(items):
            fill, stroke = th.color(it["color"])
            node_els.append(base("rectangle", f"lg-{k}", lx, ly, 40, 24, backgroundColor=fill, strokeColor=stroke, strokeWidth=2,
                                 strokeStyle="dashed" if it.get("dashed") else "solid", roundness={"type": 3}))
            tw = text_width(str(it["label"]), 12) + 6
            label_els.append(text_el(f"lgt-{k}", lx + 50, ly + 3, str(it["label"]), 12, color=th.text, align="left", w=tw, h=18))
            lx += 50 + tw + 40
        maxx = max(maxx, lx)
        maxy = max(maxy, ly + 24 + M / 2)

    W = max(maxx, block_width(wrap_text(spec.get("title", "")), 22) + 80)
    H = maxy
    title = wrap_text(spec.get("title", ""))
    if title:
        label_els.append(text_el("title", 0, 8, title, 22, color=th.text, w=W, h=30))
    if spec.get("subtitle"):
        label_els.append(text_el("sub", 0, 42, wrap_text(spec["subtitle"]), 12, color=th.subtext, w=W, h=18))
    els = groups + edge_els + node_els + label_els
    return Diagram(name, els, W, H, th, files, warnings)
