"""Shared pieces: themes, text metrics, Excalidraw element builders, SVG writer, PNG rendering, icons, spec loading."""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

FONT_STACK = "Helvetica, Arial, 'Liberation Sans', 'DejaVu Sans', sans-serif"
ALL_FORMATS = ("excalidraw", "svg", "png", "drawio")


class SpecError(ValueError):
    """Raised for invalid user specs. Message is meant to be shown as-is."""


# --------------------------------------------------------------------------- themes
def _mix(hex_color: str, other: str, t: float) -> str:
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


@dataclass
class Theme:
    name: str
    bg: str = "#ffffff"
    text: str = "#1e1e1e"
    subtext: str = "#555555"
    edge: str = "#444444"
    lifeline: str = "#9ca3af"
    divider_bg: str = "#f3f4f6"
    divider_text: str = "#374151"
    msg_text: str = "#222222"
    colors: dict = field(default_factory=dict)  # name -> (fill, stroke)

    def color(self, c) -> tuple[str, str]:
        """Resolve a color spec: palette name, '#rrggbb' (stroke; fill derived), or [fill, stroke]."""
        if c is None:
            return self.colors["gray"]
        if isinstance(c, (list, tuple)) and len(c) == 2:
            return str(c[0]), str(c[1])
        if isinstance(c, dict):
            return str(c["fill"]), str(c["stroke"])
        if isinstance(c, str):
            if c in self.colors:
                return self.colors[c]
            if re.fullmatch(r"#[0-9a-fA-F]{6}", c):
                return _mix(c, self.bg, 0.85), c
        raise SpecError(f"unknown color {c!r}; use one of {sorted(self.colors)}, '#rrggbb', or [fill, stroke]")


# Default palette = blue / green / orange / purple / gray (+ yellow for notes, red for alerts).
_DEFAULT = {
    "blue": ("#dbeafe", "#2563eb"), "green": ("#dcfce7", "#16a34a"), "orange": ("#ffedd5", "#ea580c"),
    "purple": ("#ede9fe", "#7c3aed"), "gray": ("#e5e7eb", "#6b7280"), "yellow": ("#fef9c3", "#ca8a04"),
    "red": ("#fee2e2", "#dc2626"),
}
# Monochrome: print friendly, tones separate the roles.
_MONO = {
    "blue": ("#ffffff", "#111111"), "green": ("#f3f4f6", "#111111"), "orange": ("#e5e7eb", "#111111"),
    "purple": ("#d1d5db", "#111111"), "gray": ("#f9fafb", "#6b7280"), "yellow": ("#ffffff", "#6b7280"),
    "red": ("#9ca3af", "#111111"),
}
_DARK = {
    "blue": ("#1e3a5f", "#60a5fa"), "green": ("#14532d", "#4ade80"), "orange": ("#7c2d12", "#fb923c"),
    "purple": ("#4c1d95", "#a78bfa"), "gray": ("#374151", "#9ca3af"), "yellow": ("#713f12", "#facc15"),
    "red": ("#7f1d1d", "#f87171"),
}

THEMES = {
    "default": Theme("default", colors=_DEFAULT),
    "mono": Theme("mono", edge="#222222", lifeline="#9ca3af", divider_bg="#e5e7eb", divider_text="#111111",
                  text="#111111", subtext="#444444", msg_text="#111111", colors=_MONO),
    "dark": Theme("dark", bg="#111827", text="#f3f4f6", subtext="#9ca3af", edge="#d1d5db", lifeline="#6b7280",
                  divider_bg="#1f2937", divider_text="#e5e7eb", msg_text="#f3f4f6", colors=_DARK),
}


def get_theme(spec) -> Theme:
    """`spec` is a theme name, or a dict: {base: default|mono|dark, bg:, text:, colors: {name: [fill, stroke]}}."""
    if spec is None:
        spec = "default"
    if isinstance(spec, str):
        if spec not in THEMES:
            raise SpecError(f"unknown theme {spec!r}; built-in: {', '.join(THEMES)}")
        return THEMES[spec]
    if isinstance(spec, dict):
        b = THEMES[spec.get("base", "default")]
        t = Theme(**{**b.__dict__, "colors": dict(b.colors)})
        for k, v in spec.items():
            if k == "colors":
                for n, fs in v.items():
                    t.colors[n] = (str(fs[0]), str(fs[1]))
            elif k != "base" and hasattr(t, k):
                setattr(t, k, v)
        return t
    raise SpecError("theme must be a name or a mapping")


