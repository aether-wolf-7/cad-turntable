"""
Etapa 1 - Converte o STEP para GLB (malha) usando OpenCascade via cascadio.
Nao precisa de FreeCAD nem SolidWorks instalado.

Uso:  python 01_step_to_glb.py [caminho/do/arquivo.step]
      Sem argumento, usa o unico .step/.stp que estiver na raiz do projeto.
Saida: 01_cad/<nome>.glb  +  01_cad/inventario_pecas.json
"""

import json
import sys
import time
from pathlib import Path

import cascadio
import trimesh

ROOT = Path(__file__).resolve().parent.parent

if len(sys.argv) > 1:
    STEP_IN = Path(sys.argv[1]).resolve()
else:
    achados = sorted(p for p in ROOT.iterdir()
                     if p.suffix.lower() in (".step", ".stp"))
    if not achados:
        raise SystemExit(f"nenhum .step ou .stp em {ROOT}. Passe o caminho como argumento.")
    if len(achados) > 1:
        raise SystemExit("mais de um STEP na raiz, informe qual: "
                         + ", ".join(p.name for p in achados))
    STEP_IN = achados[0]

GLB_OUT = ROOT / "01_cad" / (STEP_IN.stem + ".glb")
INVENTARIO = ROOT / "01_cad" / "inventario_pecas.json"

GLB_OUT.parent.mkdir(parents=True, exist_ok=True)

print(f"Lendo:  {STEP_IN}  ({STEP_IN.stat().st_size / 1e6:.1f} MB)")
t0 = time.time()

# tol_linear controla o quao fina fica a malha. 0.1mm da boa qualidade
# para render sem explodir o numero de triangulos.
cascadio.step_to_glb(
    str(STEP_IN),
    str(GLB_OUT),
    tol_linear=0.1,
    tol_angular=0.35,
)

print(f"Convertido em {time.time() - t0:.1f}s -> {GLB_OUT.stat().st_size / 1e6:.1f} MB")

# --- inspeciona o resultado -------------------------------------------------
scene = trimesh.load(str(GLB_OUT), process=False)

pecas = []
total_tris = 0
if isinstance(scene, trimesh.Scene):
    for nome, geom in scene.geometry.items():
        tris = int(len(geom.faces))
        total_tris += tris
        cor = None
        try:
            visual = geom.visual
            if hasattr(visual, "material") and visual.material is not None:
                base = getattr(visual.material, "baseColorFactor", None)
                if base is None:
                    base = getattr(visual.material, "main_color", None)
                if base is not None:
                    cor = [int(c) if c > 1 else round(float(c), 3) for c in base]
        except Exception:
            pass
        pecas.append({"nome": nome, "triangulos": tris, "cor": cor})
else:
    total_tris = int(len(scene.faces))
    pecas.append({"nome": "unico", "triangulos": total_tris, "cor": None})

pecas.sort(key=lambda p: -p["triangulos"])

INVENTARIO.write_text(
    json.dumps(
        {
            "arquivo": STEP_IN.name,
            "total_geometrias": len(pecas),
            "total_triangulos": total_tris,
            "pecas": pecas,
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

print(f"\nGeometrias: {len(pecas)}   Triangulos: {total_tris:,}")
print(f"Inventario: {INVENTARIO}")
print("\n--- 25 pecas mais pesadas ---")
for p in pecas[:25]:
    print(f"{p['triangulos']:>9,}  {p['cor']}  {p['nome'][:70]}")
