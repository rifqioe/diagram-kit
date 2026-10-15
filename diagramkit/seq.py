"""Sequence diagrams from a spec (participants + steps: msg, note, divider, frame)."""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path

from .core import (Diagram, SpecError, arrow_el, base, block_width, box_with_text, get_theme, need, text_el, text_width,
                   wrap_text)

_MSG = re.compile(r"^\s*([\w.\-]+?)\s*(-->|->)\s*([\w.\-]+)\s*:\s*(.*)$", re.S)


def wrap_to(text: str, maxw: float, fs: float) -> str:
    """Greedy word wrap each line of `text` to at most `maxw` px; explicit newlines are kept."""
    out = []
    for line in text.split("\n"):
        cur = ""
        for word in line.split(" "):
            t = (cur + " " + word).strip() if cur else word
            if cur and text_width(t, fs) > maxw:
                out.append(cur)
                cur = word
            else:
                cur = t
        out.append(cur)
    return "\n".join(out)


class Seq:
    """Layout engine. Call divider/msg/note/frame_start/frame_end in order, then build()."""

    def __init__(self, title, subtitle, parts, theme, gap=235):
        self.title, self.subtitle, self.parts, self.theme, self.gap = title, subtitle, parts, theme, gap
        self.ids = [p[0] for p in parts]
        self.x0 = 60 + gap / 2
        self.xs = {p[0]: self.x0 + i * gap for i, p in enumerate(parts)}
        self.y = 170
        self.groups, self.edges, self.nodes, self.labels = [], [], [], []
        self.n = 0
        self.frames = []
        self.inset = {}  # frame id -> extra horizontal padding for nested frames
        self.note_boxes = []  # (y, x1, x2) of every note, so frames can grow to contain them
        self.last = None  # kind of the previous step: 'msg', 'note' or None
        self.note_bottom = 0

    def _id(self, p):
        self.n += 1
        return f"{p}{self.n}"

    def _x(self, pid):
        if pid not in self.xs:
            raise SpecError(f"unknown participant '{pid}' (known: {', '.join(self.ids)})")
        return self.xs[pid]

    @property
    def W(self):
        return self.x0 * 2 + self.gap * (len(self.parts) - 1)

    def divider(self, text):
        th, i = self.theme, self._id("dv")
        self.last = None
        self.groups.append(base("rectangle", "dvr-" + i, 30, self.y, self.W - 60, 26, backgroundColor=th.divider_bg,
                                strokeColor="transparent"))
        self.labels.append(text_el("dvt-" + i, 40, self.y + 4, text, 13, color=th.divider_text, align="left",
                                   w=text_width(text, 13) + 6, h=18))
        self.y += 52

    def msg(self, a, b, label, dashed=False):
        th, i = self.theme, self._id("m")
        xa, xb, y = self._x(a), self._x(b), self.y
        span = max(abs(self.ids.index(a) - self.ids.index(b)), 1)
        label = wrap_to(label, span * self.gap - 36 if a != b else 170, 11)
        lines = label.split("\n")
        lw = block_width(label, 11) + 12
        lh = 15 * len(lines) + 2
        if self.last == "note":  # the label sits above the arrow; keep it clear of the note above
            self.y = max(self.y, self.note_bottom + lh + 9)
            y = self.y
        self.last = "msg"
        if a == b:  # self message: small loop to the right
            pts = [(xa, y), (xa + 46, y), (xa + 46, y + 22), (xa, y + 22)]
            self.edges.append(arrow_el("e-" + i, pts, th.edge, dashed=dashed))
            lx = xa + 52
            self.labels.append(base("rectangle", "lb-" + i, lx - 2, y - 2, lw, lh, backgroundColor=th.bg, strokeColor="transparent"))
            self.labels.append(text_el("el-" + i, lx, y - 1, label, 11, color=th.msg_text, align="left", w=lw - 8, h=lh))
            self.y += 22 + 15 * len(lines) + 18
            return
        self.edges.append(arrow_el("e-" + i, [(xa, y), (xb, y)], th.edge, dashed=dashed))
        cx = (xa + xb) / 2
        self.labels.append(base("rectangle", "lb-" + i, cx - lw / 2, y - lh - 3, lw, lh, backgroundColor=th.bg, strokeColor="transparent"))
        self.labels.append(text_el("el-" + i, cx - lw / 2, y - lh - 2, label, 11, color=th.msg_text, w=lw, h=lh))
        self.y += 18 + 15 * len(lines) + 14

    def note(self, over, text, color="yellow", width=None):
        th, i = self.theme, self._id("nt")
        over = over if isinstance(over, (list, tuple)) else [over]
        xs = [self._x(o) for o in over]
        cx = sum(xs) / len(xs)
        lines = text.split("\n")
        w = width or max(210, block_width(text, 11) + 28, (max(xs) - min(xs)) + 60)
        h = 18 + 15 * len(lines)
        if self.last == "msg":  # a message already leaves a trailing gap; pull the note up into it
            self.y -= 10
        self.last = "note"
        self.note_boxes.append((self.y, cx - w / 2, cx + w / 2))
        self.note_bottom = self.y + h
        fill, stroke = th.color(color)
        self.nodes += box_with_text(i, cx - w / 2, self.y, w, h, text, fill, stroke, fs=11, text_color=th.text, stroke_w=1,
                                    prefix="n-", tprefix="t-")
        self.y += h + 22

    def frame_start(self, label, over, color="gray", levels=1):
        self.last = None
        self.y += 6
        self.frames.append((label, over, color, self.y, levels))
        self.y += 46

    def frame_end(self):
        th = self.theme
        label, over, color, y0, levels = self.frames.pop()
        xs = [self._x(o) for o in over]
        pad = min(140, self.gap * 0.5 - 8) + 10 * (levels - 1)
        x1, x2 = min(xs) - pad, max(xs) + pad
        y2 = self.y - 6
        for ny, nx1, nx2 in self.note_boxes:  # grow the frame so notes never stick out of it
            if y0 <= ny < y2:
                x1, x2 = min(x1, nx1 - 12), max(x2, nx2 + 12)
        self.last = None
        i = self._id("fr")
        stroke = th.color(color)[1]
        self.groups.append(base("rectangle", "g-" + i, x1, y0, x2 - x1, y2 - y0, strokeColor=stroke, strokeStyle="dashed",
                                roundness={"type": 3}))
        lw = text_width(label, 12) + 10  # white plate so lifelines do not strike through the label
        self.labels.append(base("rectangle", "glb-" + i, x1 + 8, y0 + 5, lw, 20, backgroundColor=th.bg, strokeColor="transparent"))
        self.labels.append(text_el("gl-" + i, x1 + 10, y0 + 6, label, 12, color=stroke, align="left",
                                   w=text_width(label, 12) + 6, h=18))
        self.y += 18

    def build(self, name) -> Diagram:
        th = self.theme
        top, bottom = 90, self.y + 10
        nodes, edges = [], []
        bw = min(200, self.gap - 20)
        for pid, label, color in self.parts:
            x = self.xs[pid]
            fill, stroke = th.color(color)
            nodes += box_with_text("hd-" + pid, x - bw / 2, top, bw, 56, wrap_to(label, bw - 16, 13), fill, stroke, fs=13,
                                   text_color=th.text, gid="grp-" + pid)
            edges.append(arrow_el("ll-" + pid, [(x, top + 56), (x, bottom)], th.lifeline, dashed=True, head="none", width=1))
        W, H = self.W, int(bottom + 40)
        labels = list(self.labels)
        labels.append(text_el("title", 0, 10, self.title, 20, color=th.text, w=W, h=28))
        if self.subtitle:
            labels.append(text_el("sub", 0, 44, self.subtitle, 12, color=th.subtext, w=W, h=18))
        els = self.groups + edges + self.edges + nodes + self.nodes + labels
        return Diagram(name, els, W, H, th)