# --------------------------------------------------------------------------- text metrics
_NARROW = set("il.,:;|!'`jtfr()[]/ I")
_WIDE = set("mwMW@%")


def text_width(s: str, fs: float) -> float:
    """Approximate rendered width (Helvetica-like) without needing font files."""
    w = 0.0
    for ch in s:
        if ch in _NARROW:
            w += 0.3
        elif ch in _WIDE:
            w += 0.85
        elif ch.isupper():
            w += 0.66
        elif ch.isdigit():
            w += 0.56
        else:
            w += 0.52
    return w * fs


def block_width(text: str, fs: float) -> float:
    return max(text_width(l, fs) for l in text.split("\n"))


# --------------------------------------------------------------------------- element builders
def base(t, i, x, y, w, h, **kw):
    e = dict(type=t, id=i, x=x, y=y, width=w, height=h, angle=0, strokeColor="#1e1e1e", backgroundColor="transparent",
             fillStyle="solid", strokeWidth=1, strokeStyle="solid", roughness=0, opacity=100, groupIds=[], frameId=None,
             roundness=None, seed=1, version=1, versionNonce=1, isDeleted=False, boundElements=None, updated=1, link=None,
             locked=False)
    e.update(kw)
    return e


def text_el(i, x, y, text, fs, color="#1e1e1e", align="center", container=None, w=None, h=None):
    w = w if w is not None else block_width(text, fs) + 4
    h = h if h is not None else len(text.split("\n")) * fs * 1.25
    return base("text", i, x, y, w, h, text=text, fontSize=fs, fontFamily=2, textAlign=align,
                verticalAlign="middle" if container else "top", containerId=container, originalText=text,
                autoResize=True, lineHeight=1.25, strokeColor=color)


def box_with_text(nid, x, y, w, h, label, fill, stroke, *, fs=13, text_color="#1e1e1e", stroke_w=2, dashed=False,
                  text_x=None, text_w=None, align="center", prefix="n-", tprefix="t-", gid=None):
    """Rounded rectangle + bound text (+ shared group id). Returns [rect, text]."""
    gid = [gid or "grp-" + nid]
    r = base("rectangle", prefix + nid, x, y, w, h, backgroundColor=fill, strokeColor=stroke, strokeWidth=stroke_w,
             strokeStyle="dashed" if dashed else "solid", roundness={"type": 3}, groupIds=gid,
             boundElements=[{"id": tprefix + nid, "type": "text"}])
    t = text_el(tprefix + nid, text_x if text_x is not None else x, y, label, fs, color=text_color, align=align,
                container=prefix + nid, w=text_w if text_w is not None else w, h=h)
    t["groupIds"] = gid
    return [r, t]


def arrow_el(aid, pts, color, *, dashed=False, head="end", width=2):
    ox, oy = pts[0]
    rel = [[round(p[0] - ox, 1), round(p[1] - oy, 1)] for p in pts]
    return base("arrow", aid, ox, oy, max(abs(p[0]) for p in rel), max(abs(p[1]) for p in rel), points=rel,
                strokeColor=color, strokeWidth=width, strokeStyle="dashed" if dashed else "solid", startBinding=None,
                endBinding=None, startArrowhead="arrow" if head == "both" else None,
                endArrowhead="arrow" if head in ("end", "both") else None, lastCommittedPoint=None, elbowed=False,
                roundness=None)


@dataclass
class Diagram:
    name: str
    elements: list
    width: float
    height: float
    theme: Theme
    files: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def scene(self) -> dict:
        return dict(type="excalidraw", version=2, source="diagramkit", elements=self.elements,
                    appState={"viewBackgroundColor": self.theme.bg, "gridSize": None}, files=self.files)


