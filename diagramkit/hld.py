"""HLD / architecture diagrams from a spec: zones on a grid, nodes in a grid inside each zone, auto-routed edges."""
from __future__ import annotations

import copy
import math
import re

from pathlib import Path

from .core import (Diagram, SpecError, arrow_el, base, block_width, box_with_text, get_theme, need, register_icon, text_el,
                   text_width, wrap_text)
from .logos import auto_icon
from .route import EdgeIn, Router, add_jumps

_EDGE = re.compile(r"^\s*([\w.\-]+?)\s*(-->|->)\s*([\w.\-]+)\s*(?::\s*(.*))?$", re.S)
SIDES = ("top", "right", "bottom", "left")

# compact by default; `layout:` in the spec overrides any key. fill_rows spreads a short zone's rows over its grid cell.
LAYOUT = {"node_gap_x": 50, "node_gap_y": 58, "node_gap_y_tight": 24, "zone_gap_x": 50, "zone_gap_y": 52, "zone_pad": 20,
          "zone_header": 38, "margin": 40, "top": 80, "min_node_w": 140, "min_node_h": 52, "fill_rows": True}


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


def build(spec: dict, name: str = "hld", theme=None, base_dir=".", orientation=None) -> Diagram:
    spec = copy.deepcopy(spec)
    src = {"kind": "hld", "spec": copy.deepcopy(spec), "base_dir": str(Path(base_dir).resolve())}
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
        if str(n.get("icon", "")).lower() == "none":
            n["icon"] = None
        elif not n.get("icon") and str(spec.get("icons", "auto")).lower() != "none":
            n["icon"] = auto_icon(" ".join(str(n["label"]).split()))  # logo first, pictogram second
        icon = 52 if n.get("icon") else 0
        w = n.get("w") or max(L["min_node_w"], block_width(label, FS) + 36 + icon)
        h = n.get("h") or max(L["min_node_h"], len(label.split("\n")) * FS * 1.25 + 30)
        sizes[n["id"]] = (w, h)

    def make_zlayout(cap=None):
        """Per-zone node grid. `cap` re-flows zones whose nodes have no explicit row/col to that many columns."""
        zlayout = {}
        for z in zones:
            zl_ = _zone_layout(z, cap)
            zlayout[z["id"]] = zl_
        return zlayout

    def _zone_layout(z, cap):
        zn = [n for n in nodes if n["zone"] == z["id"]]
        ncols = int(z.get("cols", 1))
        if cap and not any(n.get("row") is not None or n.get("col") is not None for n in zn):
            ncols = cap
        span = {n["id"]: min(int(n.get("colspan", 1)), ncols) for n in zn}
        pos = _cells(zn, ncols, "node", lambda n: (n.get("row"), n.get("col")), lambda n: span[n["id"]])
        nrows = max([pos[n["id"]][0] for n in zn] + [-1]) + 1
        colw = [0.0] * ncols
        for n in zn:
            if span[n["id"]] == 1:
                colw[pos[n["id"]][1]] = max(colw[pos[n["id"]][1]], sizes[n["id"]][0])
        for c in range(ncols):
            colw[c] = colw[c] or L["min_node_w"]
        for n in zn:  # wide nodes: grow the spanned columns when too narrow
            sp = span[n["id"]]
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
        # rows joined by an edge keep the full gap (room for the line and its label); unlinked rows pack tighter
        linked = set()
        for k, e in enumerate(spec.get("edges") or []):
            d = _parse_edge(e, k)
            a, b = d.get("from"), d.get("to")
            if a in pos and b in pos:
                ra, rb = sorted((pos[a][0], pos[b][0]))
                linked.update(range(ra, rb))
        rowgap = [L["node_gap_y"] if r in linked else min(L["node_gap_y"], L["node_gap_y_tight"]) for r in range(max(nrows - 1, 0))]
        framed = z.get("frame", True)
        pad = L["zone_pad"] if framed else 0
        head = L["zone_header"] if framed else 0
        cw = sum(colw) + L["node_gap_x"] * (ncols - 1)
        ch = sum(rowh) + sum(rowgap)
        wz = max(cw + 2 * pad, text_width(str(z.get("label", "")), 15) + 40 if framed else 0)
        return dict(pos=pos, colw=colw, rowh=rowh, rowgap=rowgap, pad=pad, head=head, w=wz, h=ch + head + pad, framed=framed, nodes=zn, span=span)

    zlayout = make_zlayout()

    # ------------------------------------------------------------------ zones on the grid
    zcols = int(spec.get("columns") or min(len(zones), 3) or 1)
    explicit = _cells(zones, max(zcols, max([int(z.get("col", 0)) + 1 for z in zones] + [1])), "zone",
                      lambda z: (z.get("row"), z.get("col")), lambda z: 1)
    M = L["margin"]

    zedges = []  # (zone a, zone b) of every edge between different zones: sizes the gutters they pass through
    for k, e in enumerate(spec.get("edges") or []):
        d = _parse_edge(e, k)
        za, zb = nid.get(d.get("from"), {}).get("zone"), nid.get(d.get("to"), {}).get("zone")
        if za and zb and za != zb:
            zedges.append((za, zb))

    def grid(zp, zl):
        ncz = max(c for _, c in zp.values()) + 1
        nrz = max(r for r, _ in zp.values()) + 1
        cw, ch = [0.0] * ncz, [0.0] * nrz
        for z in zones:
            r, c = zp[z["id"]]
            cw[c] = max(cw[c], zl[z["id"]]["w"])
            ch[r] = max(ch[r], zl[z["id"]]["h"])
        # a gutter grows with the number of edges that have to run through it (one lane per edge), never below the base gap
        cross_c, cross_r = [0] * max(ncz - 1, 0), [0] * max(nrz - 1, 0)
        for za, zb in zedges:
            (ra, ca), (rb, cb) = zp[za], zp[zb]
            if ra == rb and ca == cb:
                continue
            if ca == cb:  # same column, different rows: the edge usually detours through a side gutter (prefer the right one)
                if ncz > 1:
                    cross_c[ca if ca < ncz - 1 else ca - 1] += 1
                continue
            if ra != rb:  # diagonal: a vertical run in the column gutter and a horizontal run in the row gutter
                for r in range(min(ra, rb), max(ra, rb)):
                    cross_r[r] += 1
            for c in range(min(ca, cb), max(ca, cb)):
                cross_c[c] += 1  # same row: only crosses; diagonal: vertical run through the gutter
        lane = L.get("lane", 14)
        gx = [max(L["zone_gap_x"], lane * min(n, 8) + 36) for n in cross_c]
        gy = [max(L["zone_gap_y"], lane * min(n, 8) + 36) for n in cross_r]
        xs_ = [M + sum(cw[:c]) + sum(gx[:c]) for c in range(ncz)]
        ys_ = [L["top"] + sum(ch[:r]) + sum(gy[:r]) for r in range(nrz)]
        return dict(pos=zp, cellw=cw, cellh=ch, xs=xs_, ys=ys_, gw=xs_[-1] + cw[-1] + M, gh=ys_[-1] + ch[-1] + M)

    orientation = orientation or spec.get("orientation")
    if orientation not in (None, "auto", "landscape", "portrait"):
        raise SpecError("orientation must be landscape, portrait or auto")
    plan = grid(explicit, zlayout)
    if orientation in ("landscape", "portrait"):
        lo, hi = (1.3, 2.0) if orientation == "landscape" else (0.55, 0.9)
        pairs = []
        for k, e in enumerate(spec.get("edges") or []):
            d = _parse_edge(e, k)
            za, zb = nid.get(d.get("from"), {}).get("zone"), nid.get(d.get("to"), {}).get("zone")
            if za and zb and za != zb:
                pairs.append((za, zb))
        cands = [("as-is", explicit)]
        if not all(z.get("row") is not None and z.get("col") is not None for z in zones):
            # re-flow only when the author left zone positions open; fully pinned grids are kept as written
            cands.append(("transposed", {k: (c, r) for k, (r, c) in explicit.items()}))
            flat = [{"id": z["id"]} for z in zones]
            for k in range(1, len(zones) + 1):
                cands.append((f"flow{k}", _cells(flat, k, "zone", lambda z: (None, None), lambda z: 1)))
        best = None
        for cap in [None, 1, 2, 3, 4, 5, 6]:
            zl_c = make_zlayout(cap)
            for label, zp in cands:
                g = grid(zp, zl_c)
                asp = (g["gw"] + 2 * M) / (g["gh"] + M + 60)
                dev = 0.0 if lo <= asp <= hi else abs(math.log(asp / (lo if asp < lo else hi)))
                near = sum(abs(zp[x][0] - zp[y][0]) + abs(zp[x][1] - zp[y][1]) for x, y in pairs)  # short zone hops
                cost = 3 * dev + 0.02 * near + (0 if label == "as-is" else 0.04) + (0 if cap is None else 0.04)
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, g, zl_c)
        plan, zlayout = best[1], best[2]
    zpos, cellw, cellh, xs, ys, gw, gh = (plan[k] for k in ("pos", "cellw", "cellh", "xs", "ys", "gw", "gh"))

    groups, node_els, label_els = [], [], []
    rects, soft, zrects = {}, [], []
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
            zrects.append((zx, zy, zx + zw, zy + zh))
        # stretch columns to the zone width, center content
        pad = zl["pad"]
        extra = zw - 2 * pad - (sum(zl["colw"]) + L["node_gap_x"] * (len(zl["colw"]) - 1))
        colw = [w + extra / len(zl["colw"]) for w in zl["colw"]]
        colx = [zx + pad + sum(colw[:k]) + L["node_gap_x"] * k for k in range(len(colw))]
        # a zone shorter than its grid cell: spread rows over the free height (single row: center it) so no band stays empty
        free = zh - zl["head"] - zl["pad"] - sum(zl["rowh"]) - sum(zl["rowgap"])
        nr = len(zl["rowh"])
        if free > 1 and L.get("fill_rows", True) and zl["framed"]:
            vgap = free / (nr - 1) if nr > 1 else 0.0
            voff = 0.0 if nr > 1 else free / 2
        else:
            vgap, voff = 0.0, 0.0
        rowy = [zy + zl["head"] + voff + sum(zl["rowh"][:k]) + sum(zl["rowgap"][:k]) + vgap * k for k in range(nr)]
        for n in zl["nodes"]:
            rr, cc = zl["pos"][n["id"]]
            sp = zl["span"][n["id"]]
            wcell = sum(colw[cc:cc + sp]) + L["node_gap_x"] * (sp - 1)
            w, h = sizes[n["id"]]
            w = wcell if not n.get("w") else min(w, wcell)
            x = colx[cc] + (wcell - w) / 2
            y = rowy[rr] + (zl["rowh"][rr] - h) / 2
            nfill, nstroke = th.color(n.get("color", z.get("color", "gray")))
            icon_id = register_icon(files, n["icon"], base_dir, warnings, th.text) if n.get("icon") else None
            off = 52 if icon_id else 0
            align = n.get("align", "center")
            pad = 20 if align == "left" else 0  # left-aligned text needs breathing room from the border
            node_els += box_with_text(n["id"], x, y, w, h, n["_label"], nfill, nstroke, fs=FS, text_color=th.text,
                                      dashed=bool(n.get("dashed")), text_x=x + off + pad, text_w=w - off - 2 * pad, align=align)
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
    router = Router(rects, (M / 2, L["top"] - 20, gw - M / 2, gh - M / 2 + 10), soft, zrects)
    routes = router.route_all(edges_in)

    edge_els = []
    maxx, maxy = gw, gh
    jumps = spec.get("jumps", "arc")
    if jumps not in ("arc", "none"):
        raise SpecError("jumps must be 'arc' or 'none'")
    jsize = float(spec.get("jump_size", 7))
    hopped = add_jumps([rt.pts for rt in routes], jsize) if jumps == "arc" else [rt.pts for rt in routes]
    for k, (rt, d) in enumerate(zip(routes, raw_edges)):
        head = d.get("arrow", "end")
        el = arrow_el(f"e-{k}", hopped[k], th.edge, dashed=bool(d.get("dashed")), head=head)
        el["customData"] = {"route": [list(p) for p in rt.pts], "jumps": jumps, "jumpSize": jsize}  # orthogonal route, for draw.io
        edge_els.append(el)
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
    return Diagram(name, els, W, H, th, files, warnings, src)
