"""
Etapa 4 - Monta o demo web num unico HTML autocontido.

Junta:
  03_frames/frame_*.png   -> WebP embutido como data URI
  04_web/hotspots.json    -> posicao 2D dos pontos por quadro
  04_web/dados_*.json     -> textos e especificacoes da maquina
  04_web/template.html    -> a pagina

Saida: 06_entregas/demo_<maquina>.html

Uso:  python 04_montar_demo.py [--largura 1100] [--qualidade 82] [--teto-mb 12]
"""

import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "03_frames"
WEB = ROOT / "04_web"

_dados = sorted(WEB.glob("dados_*.json"))
if not _dados:
    raise SystemExit(f"nenhum dados_*.json em {WEB}")
DADOS = _dados[0]
SAIDA = ROOT / "06_entregas" / f"demo_{DADOS.stem.removeprefix('dados_')}.html"

ap = argparse.ArgumentParser()
ap.add_argument("--largura", type=int, default=1100)
ap.add_argument("--qualidade", type=int, default=82)
ap.add_argument("--teto-mb", type=float, default=12.0)
A = ap.parse_args()


def codificar(paths, largura, qualidade):
    """PNG -> WebP com alpha -> data URI. Devolve (lista, bytes totais)."""
    uris, total = [], 0
    for p in paths:
        im = Image.open(p).convert("RGBA")
        if im.width != largura:
            im = im.resize((largura, largura), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=qualidade, method=6)
        b = buf.getvalue()
        total += len(b)
        uris.append("data:image/webp;base64," + base64.b64encode(b).decode("ascii"))
    return uris, total


quadros = sorted(FRAMES.glob("frame_*.png"))
if not quadros:
    raise SystemExit(f"nenhum quadro em {FRAMES}. Rode 03_render_turntable.py antes.")

hotspots = json.loads((WEB / "hotspots.json").read_text(encoding="utf-8"))
dados = json.loads(DADOS.read_text(encoding="utf-8"))
template = (WEB / "template.html").read_text(encoding="utf-8")

n_pos = len(next(iter(hotspots["pontos"].values()))["pos"])
if n_pos != len(quadros):
    raise SystemExit(
        f"descompasso: {len(quadros)} quadros em disco mas {n_pos} posicoes no "
        f"hotspots.json. Rode o render de novo para os dois baterem."
    )

largura, qualidade = A.largura, A.qualidade
print(f"{len(quadros)} quadros")

# Reduz progressivamente ate caber no teto (o base64 infla ~33%).
for tentativa in range(6):
    uris, bruto = codificar(quadros, largura, qualidade)
    mb = bruto * 4 / 3 / 1e6
    print(f"  {largura}px q{qualidade}  ->  {bruto/1e6:.2f} MB brutos, ~{mb:.2f} MB em base64")
    if mb <= A.teto_mb:
        break
    if qualidade > 66:
        qualidade -= 8
    else:
        largura = int(largura * 0.85)
else:
    print("  [aviso] ainda acima do teto depois de reduzir")

payload = {"frames": uris, "hotspots": hotspots, "dados": dados}
injecao = "<script>window.__DEMO__=" + json.dumps(payload, ensure_ascii=False) + ";</script>"

html = template.replace("<script>\nconst D = window.__DEMO__;", injecao + "\n<script>\nconst D = window.__DEMO__;", 1)
if injecao not in html:
    raise SystemExit("nao consegui injetar os dados no template")

# O <title> precisa estar literal no arquivo: quem le o titulo nao roda o JS.
titulo = dados.get("pagina", {}).get("titulo") or dados["maquina"]["nome"]
if "__TITULO__" not in html:
    raise SystemExit("o template perdeu o marcador __TITULO__")
html = html.replace("__TITULO__", titulo, 1)

SAIDA.parent.mkdir(parents=True, exist_ok=True)
SAIDA.write_text(html, encoding="utf-8")
print(f"\n{SAIDA}")
print(f"{SAIDA.stat().st_size/1e6:.2f} MB")