# --------------------------------------------------------------------------- icons (optional, user supplied)
def load_icon(src: str, base_dir: str | Path = ".", timeout: int = 10):
    """Return (mime, data_url) for a local path or http(s) URL. Raises OSError/ValueError on failure."""
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "diagramkit"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(5_000_000)
            mt = (r.headers.get_content_type() or "").lower()
        if mt in ("", "application/octet-stream", "text/plain"):
            mt = mimetypes.guess_type(src.split("?")[0])[0] or "image/png"
    else:
        p = Path(src)
        if not p.is_absolute():
            p = Path(base_dir) / p
        raw = p.read_bytes()
        mt = mimetypes.guess_type(str(p))[0] or ("image/svg+xml" if p.suffix.lower() == ".svg" else "image/png")
    if mt == "image/svg+xml":
        t = raw.decode("utf-8", "replace").replace('width="1em"', 'width="64"').replace('height="1em"', 'height="64"')
        raw = t.encode()
    elif not mt.startswith("image/"):
        raise ValueError(f"not an image: {src} ({mt})")
    return mt, f"data:{mt};base64,{base64.b64encode(raw).decode()}"


def register_icon(files: dict, src: str, base_dir, warnings: list):
    """Load icon into the Excalidraw `files` map; returns fileId or None (and a warning) on failure."""
    try:
        mt, du = load_icon(src, base_dir)
    except Exception as ex:  # noqa: BLE001 - user supplied path/URL: never crash the render
        warnings.append(f"icon skipped ({src}): {ex}")
        return None
    fid = hashlib.sha1(du.encode()).hexdigest()[:16]
    files[fid] = dict(mimeType=mt, id=fid, dataURL=du, created=1)
    return fid


# --------------------------------------------------------------------------- SVG writer
def to_svg(d: Diagram) -> str:
    W, H = d.width, d.height
    colors = sorted({e["strokeColor"] for e in d.elements if e["type"] == "arrow" and e.get("endArrowhead")})
    marks = "".join(
        f'<marker id="ah{i}" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="userSpaceOnUse">'
        f'<path d="M0,0 L10,4 L0,8 z" fill="{c}"/></marker>' for i, c in enumerate(colors))
    mk = {c: i for i, c in enumerate(colors)}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 0 {W:.0f} {H:.0f}">',
         f'<rect width="100%" height="100%" fill="{d.theme.bg}"/>', f"<defs>{marks}</defs>"]
    for e in d.elements:
        t = e["type"]
        if t == "rectangle":
            dash = ' stroke-dasharray="8 5"' if e["strokeStyle"] == "dashed" else ""
            rx = 10 if e.get("roundness") else 0
            fill = e["backgroundColor"] if e["backgroundColor"] != "transparent" else "none"
            stroke = e["strokeColor"] if e["strokeColor"] != "transparent" else "none"
            sw = 1.5 if e["strokeWidth"] > 1 else 1
            o.append(f'<rect x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["width"]:.1f}" height="{e["height"]:.1f}" rx="{rx}" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>')
        elif t == "arrow":
            pts = " ".join(f'{e["x"] + p[0]:.1f},{e["y"] + p[1]:.1f}' for p in e["points"])
            dash = ' stroke-dasharray="6 4"' if e["strokeStyle"] == "dashed" else ""
            m = f' marker-end="url(#ah{mk[e["strokeColor"]]})"' if e.get("endArrowhead") else ""
            ms = ""
            if e.get("startArrowhead"):
                ms = f' marker-start="url(#ah{mk.get(e["strokeColor"], 0)})"'
            sw = 1.5 if e["strokeWidth"] > 1 else 1
            o.append(f'<polyline points="{pts}" fill="none" stroke="{e["strokeColor"]}" stroke-width="{sw}"{dash}{m}{ms}/>')
        elif t == "image":
            f = d.files.get(e["fileId"])
            if f:
                o.append(f'<image x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["width"]:.1f}" height="{e["height"]:.1f}" '
                         f'preserveAspectRatio="xMidYMid meet" href="{f["dataURL"]}" xlink:href="{f["dataURL"]}"/>')
        elif t == "text":
            lines = e["text"].split("\n")
            fs = e["fontSize"]
            lh = fs * 1.25
            al = e["textAlign"]
            ax = {"left": e["x"], "center": e["x"] + e["width"] / 2, "right": e["x"] + e["width"]}[al]
            anchor = {"left": "start", "center": "middle", "right": "end"}[al]
            if e.get("containerId"):
                y0 = e["y"] + (e["height"] - len(lines) * lh) / 2 + fs * 0.95
            else:
                y0 = e["y"] + fs * 0.95
            ts = "".join(f'<tspan x="{ax:.1f}" dy="{0 if i == 0 else lh:.1f}">{escape(l)}</tspan>' for i, l in enumerate(lines))
            o.append(f'<text y="{y0:.1f}" font-family="{FONT_STACK}" font-size="{fs}" fill="{e["strokeColor"]}" '
                     f'text-anchor="{anchor}">{ts}</text>')
    o.append("</svg>")
    return "\n".join(o)