# ----------------------------------------------------------------------------- spec -> Seq
def _parse_msg(step, where):
    v = step.get("msg", step.get("message"))
    if isinstance(v, str):
        m = _MSG.match(v)
        if not m:
            raise SpecError(f"{where}: msg must look like 'a->b: label' or 'a-->b: label' (dashed), got {v!r}")
        return m.group(1), m.group(3), wrap_text(m.group(4).strip()), m.group(2) == "-->"
    if isinstance(v, dict):
        return (need(v, "from", where), need(v, "to", where), wrap_text(v.get("label", "")), bool(v.get("dashed", False)))
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return v[0], v[1], wrap_text(v[2]), bool(v[3]) if len(v) > 3 else False
    raise SpecError(f"{where}: msg must be a string, mapping or [from, to, label]")


def _norm(steps):
    return [{"msg": s} if isinstance(s, str) else s for s in steps]


def _used(steps):
    out = []
    for s in _norm(steps):
        if "msg" in s or "message" in s:
            a, b, _, _ = _parse_msg(s, "msg")
            out += [a, b]
        elif "note" in s:
            o = s.get("over")
            out += o if isinstance(o, list) else [o]
        elif "frame" in s:
            out += _used(s.get("steps", []))
    return out


def _levels(steps):
    return 1 + max([_levels(s.get("steps", [])) for s in _norm(steps) if "frame" in s] or [0])


