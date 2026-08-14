"""
Etapa 2 - Classifica as pecas da montagem em grupos.

Objetivo:
  - separar ferragem invisivel (rolamento, parafuso, arruela, pino, porca)
  - identificar eletronica / controle (nao vai para modelo 3D publicado)
  - identificar acionamento, estrutura e pecas de projeto proprio do fabricante

Uso:  python 02_classificar.py
Saida: 01_cad/classificacao.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTARIO = ROOT / "01_cad" / "inventario_pecas.json"
SAIDA = ROOT / "01_cad" / "classificacao.json"

# Regex do codigo de peca projetada pelo proprio fabricante, para separar do que
# e componente de catalogo. Vem do projeto.json, campo "prefixo_proprio".
_cfg = ROOT / "projeto.json"
if not _cfg.exists():
    _cfg = ROOT / "projeto.exemplo.json"
PREFIXO_PROPRIO = json.loads(_cfg.read_text(encoding="utf-8")).get("prefixo_proprio")

# Ordem importa: a primeira regra que casar define o grupo.
REGRAS = [
    # --- ferragem: invisivel na maquina montada, sai do modelo ---
    ("ferragem", r"^skf_bearing"),
    ("ferragem", r"^GBT\d"),
    ("ferragem", r"^locknut"),
    ("ferragem", r"^Porca\b"),
    ("ferragem", r"^Arruela\b"),
    ("ferragem", r"^M\d+X\d+"),          # M4X16 = parafuso
    ("ferragem", r"parafuso|washer|screw|pino\b"),

    # --- eletronica e controle: sensivel, nao vai para 3D publicado ---
    ("eletronica", r"^XD3?-"),           # CLP e modulos de expansao
    ("eletronica", r"^KCD"),             # chave / botao
    ("eletronica", r"^AC Power"),        # entrada de forca
    ("eletronica", r"^Conector"),
    ("eletronica", r"^Exten\. USB"),
    ("eletronica", r"FIM DE CURSO"),
    ("eletronica", r"^TG\d"),

    # --- acionamento: motor, redutor, fuso, engrenagem ---
    ("acionamento", r"^Motor\b"),
    ("acionamento", r"^Redutor\b"),
    ("acionamento", r"^Castanha\b"),     # castanha de fuso de esferas
    ("acionamento", r"^M\d[,.]\d\s+Z\d+"),  # engrenagem modulo x, Z dentes
    ("acionamento", r"RD 1:\d"),         # par redutor
    ("acionamento", r"^sv-mm|^SV\d|^SV-MM|^S-YD"),

    # --- estrutura visivel ---
    ("estrutura", r"^(CARENAGEM|HOUSING|COVER|CABINET|ENCLOSURE)"),
    ("estrutura", r"^(CANTONEIRA|BRACKET|ANGLE)"),
]

COMPILADAS = [(g, re.compile(p, re.IGNORECASE)) for g, p in REGRAS]


def base(nome: str) -> str:
    """Remove sufixo de instancia (_2, _03) que o glTF adiciona."""
    return re.sub(r"_\d{1,2}$", "", nome)


def classificar(nome: str) -> str:
    n = base(nome)
    for grupo, rx in COMPILADAS:
        if rx.search(n):
            return grupo
    if PREFIXO_PROPRIO and re.match(PREFIXO_PROPRIO, n, re.IGNORECASE):
        return "projeto_proprio"
    return "desconhecido"


dados = json.loads(INVENTARIO.read_text(encoding="utf-8"))
pecas = dados["pecas"]

grupos = defaultdict(list)
for p in pecas:
    p["grupo"] = classificar(p["nome"])
    grupos[p["grupo"]].append(p)

resumo = {}
for g, itens in grupos.items():
    resumo[g] = {
        "geometrias": len(itens),
        "triangulos": sum(i["triangulos"] for i in itens),
    }

total_tris = dados["total_triangulos"]

SAIDA.write_text(
    json.dumps({"resumo": resumo, "pecas": pecas}, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print(f"Total: {len(pecas)} geometrias / {total_tris:,} triangulos\n")
print(f"{'GRUPO':<20}{'GEOM':>6}{'TRIANGULOS':>14}{'%':>8}")
print("-" * 48)
for g in sorted(resumo, key=lambda k: -resumo[k]["triangulos"]):
    r = resumo[g]
    print(f"{g:<20}{r['geometrias']:>6}{r['triangulos']:>14,}{100*r['triangulos']/total_tris:>7.1f}%")

print("\n--- NAO CLASSIFICADO (precisa de olho) ---")
for p in sorted(grupos["desconhecido"], key=lambda x: -x["triangulos"]):
    print(f"{p['triangulos']:>8,}  {p['nome'][:65]}")
