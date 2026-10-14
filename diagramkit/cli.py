"""Command line: diagramkit seq|hld|drawio."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import ALL_FORMATS, SpecError, default_name, load_spec, write_outputs


def _formats(s: str):
    fm = tuple(x.strip() for x in s.split(",") if x.strip())
    bad = [f for f in fm if f not in ALL_FORMATS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown format {bad}; choose from {', '.join(ALL_FORMATS)}")
    return fm


def _render(kind: str, a) -> int:
    import importlib

    spec = load_spec(a.spec)
    name = a.name or default_name(spec, a.spec)
    mod = importlib.import_module(f".{kind}", __package__)
    d = mod.build(spec, name, theme=a.theme, base_dir=Path(a.spec).resolve().parent, orientation=a.orientation)
    return _emit(d, a)


def _emit(d, a) -> int:
    written = write_outputs(d, a.out, a.formats, a.scale)
    for p in written:
        print("wrote", p)
    for w in d.warnings:
        print("warning:", w, file=sys.stderr)
    if a.strict and d.warnings:
        return 2
    return 0


def _convert(a) -> int:
    """Re-lay out a diagramkit .excalidraw in another orientation, using the spec embedded in the file."""
    import importlib
    import json

    p = Path(a.file)
    scene = json.loads(p.read_text(encoding="utf-8"))
    src = scene.get("diagramkit")
    if not src or src.get("kind") not in ("seq", "hld"):
        raise SpecError(f"{p}: no embedded spec (only files written by diagramkit >= 0.2 can be converted); "
                        "re-render from the original spec with --orientation instead")
    mod = importlib.import_module(f".{src['kind']}", __package__)
    base = p.stem + "-" + a.orientation
    d = mod.build(src["spec"], a.name or base, theme=a.theme, base_dir=src.get("base_dir", "."), orientation=a.orientation)
    return _emit(d, a)


def _icons(a) -> int:
    from .core import list_icons

    print("builtin icons (use as  icon: builtin:<name>):")
    print("  " + ", ".join(list_icons()))
    return 0


def _drawio(a) -> int:
    from . import drawio

    rc = 0
    for f in a.files:
        out = drawio.convert_file(f, a.output if len(a.files) == 1 else None)
        problems = drawio.validate(Path(out).read_text(encoding="utf-8"))
        print("wrote", out)
        for pr in problems:
            print("invalid:", pr, file=sys.stderr)
            rc = 1
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="diagramkit", description="Sequence and HLD diagrams from JSON/YAML specs.")
    ap.add_argument("--version", action="version", version=f"diagramkit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for kind, helptext in (("seq", "sequence diagram from a spec"), ("hld", "HLD / architecture diagram from a spec")):
        p = sub.add_parser(kind, help=helptext)
        p.add_argument("spec", help="spec file (.json, .yaml, .yml)")
        p.add_argument("-o", "--out", default="out", help="output directory (default: out)")
        p.add_argument("-n", "--name", help="output base name (default: spec 'name' or file stem)")
        p.add_argument("-f", "--formats", type=_formats, default=ALL_FORMATS,
                       help="comma list of excalidraw,svg,png,drawio (default: all)")
        p.add_argument("-t", "--theme", help="default | mono | dark (overrides spec)")
        p.add_argument("-r", "--orientation", choices=("landscape", "portrait", "auto"),
                       help="target page shape; hld re-flows/transposes zones, seq adjusts lane spacing (default: as written)")
        p.add_argument("--scale", type=float, default=2.0, help="PNG scale factor (default 2)")
        p.add_argument("--strict", action="store_true", help="exit 2 when there are warnings (routing collisions, icons, PNG)")
    p = sub.add_parser("convert", help="re-lay out a diagramkit .excalidraw as landscape or portrait (uses the embedded spec)")
    p.add_argument("file")
    p.add_argument("orientation", choices=("landscape", "portrait"))
    p.add_argument("-o", "--out", default="out", help="output directory (default: out)")
    p.add_argument("-n", "--name", help="output base name (default: <file>-<orientation>)")
    p.add_argument("-f", "--formats", type=_formats, default=ALL_FORMATS)
    p.add_argument("-t", "--theme")
    p.add_argument("--scale", type=float, default=2.0)
    p.add_argument("--strict", action="store_true")
    sub.add_parser("icons", help="list builtin icons")
    p = sub.add_parser("drawio", help="convert .excalidraw file(s) to .drawio")
    p.add_argument("files", nargs="+")
    p.add_argument("-o", "--output", help="output path (single input only)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "drawio":
            return _drawio(a)
        if a.cmd == "convert":
            return _convert(a)
        if a.cmd == "icons":
            return _icons(a)
        return _render(a.cmd, a)
    except SpecError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    except FileNotFoundError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
