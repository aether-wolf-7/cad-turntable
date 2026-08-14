# cad-turntable

Turns a STEP/CAD assembly into a photoreal 360° spin viewer with occlusion-aware
hotspots and a self-contained product page.

Built for industrial equipment manufacturers who have CAD but no product video.
A camera can only film a machine with its covers on. CAD gives you exploded
views, cutaways and clean studio lighting, without stopping production.

Everything in the toolchain is free and cleared for commercial use.

## Why pre-rendered frames instead of WebGL

The viewer swaps pre-rendered images rather than running a live 3D model in the
browser. That buys three things at once:

- **Photoreal quality.** Path-traced frames, not a plastic-looking realtime mesh.
- **Weight.** A 36-frame WebP turntable lands around 1–2 MB and opens on a phone
  with no GPU work.
- **IP protection.** A rendered image cannot be turned back into CAD. Publishing
  a GLB hands your competitor the geometry; publishing frames does not.

## Pipeline

```
STEP  ──01──▶  GLB  ──03──▶  frames + hotspots.json  ──04──▶  one HTML file
              (mesh)         (Blender, headless)              (self-contained)
```

| Script | Does |
|---|---|
| `01_step_to_glb.py` | STEP → GLB via OpenCascade (`cascadio`). No FreeCAD or SolidWorks needed. |
| `02_classificar.py` | Buckets parts (fasteners, electronics, drivetrain, structure) so you know what is safe to strip. |
| `03_render_turntable.py` | Blender: axis fix, PBR materials, studio lighting, auto-exposure, turntable render, and per-frame 2D hotspot projection with occlusion testing. |
| `04_montar_demo.py` | Packs frames + JSON + template into a single self-contained HTML. |

## Requirements

- Python 3.10+ with `cascadio`, `trimesh`, `pillow`, `numpy`
- [Blender](https://www.blender.org/) 4.2+ (GPL, free for commercial work)

```bash
pip install cascadio trimesh pillow numpy
```

## Usage

```bash
python 05_scripts/01_step_to_glb.py
python 05_scripts/02_classificar.py

# what is actually visible from outside? use this to choose hotspots
blender --background --factory-startup --python 05_scripts/03_render_turntable.py -- --diag

# full render
blender --background --factory-startup --python 05_scripts/03_render_turntable.py -- \
        --frames 36 --res 1400 --samples 96

# recompute hotspot anchors only, no re-render (seconds instead of ~30 min)
blender --background --factory-startup --python 05_scripts/03_render_turntable.py -- \
        --frames 36 --somente-pontos

python 05_scripts/04_montar_demo.py --largura 1400 --qualidade 92
```

To point it at a different machine, swap the STEP file and edit two lists at the
top of `03_render_turntable.py`: `MATERIAIS` (part name → PBR material) and
`PONTOS` (hotspot label → part names). Nothing else is model-specific.

## Four problems this solves that are not obvious up front

**The model arrives lying down.** `cascadio` writes the STEP in Z-up, but
Blender's glTF importer assumes Y-up and rotates it. A press whose real height
is 1016 mm shows up 478 mm tall with its height on the Y axis. Fixed with a
−90° X rotation; always sanity-check the printed `dim(mm)` line.

**Part names are not where you expect.** `cascadio` names glTF *nodes* after
STEP NAUO entities (`NAUO1`, `NAUO2`, …) and puts the real part name on the
*mesh*. In Blender that means `object.name` is useless and `object.data.name`
is what you want. Every lookup here uses `data.name`.

**Guessing light wattage does not converge.** Instead the script renders one
small linear EXR frame, measures luminance at a high percentile, and corrects
exposure in stops. That handles a white machine and a black one with chrome
columns without hand-tuning, and it carries over to the next model.

**A bounding-box centre is a bad hotspot anchor**, and it fails in two opposite
ways. It goes invisible when another part sits in front of it — a test table
hidden behind its own pedestal. And on symmetric pairs, like two guide columns,
the combined centre lands in mid-air *between* them, where the occlusion ray
hits nothing at all and reports a false positive. The fix is multiple candidate
anchors per hotspot — the largest part's centre, each part's centre, and mesh
vertices sorted by height — picking, per frame, the visible one nearest the
reference.

## Output

A single HTML file. No hosting, no build step, no external requests. Drag to
rotate, click a marker to open that component's spec, and the spec table feeds
both the page and the downloadable datasheet from the same source.

## License

MIT