def _auto_gap(parts, steps, order):
    need_w = 220.0
    for _, label, _ in parts:
        need_w = max(need_w, block_width(label, 13) + 60)

    def walk(ss):
        nonlocal need_w
        for s in _norm(ss):
            if "msg" in s or "message" in s:
                a, b, label, _ = _parse_msg(s, "msg")
                if a in order and b in order and a != b:
                    span = abs(order.index(a) - order.index(b))
                    need_w = max(need_w, (block_width(label, 11) + 40) / span)
            elif "frame" in s:
                walk(s.get("steps", []))

    walk(steps)
    return min(need_w, 420)


def _emit(seq: Seq, steps, where, depth_guard=0):
    for k, s in enumerate(steps):
        w = f"{where}[{k}]"
        if isinstance(s, str):  # bare string = msg shorthand
            s = {"msg": s}
        if not isinstance(s, dict):
            raise SpecError(f"{w}: step must be a mapping or an 'a->b: label' string")
        if "divider" in s:
            seq.divider(str(s["divider"]))
        elif "msg" in s or "message" in s:
            a, b, label, dashed = _parse_msg(s, w)
            if "dashed" in s:
                dashed = bool(s["dashed"])
            seq.msg(a, b, label, dashed)
        elif "note" in s:
            over = need(s, "over", w)
            seq.note(over, wrap_text(s["note"]), s.get("color", "yellow"), s.get("width"))
        elif "frame" in s:
            inner = s.get("steps", [])
            over = s.get("over") or sorted(set(_used(inner)), key=seq.ids.index)
            if not over:
                raise SpecError(f"{w}: frame has no 'over' and no participants inside")
            seq.frame_start(str(s["frame"]), over, s.get("color", "gray"), _levels(inner))
            _emit(seq, inner, w + ".steps")
            seq.frame_end()
        else:
            raise SpecError(f"{w}: unknown step; expected one of divider, msg, note, frame (got keys {list(s)})")


def build(spec: dict, name: str = "sequence", theme=None, base_dir=".", orientation=None) -> Diagram:
    spec = copy.deepcopy(spec)
    src = {"kind": "seq", "spec": copy.deepcopy(spec), "base_dir": str(Path(base_dir).resolve())}
    orientation = orientation or spec.get("orientation")
    if orientation not in (None, "auto", "landscape", "portrait"):
        raise SpecError("orientation must be landscape, portrait or auto")
    if spec.get("gap") or orientation in (None, "auto"):
        d = _build(spec, name, theme, spec.get("gap"))
    else:
        # sequence diagrams grow downward; orientation changes the lane spacing until the aspect ratio fits
        target = 1.5 if orientation == "landscape" else 0.75
        parts = _participants(spec)
        base_gap = _auto_gap(parts, spec.get("steps") or [], [p[0] for p in parts])
        lo = 150
        hi = 380
        cands = [base_gap] + list(range(hi, lo - 1, -10)) if orientation == "landscape" else [base_gap] + list(range(lo, 380, 10))
        d, best = None, None
        for g in sorted(set(cands)):
            dd = _build(spec, name, theme, g)
            cost = abs(math.log(dd.width / dd.height / target))
            if best is None or cost < best - 1e-9:
                d, best = dd, cost
    d.source = src
    return d


def _participants(spec):
    raw = need(spec, "participants", "spec")
    parts = []
    for k, p in enumerate(raw):
        if isinstance(p, str):
            p = {"id": p, "label": p}
        pid = str(need(p, "id", f"participants[{k}]"))
        parts.append((pid, wrap_text(p.get("label", pid)), p.get("color", "blue")))
    if len({p[0] for p in parts}) != len(parts):
        raise SpecError("participants: duplicate id")
    return parts


def _build(spec, name, theme, gap) -> Diagram:
    th = get_theme(theme if theme is not None else spec.get("theme"))
    parts = _participants(spec)
    steps = need(spec, "steps", "spec")
    order = [p[0] for p in parts]
    title = wrap_text(spec.get("title", ""))
    gap = gap or _auto_gap(parts, steps, order)
    seq = Seq(title, wrap_text(spec.get("subtitle", "")), parts, th, gap=gap)
    # widen so a long title fits; keep lifelines centered
    need_w = max(block_width(title, 20), block_width(spec.get("subtitle", "") or "", 12)) + 80
    if need_w > seq.W:
        seq.x0 += (need_w - seq.W) / 2
        seq.xs = {p[0]: seq.x0 + i * gap for i, p in enumerate(parts)}
    _emit(seq, steps, "steps")
    if seq.frames:
        raise SpecError("unbalanced frames")
    return seq.build(name)
