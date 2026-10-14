"""Orthogonal edge router for HLD diagrams: side-to-side routes of at most 3 segments (Z / U / L / straight),
manual waypoints (`via`), collision checks against node boxes, and edge-label placement.

Pipeline (Router.route_all):
  A. pick (side_a, side_b) per edge by scoring every legal side pair with centered ports
  B. spread ports along each side, and align single ports so facing edges run straight
  C. route each edge with its real ports, picking the channel that avoids boxes and existing routes
"""
from __future__ import annotations

from dataclasses import dataclass, field

Rect = tuple  # (x0, y0, x1, y1)
Pt = tuple
H_SIDES = ("left", "right")
OUT = {"top": (0, -1), "right": (1, 0), "bottom": (0, 1), "left": (-1, 0)}
SWAP_SIDE = {"left": "top", "right": "bottom", "top": "left", "bottom": "right"}

NODE_MARGIN = 8        # hard clearance around boxes that are not the edge's own endpoints (violation = warning)
SOFT_MARGIN = 22       # preferred clearance: closer routes are penalized
PORT_INSET = 26        # ports stay this far from the box corners (shrinks on narrow boxes)
STUB = 22              # minimum straight run leaving/entering a box
LANE = 14              # spacing between parallel candidate channels
ZONE_CLEAR = 14        # preferred distance between a parallel line and a zone border


@dataclass
class EdgeIn:
    id: str
    a: str
    b: str
    label: str = ""
    via: list = field(default_factory=list)
    side_a: str | None = None
    side_b: str | None = None


@dataclass
class Route:
    edge: EdgeIn
    pts: list
    side_a: str
    side_b: str
    problems: list = field(default_factory=list)
    label_box: Rect | None = None
    label_pos: Pt | None = None


def side_point(r: Rect, side: str, pos: float) -> Pt:
    """pos in 0..1 along the side (left->right for top/bottom, top->bottom for left/right)."""
    x0, y0, x1, y1 = r
    if side == "top":
        return (x0 + pos * (x1 - x0), y0)
    if side == "bottom":
        return (x0 + pos * (x1 - x0), y1)
    if side == "left":
        return (x0, y0 + pos * (y1 - y0))
    return (x1, y0 + pos * (y1 - y0))


def simplify(pts):
    out = []
    for p in pts:
        p = (round(p[0], 1), round(p[1], 1))
        if out and abs(out[-1][0] - p[0]) < 0.05 and abs(out[-1][1] - p[1]) < 0.05:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.05 and abs(b[0] - c[0]) < 0.05) or (abs(a[1] - b[1]) < 0.05 and abs(b[1] - c[1]) < 0.05):
            del out[i]
        else:
            i += 1
    return out


def seg_hits(p: Pt, q: Pt, r: Rect, margin: float) -> bool:
    x0, y0, x1, y1 = r[0] - margin, r[1] - margin, r[2] + margin, r[3] + margin
    if abs(p[0] - q[0]) < 0.05:
        lo, hi = sorted((p[1], q[1]))
        return x0 < p[0] < x1 and lo < y1 and hi > y0
    lo, hi = sorted((p[0], q[0]))
    return y0 < p[1] < y1 and lo < x1 and hi > x0


def segs(pts):
    return list(zip(pts[:-1], pts[1:]))


def length(pts):
    return sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in segs(pts))


def _overlap_and_cross(p, q, other):
    """(collinear overlap count, perpendicular crossing count) between segment p-q and a list of segments."""
    ov = cr = 0
    ph = abs(p[1] - q[1]) < 0.05
    for a, b in other:
        oh = abs(a[1] - b[1]) < 0.05
        if ph and oh:
            if abs(p[1] - a[1]) < 7 and min(max(p[0], q[0]), max(a[0], b[0])) - max(min(p[0], q[0]), min(a[0], b[0])) > 2:
                ov += 1
        elif not ph and not oh:
            if abs(p[0] - a[0]) < 7 and min(max(p[1], q[1]), max(a[1], b[1])) - max(min(p[1], q[1]), min(a[1], b[1])) > 2:
                ov += 1
        else:
            h, v = ((p, q), (a, b)) if ph else ((a, b), (p, q))
            if min(h[0][0], h[1][0]) < v[0][0] < max(h[0][0], h[1][0]) and min(v[0][1], v[1][1]) < h[0][1] < max(v[0][1], v[1][1]):
                cr += 1
    return ov, cr


