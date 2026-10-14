---
name: diagramkit
description: Generate sequence diagrams and HLD / architecture diagrams from a JSON or YAML spec, output as .excalidraw, .svg, .png and .drawio. Use when the user asks for a sequence diagram, flow between services, HLD, architecture diagram, or a draw.io / Excalidraw file from a description.
---

# diagramkit

CLI: `diagramkit seq|hld spec.yaml -o out/` and `diagramkit drawio file.excalidraw`.
Install once: `pip install <path to this repo>` (or `python -m diagramkit` from the repo root with deps installed).

## Workflow

1. Write a spec file (YAML or JSON). Full format: see `README.md`. Examples: `examples/*.yaml|json`.
2. Run `diagramkit seq spec.yaml -o out/` (sequence) or `diagramkit hld spec.yaml -o out/` (architecture). Add `--strict`
   to fail on warnings.
3. **Look at the PNG** (read the image) and fix the spec until it is tidy. Print warnings are real problems:
   - `crosses box` / `no legal route`: set `from_side`/`to_side` on the edge, add `via: [[x, y], ...]`,
     or move nodes (`row`/`col`, `colspan`) so connected nodes are neighbours.
   - `label ... overlaps`: shorten the label or increase `layout.node_gap_x/node_gap_y`.
4. Page shape: add `-r portrait` or `-r landscape` to `seq`/`hld`, or flip an existing diagram with
   `diagramkit convert out/x.excalidraw portrait`.
5. Give the user the files from `out/` (`.excalidraw` opens in excalidraw.com, `.drawio` in diagrams.net).

## Spec cheat sheet

Sequence: `participants` (id, label, color) + `steps`:
`"a->b: label"` solid, `"a-->b: label"` dashed, `{divider: "..."}`, `{note: "...", over: [a,b], color: yellow}`,
`{frame: "alt  label", steps: [...]}` (nestable). Self message: `a->a`.

HLD: `zones` (id, label, color, row, col, cols, frame) + `nodes` (id, zone, label, color, icon, dashed, colspan, row, col)
+ `edges` (`"a->b: label"` or `{from,to,label,dashed,arrow,from_side,to_side,via}`) + optional `legend`.

HLD options: `jumps: arc|none` (line hops at crossings, default arc), `jump_size`, `orientation`.

Colors: blue, green, orange, purple, gray, yellow, red. Themes: `-t default|mono|dark`.

## Rules of thumb

- Use neutral, generic names unless the user supplies real ones. Never invent customer or company names.
- One role per color (e.g. blue = existing, green = new, purple = data, orange = devices/clients, gray = external).
- Keep labels short (2-4 words) on edges; put detail in notes (sequence) or node text (HLD).
- Icons: use `icon: builtin:<name>` (see `diagramkit icons`) for generic pictograms. Real logos: `icon: path/to/logo.svg` or a URL; `examples/logos/` has five sample logos (see NOTICE.md). Do not bundle new brand logos into the package without the user's say-so.
- PNG needs `resvg-py` (installed with the package) or `cairosvg`.