# --------------------------------------------------------------------------- PNG
def svg_to_png(svg: str, out_path: str | Path, scale: float = 2.0, bg: str = "#ffffff") -> str:
    """Render SVG to PNG. Order: resvg-py, cairosvg, optional node+sharp (env DIAGRAMKIT_SHARP=<path to sharp>).
    Returns the backend name; raises RuntimeError if none works."""
    errors = []
    try:
        import resvg_py  # type: ignore

        png = resvg_py.svg_to_bytes(svg_string=svg, zoom=scale, background=bg)
        Path(out_path).write_bytes(bytes(png))
        return "resvg"
    except Exception as ex:  # noqa: BLE001
        errors.append(f"resvg-py: {ex}")
    try:
        import cairosvg  # type: ignore

        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out_path), scale=scale, background_color=bg)
        return "cairosvg"
    except Exception as ex:  # noqa: BLE001
        errors.append(f"cairosvg: {str(ex).splitlines()[0] if str(ex) else type(ex).__name__}")
    sharp, node = os.environ.get("DIAGRAMKIT_SHARP"), shutil.which("node")
    if sharp and node:
        try:
            with tempfile.TemporaryDirectory() as td:
                sp = Path(td) / "in.svg"
                sp.write_text(svg, encoding="utf-8")
                js = (f'import sharp from {json.dumps(Path(sharp).as_uri() if os.path.isabs(sharp) else sharp)};'
                      f'import fs from "fs";await sharp(fs.readFileSync({json.dumps(str(sp))}),{{density:{int(96 * scale)}}})'
                      f'.png().toFile({json.dumps(str(out_path))});')
                jp = Path(td) / "r.mjs"
                jp.write_text(js)
                subprocess.run([node, str(jp)], check=True, capture_output=True)
            return "node-sharp"
        except Exception as ex:  # noqa: BLE001
            errors.append(f"node-sharp: {ex}")
    raise RuntimeError("PNG backend unavailable (pip install resvg-py  or  pip install cairosvg). " + " | ".join(errors))


# --------------------------------------------------------------------------- outputs + spec IO
def write_outputs(d: Diagram, outdir: str | Path, formats=ALL_FORMATS, scale: float = 2.0) -> list[Path]:
    from . import drawio  # local import: drawio imports core

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    scene = d.scene()
    svg = None
    if "excalidraw" in formats:
        p = out / f"{d.name}.excalidraw"
        p.write_text(json.dumps(scene), encoding="utf-8")
        written.append(p)
    if "svg" in formats or "png" in formats:
        svg = to_svg(d)
    if "svg" in formats:
        p = out / f"{d.name}.svg"
        p.write_text(svg, encoding="utf-8")
        written.append(p)
    if "png" in formats:
        p = out / f"{d.name}.png"
        try:
            svg_to_png(svg, p, scale, d.theme.bg)
            written.append(p)
        except RuntimeError as ex:
            d.warnings.append(f"png skipped: {ex}")
    if "drawio" in formats:
        p = out / f"{d.name}.drawio"
        p.write_text(drawio.convert_scene(scene), encoding="utf-8")
        written.append(p)
    return written


def load_spec(path: str | Path) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        if p.suffix.lower() == ".json":
            spec = json.loads(text)
        else:
            import yaml

            spec = yaml.safe_load(text)
    except Exception as ex:  # noqa: BLE001
        raise SpecError(f"cannot parse {p}: {ex}") from ex
    if not isinstance(spec, dict):
        raise SpecError(f"{p}: top level must be a mapping")
    return spec


def default_name(spec: dict, path: str | Path) -> str:
    n = spec.get("name") or Path(path).name.split(".")[0]
    return re.sub(r"[^\w.-]+", "-", str(n)).strip("-") or "diagram"


def need(d: dict, key: str, where: str):
    if key not in d or d[key] in (None, ""):
        raise SpecError(f"{where}: missing required key '{key}'")
    return d[key]


def wrap_text(s: str) -> str:
    return str(s).replace("\\n", "\n")