class Router:
    def __init__(self, nodes: dict, bounds: Rect, soft: list | None = None, zones: list | None = None):
        self.nodes, self.bounds, self.soft, self.zones = nodes, bounds, soft or [], zones or []
        self.done: list[Route] = []

    # ---- geometry of candidates
    def _chan(self, lo, hi):
        if lo > hi:
            lo, hi = hi, lo
        if hi - lo < 1:
            return [(lo + hi) / 2]
        mid = (lo + hi) / 2
        out = [mid]
        k = 1
        while mid + LANE * k <= hi or mid - LANE * k >= lo:
            if mid - LANE * k >= lo:
                out.append(mid - LANE * k)
            if mid + LANE * k <= hi:
                out.append(mid + LANE * k)
            k += 1
            if k > 14:
                break
        return out

    def _paths_h(self, pa, sa, pb, sb):
        """Both sides horizontal (left/right)."""
        oa, ob = OUT[sa][0], OUT[sb][0]
        res = []
        if oa == -ob:  # facing sides
            if (pb[0] - pa[0]) * oa > 2 * STUB - 1:
                if abs(pa[1] - pb[1]) < 0.5:
                    res.append([pa, pb])
                else:
                    for mx in self._chan(pa[0] + oa * STUB, pb[0] + ob * STUB):
                        res.append([pa, (mx, pa[1]), (mx, pb[1]), pb])
        else:  # same direction: U shape around
            far = max(pa[0], pb[0]) if oa > 0 else min(pa[0], pb[0])
            for d in range(40, 40 + 16 * LANE, LANE):
                ex = far + oa * d
                res.append([pa, (ex, pa[1]), (ex, pb[1]), pb])
        return res

    def paths(self, pa, sa, pb, sb):
        ha, hb = sa in H_SIDES, sb in H_SIDES
        if ha and hb:
            return self._paths_h(pa, sa, pb, sb)
        if not ha and not hb:
            sw = lambda p: (p[1], p[0])  # noqa: E731
            return [[sw(p) for p in path] for path in self._paths_h(sw(pa), SWAP_SIDE[sa], sw(pb), SWAP_SIDE[sb])]
        corner = (pb[0], pa[1]) if ha else (pa[0], pb[1])
        return [[pa, corner, pb]]

    # ---- scoring
    def _dirs_ok(self, pts, sa, sb):
        if len(pts) < 2:
            return False
        a, b = pts[0], pts[1]
        oa = OUT[sa]
        if (b[0] - a[0]) * oa[0] + (b[1] - a[1]) * oa[1] <= 0:
            return False
        c, d = pts[-2], pts[-1]
        ob = OUT[sb]
        return (d[0] - c[0]) * (-ob[0]) + (d[1] - c[1]) * (-ob[1]) > 0

    def _in_bounds(self, pts):
        bx0, by0, bx1, by1 = self.bounds
        return all(bx0 <= p[0] <= bx1 and by0 <= p[1] <= by1 for p in pts)

    def _hits(self, pts, ea, eb):
        hit = []
        for nid, r in self.nodes.items():
            m = -1.0 if nid in (ea, eb) else NODE_MARGIN
            if any(seg_hits(p, q, r, m) for p, q in segs(pts)):
                hit.append(nid)
        return hit

    def score(self, pts, ea, eb, use_done=True):
        hit = self._hits(pts, ea, eb)
        s = length(pts) + 35 * (len(pts) - 2) + 4000 * len(hit)
        for p, q in segs(pts):
            for r in self.soft:
                if seg_hits(p, q, r, 0):
                    s += 150
            for nid, r in self.nodes.items():  # prefer breathing room around other boxes
                if nid not in (ea, eb) and seg_hits(p, q, r, SOFT_MARGIN):
                    s += 90
            for z in self.zones:  # avoid hugging a zone border
                s += 60 * _hugs(p, q, z)
        if use_done and self.done:
            other = [sg for rt in self.done for sg in segs(rt.pts)]
            for p, q in segs(pts):
                ov, cr = _overlap_and_cross(p, q, other)
                s += 350 * ov + 25 * cr
        return s, hit

    def best(self, pa, sa, pb, sb, ea, eb, use_done=True):
        best = None
        for pts in self.paths(pa, sa, pb, sb):
            pts = simplify(pts)
            if not self._dirs_ok(pts, sa, sb) or not self._in_bounds(pts):
                continue
            s, hit = self.score(pts, ea, eb, use_done)
            if best is None or s < best[0] - 1e-9:
                best = (s, pts, hit)
        return best

    # ---- manual waypoints
    def via_path(self, pa, sa, pb, sb, via):
        pts = [pa] + [tuple(v) for v in via] + [pb]
        out = [pts[0]]
        horiz = sa in H_SIDES  # orientation of the segment leaving pa
        for i in range(1, len(pts)):
            p, q = out[-1], pts[i]
            last = i == len(pts) - 1
            if abs(p[0] - q[0]) < 0.05 or abs(p[1] - q[1]) < 0.05:
                out.append(q)
                horiz = abs(p[1] - q[1]) < 0.05
                continue
            if last:  # final segment must run along the entry side's axis
                first_h = sb not in H_SIDES  # if entry axis is vertical, go horizontal first
            else:
                first_h = horiz
            out.append((q[0], p[1]) if first_h else (p[0], q[1]))
            out.append(q)
            horiz = not first_h
        return simplify(out)

    # ---- orchestration
    @staticmethod
    def _trial_ports(ra, sa, rb, sb):
        """Side centers, except that facing sides with overlapping extent get aligned (straight) ports."""
        pa, pb = list(side_point(ra, sa, 0.5)), list(side_point(rb, sb, 0.5))
        if (sa in H_SIDES) == (sb in H_SIDES) and OUT[sa] == tuple(-v for v in OUT[sb]):
            ax = 1 if sa in H_SIDES else 0
            lo = max(ra[ax], rb[ax]) + PORT_INSET * 0.6
            hi = min(ra[ax + 2], rb[ax + 2]) - PORT_INSET * 0.6
            if lo <= hi:
                pa[ax] = pb[ax] = (lo + hi) / 2
        return tuple(pa), tuple(pb)

    def choose_sides(self, e: EdgeIn):
        ra, rb = self.nodes[e.a], self.nodes[e.b]
        sas = [e.side_a] if e.side_a else list(OUT)
        sbs = [e.side_b] if e.side_b else list(OUT)
        best = None
        ca = ((ra[0] + ra[2]) / 2, (ra[1] + ra[3]) / 2)
        cb = ((rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2)
        for sa in sas:
            for sb in sbs:
                pa, pb = self._trial_ports(ra, sa, rb, sb)
                r = self.best(pa, sa, pb, sb, e.a, e.b, use_done=False)
                if r is None:
                    continue
                # tiny tie-break: prefer sides that face the other node
                face = 0
                for s, c0, c1 in ((sa, ca, cb), (sb, cb, ca)):
                    o = OUT[s]
                    face -= 3 if (c1[0] - c0[0]) * o[0] + (c1[1] - c0[1]) * o[1] > 0 else 0
                sc = r[0] + face
                if best is None or sc < best[0]:
                    best = (sc, sa, sb)
        if best is None:
            return e.side_a or "bottom", e.side_b or "top"
        return best[1], best[2]

    def route_all(self, edges: list[EdgeIn]) -> list[Route]:
        sides = {}
        for e in edges:
            if e.via:
                sides[e.id] = self._sides_via(e)
            else:
                sides[e.id] = self.choose_sides(e)
        ports = self._assign_ports(edges, sides)
        order = sorted(range(len(edges)), key=lambda i: self._span(edges[i], ports))
        routes = {}
        for i in order:
            e = edges[i]
            sa, sb = sides[e.id]
            pa, pb = ports[(e.id, "a")], ports[(e.id, "b")]
            rt = Route(e, [], sa, sb)
            if e.via:
                pts = self.via_path(pa, sa, pb, sb, e.via)
                hit = self._hits(pts, e.a, e.b)
            else:
                r = self.best(pa, sa, pb, sb, e.a, e.b)
                if r is None:  # ports from the straighten step made every shape illegal: retry other sides
                    r = self._fallback(e)
                    if r is not None:
                        rt.side_a, rt.side_b = r[3], r[4]
                if r is None:
                    pts, hit = simplify([pa, (pb[0], pa[1]), pb]), []
                    rt.problems.append(f"edge {e.a}->{e.b}: no legal route found; add 'via' waypoints")
                else:
                    pts, hit = r[1], r[2]
            rt.pts = pts
            for n in hit:
                rt.problems.append(f"edge {e.a}->{e.b} crosses box '{n}'; add 'via' waypoints or set from_side/to_side")
            routes[e.id] = rt
            self.done.append(rt)
        out = [routes[e.id] for e in edges]
        for rt in out:
            self._place_label(rt, out)
        return out

    def _fallback(self, e):
        ra, rb = self.nodes[e.a], self.nodes[e.b]
        best = None
        for sa in ([e.side_a] if e.side_a else OUT):
            for sb in ([e.side_b] if e.side_b else OUT):
                pa, pb = self._trial_ports(ra, sa, rb, sb)
                r = self.best(pa, sa, pb, sb, e.a, e.b)
                if r and (best is None or r[0] < best[0]):
                    best = (*r, sa, sb)
        return best

    def _span(self, e, ports):
        a, b = ports[(e.id, "a")], ports[(e.id, "b")]
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def _sides_via(self, e):
        ra, rb = self.nodes[e.a], self.nodes[e.b]

        def facing(r, target):
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            dx, dy = target[0] - cx, target[1] - cy
            if abs(dx) * (r[3] - r[1]) > abs(dy) * (r[2] - r[0]):
                return "right" if dx > 0 else "left"
            return "bottom" if dy > 0 else "top"

        return (e.side_a or facing(ra, e.via[0]), e.side_b or facing(rb, e.via[-1]))

    def _assign_ports(self, edges, sides):
        by_side = {}
        for e in edges:
            sa, sb = sides[e.id]
            ra, rb = self.nodes[e.a], self.nodes[e.b]
            ta = e.via[0] if e.via else ((rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2)
            tb = e.via[-1] if e.via else ((ra[0] + ra[2]) / 2, (ra[1] + ra[3]) / 2)
            by_side.setdefault((e.a, sa), []).append((e.id, "a", ta))
            by_side.setdefault((e.b, sb), []).append((e.id, "b", tb))
        ports, count = {}, {}
        for (nid, side), items in by_side.items():
            r = self.nodes[nid]
            axis = 0 if side in ("top", "bottom") else 1
            items.sort(key=lambda it: (it[2][axis], it[0]))
            lo, hi = (r[0], r[2]) if axis == 0 else (r[1], r[3])
            ins = min(PORT_INSET, (hi - lo) * 0.22)
            lo, hi = lo + ins, hi - ins
            n = len(items)
            for k, (eid, end, _) in enumerate(items):
                c = (lo + hi) / 2 if n == 1 else lo + (hi - lo) * k / (n - 1)
                if n > 1 and hi - lo < 14 * (n - 1):
                    c = (r[0] + r[2]) / 2 if axis == 0 else (r[1] + r[3]) / 2
                ports[(eid, end)] = (c, side, nid)
                count[(eid, end)] = n
        res = {}
        for (eid, end), (c, side, nid) in ports.items():
            r = self.nodes[nid]
            res[(eid, end)] = (c, r[1] if side == "top" else r[3]) if side in ("top", "bottom") else (r[0] if side == "left" else r[2], c)
        # straighten: a lone port lines up with its partner when the partner coordinate lies on its side
        for e in edges:
            if e.via:
                continue
            sa, sb = sides[e.id]
            if (sa in H_SIDES) != (sb in H_SIDES) or OUT[sa] != tuple(-v for v in OUT[sb]):
                continue
            ax = 1 if sa in H_SIDES else 0  # coordinate to match
            pa, pb = list(res[(e.id, "a")]), list(res[(e.id, "b")])
            ra, rb = self.nodes[e.a], self.nodes[e.b]
            lo_a, hi_a = (ra[1], ra[3]) if ax == 1 else (ra[0], ra[2])
            lo_b, hi_b = (rb[1], rb[3]) if ax == 1 else (rb[0], rb[2])
            lo, hi = max(lo_a, lo_b) + PORT_INSET * 0.6, min(hi_a, hi_b) - PORT_INSET * 0.6
            if lo > hi:
                continue
            na, nb = count[(e.id, "a")], count[(e.id, "b")]
            if na == 1 and nb == 1:
                v = (max(lo, min(hi, (lo_a + hi_a) / 2)) + max(lo, min(hi, (lo_b + hi_b) / 2))) / 2
                v = max(lo, min(hi, v))
            elif na == 1 and lo <= pb[ax] <= hi:
                v = pb[ax]
            elif nb == 1 and lo <= pa[ax] <= hi:
                v = pa[ax]
            else:
                continue
            pa[ax] = pb[ax] = v
            res[(e.id, "a")], res[(e.id, "b")] = tuple(pa), tuple(pb)
        return res

    # ---- labels
    def _place_label(self, rt: Route, all_routes):
        from .core import text_width

        lab = rt.edge.label
        if not lab:
            return
        lines = lab.split("\n")
        lw = max(text_width(l, 11) for l in lines) + 10
        lh = 15 * len(lines) + 3
        best = None
        taken = [r.label_box for r in all_routes if r.label_box]
        others = [sg for r in all_routes if r is not rt for sg in segs(r.pts)]
        order = sorted(range(len(rt.pts) - 1), key=lambda i: -(abs(rt.pts[i][0] - rt.pts[i + 1][0]) + abs(rt.pts[i][1] - rt.pts[i + 1][1])))
        for i in order:
            p, q = rt.pts[i], rt.pts[i + 1]
            seglen = abs(p[0] - q[0]) + abs(p[1] - q[1])
            for t in (0.5, 0.35, 0.65, 0.2, 0.8):
                cx, cy = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                box = (cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2)
                s = 0.0
                horiz = abs(p[1] - q[1]) < 0.05
                need = lw + 8 if horiz else lh + 8
                if seglen < need:
                    s += 300 + (need - seglen)
                s += 1000 * sum(1 for r in self.nodes.values() if _rect_overlap(box, r, 2))
                s += 1000 * sum(1 for b in taken if _rect_overlap(box, b, 2))
                s += 120 * sum(1 for a, b in others if seg_hits(a, b, box, 0))
                s += 40 * sum(1 for j, (a, b) in enumerate(segs(rt.pts)) if j != i and seg_hits(a, b, box, 0))
                s += abs(t - 0.5) * 20
                if best is None or s < best[0]:
                    best = (s, box, (cx, cy))
            if best and best[0] < 1:
                break
        rt.label_box, rt.label_pos = best[1], best[2]
        if best[0] >= 1000:
            rt.problems.append(f"label '{lab}' of edge {rt.edge.a}->{rt.edge.b} overlaps a box or another label")


def _hugs(p, q, z: Rect) -> int:
    """1 if segment p-q runs parallel to a zone border within ZONE_CLEAR (and along it), else 0."""
    if abs(p[1] - q[1]) < 0.05:
        lo, hi = sorted((p[0], q[0]))
        if hi < z[0] or lo > z[2]:
            return 0
        return int(any(abs(p[1] - y) < ZONE_CLEAR for y in (z[1], z[3])) and hi - lo > 2)
    lo, hi = sorted((p[1], q[1]))
    if hi < z[1] or lo > z[3]:
        return 0
    return int(any(abs(p[0] - x) < ZONE_CLEAR for x in (z[0], z[2])) and hi - lo > 2)


def _rect_overlap(a: Rect, b: Rect, m: float = 0) -> bool:
    return a[0] < b[2] + m and a[2] > b[0] - m and a[1] < b[3] + m and a[3] > b[1] - m


def add_jumps(routes: list, r: float = 7.0, samples: int = 8) -> list:
    """Line hops: where a horizontal segment crosses another edge's vertical segment, bend it into a small arc.
    `routes` is a list of point lists (orthogonal); returns new point lists (arcs are polylines)."""
    vert = []  # (route index, x, y0, y1)
    for k, pts in enumerate(routes):
        for p, q in segs(pts):
            if abs(p[0] - q[0]) < 0.05:
                vert.append((k, p[0], min(p[1], q[1]), max(p[1], q[1])))
    out = []
    for k, pts in enumerate(routes):
        new = [pts[0]]
        for p, q in segs(pts):
            if abs(p[1] - q[1]) < 0.05 and abs(p[0] - q[0]) > 4 * r:
                s = 1 if q[0] > p[0] else -1
                xs = sorted((v[1] for v in vert if v[0] != k and v[2] + 2 < p[1] < v[3] - 2
                             and min(p[0], q[0]) + r + 3 < v[1] < max(p[0], q[0]) - r - 3), reverse=(s < 0))
                last = None
                for x in xs:
                    if last is not None and abs(x - last) < 2 * r + 4:
                        continue  # two crossings too close: hop only the first
                    last = x
                    for i in range(samples + 1):
                        t = i / samples
                        import math

                        new.append((x - s * r * math.cos(math.pi * t), p[1] - r * math.sin(math.pi * t)))
            new.append(q)
        out.append([(round(a, 1), round(b, 1)) for a, b in new])
    return out
