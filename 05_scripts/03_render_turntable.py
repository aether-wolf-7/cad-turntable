"""
Etapa 3 - Render do giro (turntable) da maquina + coordenadas dos pontos clicaveis.

Roda DENTRO do Blender, sem abrir interface:

    blender --background --factory-startup --python 03_render_turntable.py -- --frames 36

Opcoes: --frames N  --res PX  --samples N  --engine CYCLES|BLENDER_EEVEE_NEXT

O que ele faz:
  1. importa o .glb de 01_cad/
  2. corrige o eixo (o arquivo vem deitado apos a conversao Y-up do Blender)
  3. cria materiais PBR a partir das cores originais do STEP
  4. enquadra a camera pela esfera envolvente, ilumina com 3 pontos
  5. gira a maquina e renderiza N quadros com fundo transparente -> 03_frames/
  6. exporta a posicao 2D de cada ponto clicavel em CADA quadro, com teste de
     oclusao por raio -> 04_web/hotspots.json

NOTA IMPORTANTE SOBRE NOMES
O cascadio nomeia os NOS do glTF como NAUO1, NAUO2... (entidades do STEP) e
guarda o nome real da peca na MALHA. No Blender isso vira:
    objeto.name      -> 'NAUO37'          (inutil)
    objeto.data.name -> 'CARENAGEM 1'     (o que interessa)
Toda busca por peca usa data.name.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
FRAMES_DIR = ROOT / "03_frames"
WEB_DIR = ROOT / "04_web"

_glbs = sorted((ROOT / "01_cad").glob("*.glb"))
if not _glbs:
    raise SystemExit("nenhum .glb em 01_cad. Rode 01_step_to_glb.py antes.")
GLB = _glbs[0]
BLEND_OUT = ROOT / "02_render" / (GLB.stem + ".blend")

# ---------------------------------------------------------------------------
# O que e especifico da maquina (materiais e pontos clicaveis) vem de fora, do
# projeto.json, que fica FORA do git. Assim os codigos de peca e de componente
# de um cliente nunca chegam ao repositorio. Sem projeto.json, usa o exemplo.
# ---------------------------------------------------------------------------
CFG_PROJETO = ROOT / "projeto.json"
if not CFG_PROJETO.exists():
    CFG_PROJETO = ROOT / "projeto.exemplo.json"
PROJ = json.loads(CFG_PROJETO.read_text(encoding="utf-8"))
print(f"[cfg] {CFG_PROJETO.name}")

# Materiais PBR por padrao de nome de peca. A primeira entrada que casar vence.
# O que nao casar herda a cor original que veio do STEP.
MATERIAIS = [
    (m["padroes"], dict(cor=tuple(m["cor"]), metallic=m["metallic"],
                        roughness=m["roughness"], nome=m["nome"]))
    for m in PROJ["materiais"]
]

# O GLB do cascadio guarda o STEP em Z-up, mas o importador do Blender assume
# Y-up e deita o modelo. -90 graus em X coloca de pe. Verificar no print de dim.
CORRECAO_EIXO_X_GRAUS = PROJ.get("correcao_eixo_x_graus", -90.0)

# Camera
ELEVACAO_GRAUS = 12.0
LENTE_MM = 85.0
MARGEM = 1.12          # folga alem da esfera envolvente

# Iluminacao (energia escala com o quadrado da distancia).
# O nivel exato nao importa muito: a exposicao e calibrada por medicao depois.
POT_KEY, POT_FILL, POT_RIM = 22.0, 8.0, 13.0
# Softbox de teto: sem ela o inox reflete o vazio e a mesa sai preta.
# Superficie metalica horizontal so aparece se houver algo claro acima dela.
POT_TOPO = 16.0
AMBIENTE = 0.19

# Auto-exposicao. Com a maquina preta e as colunas de inox, a media nao serve:
# quase todo pixel e escuro e o brilho vem so do metal. Entao a exposicao e
# ancorada num percentil alto, deixando o inox brilhar sem estourar.
PERCENTIL_EXPOSICAO = 96
ALVO_LUMINANCIA = 0.78

# Pontos clicaveis: rotulo -> padroes buscados em data.name.
# Use --diag antes de escolher: ele lista o que realmente aparece por fora,
# e so peca visivel serve como ponto.
PONTOS = [(p["rotulo"], p["padroes"]) for p in PROJ["pontos"]]

# ---------------------------------------------------------------------------


def argumentos():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    cfg = {"frames": 36, "res": 1200, "samples": 64, "engine": "CYCLES"}
    for i, a in enumerate(argv):
        if a == "--frames":
            cfg["frames"] = int(argv[i + 1])
        elif a == "--res":
            cfg["res"] = int(argv[i + 1])
        elif a == "--samples":
            cfg["samples"] = int(argv[i + 1])
        elif a == "--engine":
            cfg["engine"] = argv[i + 1]
    return cfg


CFG = argumentos()


def bounds(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in objs:
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo = Vector((min(lo[i], p[i]) for i in range(3)))
            hi = Vector((max(hi[i], p[i]) for i in range(3)))
    return lo, hi


def importar():
    print(f"[1/6] importando {GLB.name}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    malhas = [o for o in bpy.context.scene.objects if o.type == "MESH"]

    raizes = [o for o in bpy.context.scene.objects if o.parent is None]
    R = Matrix.Rotation(math.radians(CORRECAO_EIXO_X_GRAUS), 4, "X")
    for o in raizes:
        o.matrix_world = R @ o.matrix_world
    bpy.context.view_layer.update()

    lo, hi = bounds(malhas)
    d = hi - lo
    print(f"      {len(malhas)} malhas   dim(mm) "
          f"{d.x*1000:.0f} x {d.y*1000:.0f} x {d.z*1000:.0f}  (larg x prof x alt)")
    return malhas


def achar_bsdf(mat):
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


def cor_para_material(rgb, nome):
    mat = bpy.data.materials.new(nome)
    mat.use_nodes = True
    bsdf = achar_bsdf(mat)
    if bsdf is None:
        return mat
    r, g, b = rgb[:3]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    azulado = b > r + 0.04 and lum > 0.4          # padrao SolidWorks p/ metal
    if azulado:
        metallic, roughness = 0.85, 0.34
    elif lum < 0.10:
        metallic, roughness = 0.0, 0.55           # plastico/borracha preta
    elif lum > 0.92:
        metallic, roughness = 0.0, 0.30           # plastico branco
    else:
        metallic, roughness = 0.15, 0.42          # pintado
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def material_explicito(spec):
    """Material vindo da lista MATERIAIS, ou seja, definido pela foto real."""
    mat = bpy.data.materials.new(spec["nome"])
    mat.use_nodes = True
    b = achar_bsdf(mat)
    if b is None:
        return mat
    r, g, bl = spec["cor"]
    b.inputs["Base Color"].default_value = (r, g, bl, 1.0)
    b.inputs["Metallic"].default_value = spec["metallic"]
    b.inputs["Roughness"].default_value = spec["roughness"]
    return mat


def casar_material(nome_peca):
    n = nome_peca.lower()
    for padroes, spec in MATERIAIS:
        if any(p.lower() in n for p in padroes):
            return spec
    return None


def aplicar_materiais(malhas):
    print("[2/6] materiais PBR")
    cache = {}
    definidos = 0
    for ob in malhas:
        nome_peca = ob.data.name          # <- nome real esta na malha, nao no objeto
        spec = casar_material(nome_peca)

        if spec is not None:
            chave = ("DEF", spec["nome"])
            definidos += 1
            if chave not in cache:
                cache[chave] = material_explicito(spec)
        else:
            base = (0.7, 0.7, 0.72, 1.0)
            if ob.data.materials and ob.data.materials[0]:
                b = achar_bsdf(ob.data.materials[0])
                if b is not None:
                    base = tuple(b.inputs["Base Color"].default_value)
            chave = tuple(round(c, 3) for c in base[:3])
            if chave not in cache:
                cache[chave] = cor_para_material(chave, f"Mat_{len(cache):03d}")

        ob.data.materials.clear()
        ob.data.materials.append(cache[chave])

    usados = sorted({k[1] for k in cache if k[0] == "DEF"})
    print(f"      {len(cache)} materiais   {definidos} pecas com material da foto")
    print(f"      definidos: {', '.join(usados)}")


def criar_pivo(malhas):
    """Pivo no centro XY, na base do modelo. Nao move as malhas: elas ja tem
    pai vindo do glTF, entao o pivo adota apenas as raizes."""
    print("[3/6] pivo de rotacao")
    lo, hi = bounds(malhas)
    centro = (lo + hi) / 2

    pivo = bpy.data.objects.new("PIVO", None)
    bpy.context.scene.collection.objects.link(pivo)
    pivo.location = (centro.x, centro.y, lo.z)
    bpy.context.view_layer.update()

    for o in [o for o in bpy.context.scene.objects
              if o.parent is None and o is not pivo]:
        o.parent = pivo
        o.matrix_parent_inverse = pivo.matrix_world.inverted()

    bpy.context.view_layer.update()
    raio = (hi - lo).length / 2
    alvo = Vector((centro.x, centro.y, centro.z))
    print(f"      centro {tuple(round(v,3) for v in alvo)}  raio {raio:.3f}")
    return pivo, alvo, raio


def montar_camera(alvo, raio):
    """Distancia calculada pela esfera envolvente e pelo campo de visao,
    para o objeto sempre caber no quadro."""
    print("[4/6] camera e luz")
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = LENTE_MM
    cam_data.sensor_width = 36.0
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    fov = 2 * math.atan(cam_data.sensor_width / (2 * LENTE_MM))
    dist = (raio * MARGEM) / math.sin(fov / 2)

    elev = math.radians(ELEVACAO_GRAUS)
    cam.location = (
        alvo.x,
        alvo.y - dist * math.cos(elev),
        alvo.z + dist * math.sin(elev),
    )
    cam.rotation_euler = (alvo - cam.location).to_track_quat("-Z", "Y").to_euler()
    print(f"      distancia {dist:.2f} m")

    def area(nome, offset, pot, tam):
        loc = alvo + Vector(offset) * dist
        d = bpy.data.lights.new(nome, type="AREA")
        d.energy = pot * (dist ** 2)      # energia escala com distancia^2
        d.size = tam * raio
        o = bpy.data.objects.new(nome, d)
        bpy.context.scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (alvo - loc).to_track_quat("-Z", "Y").to_euler()

    area("Key",  (-0.55, -0.65, 0.78), POT_KEY,  2.6)
    area("Fill", (0.72, -0.48, 0.30),  POT_FILL, 3.0)
    area("Rim",  (0.28, 0.82, 0.62),   POT_RIM,  2.0)
    area("Topo", (0.05, -0.10, 1.35),  POT_TOPO, 4.2)   # reflexo do inox

    w = bpy.data.worlds.new("World")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (AMBIENTE, AMBIENTE, AMBIENTE * 1.05, 1)
    bpy.context.scene.world = w
    return cam


def criar_pontos(malhas, pivo):
    """Para cada ponto guarda VARIAS ancoras candidatas em espaco local do pivo:
    o centro da caixa mais amostras de vertices da propria peca. Assim, quando o
    centro esta atras de outra peca (o caso da mesa, tapada pelo pedestal), ainda
    existe um ponto da peca que a camera enxerga."""
    print("[5/6] pontos clicaveis")
    inv = pivo.matrix_world.inverted()
    pontos = []
    for rotulo, padroes in PONTOS:
        alvos = [o for o in malhas
                 if any(p.lower() in o.data.name.lower() for p in padroes)]
        if not alvos:
            print(f"      [AVISO] '{rotulo}' nao achou peca")
            continue

        # A referencia e o centro da MAIOR peca do grupo, nao o centro do
        # conjunto: em pecas pares (as duas colunas) o centro do conjunto cai
        # no ar entre elas e o marcador flutuaria fora da maquina.
        def volume(ob):
            l, h = bounds([ob])
            d = h - l
            return d.x * d.y * d.z

        principal = max(alvos, key=volume)
        centro_de = lambda ob: (lambda lh: (lh[0] + lh[1]) / 2)(bounds([ob]))

        cands = [inv @ centro_de(principal)]              # indice 0 = referencia
        for ob in alvos:                                  # centro de cada peca
            if ob is not principal:
                cands.append(inv @ centro_de(ob))

        for ob in alvos:
            vs = ob.data.vertices
            if not len(vs):
                continue
            # ordena por altura para as amostras cobrirem a peca inteira, e nao
            # so as pontas (a ordem nativa da malha costuma ser por anel)
            mw = ob.matrix_world
            pts = sorted((mw @ v.co for v in vs), key=lambda p: p.z)
            passo = max(1, len(pts) // 20)
            cands.extend(inv @ p for p in pts[::passo])

        pontos.append((rotulo, cands, {o.name for o in alvos}))
        print(f"      '{rotulo}' <- {len(alvos)} peca(s), {len(cands)} ancoras")
    return pontos


def configurar_render():
    sc = bpy.context.scene
    sc.render.engine = CFG["engine"]
    sc.render.resolution_x = CFG["res"]
    sc.render.resolution_y = CFG["res"]
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.compression = 20
    try:
        sc.view_settings.view_transform = "Standard"
    except Exception:
        pass

    if CFG["engine"] == "CYCLES":
        sc.cycles.samples = CFG["samples"]
        sc.cycles.use_denoising = True
        sc.cycles.use_adaptive_sampling = True
        addon = bpy.context.preferences.addons.get("cycles")
        if addon:
            cp = addon.preferences
            for tipo in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
                try:
                    cp.compute_device_type = tipo
                    devs = cp.get_devices_for_type(tipo)
                    if devs:
                        for d in cp.devices:
                            d.use = True
                        sc.cycles.device = "GPU"
                        print(f"      GPU: {tipo} ({len(devs)} dispositivo(s))")
                        break
                except Exception:
                    continue
            else:
                print("      sem GPU compativel, renderizando em CPU")


def calibrar_exposicao():
    """Renderiza um quadro pequeno em EXR (linear), mede a luminancia do objeto
    e ajusta a exposicao em stops. Evita chutar potencia de luz."""
    import numpy as np

    sc = bpy.context.scene
    rx, ry = sc.render.resolution_x, sc.render.resolution_y
    fmt = sc.render.image_settings.file_format
    amostras = getattr(sc.cycles, "samples", 32) if CFG["engine"] == "CYCLES" else 32

    sc.render.resolution_x = sc.render.resolution_y = 240
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "16"
    if CFG["engine"] == "CYCLES":
        sc.cycles.samples = 16
    sc.view_settings.exposure = 0.0

    tmp = FRAMES_DIR / "_calibracao.exr"
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    sc.render.filepath = str(tmp)
    bpy.ops.render.render(write_still=True)

    img = bpy.data.images.load(str(tmp), check_existing=False)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
    bpy.data.images.remove(img)
    try:
        tmp.unlink()
    except OSError:
        pass

    objeto = px[px[:, 3] > 0.5]
    if len(objeto) < 50:
        print("      [AVISO] objeto quase vazio no quadro, exposicao nao calibrada")
        stops = 0.0
    else:
        lum = 0.2126 * objeto[:, 0] + 0.7152 * objeto[:, 1] + 0.0722 * objeto[:, 2]
        pico = max(float(np.percentile(lum, PERCENTIL_EXPOSICAO)), 1e-5)
        stops = math.log2(ALVO_LUMINANCIA / pico)
        stops = max(-8.0, min(8.0, stops))
        print(f"      medido p{PERCENTIL_EXPOSICAO}={pico:.4f}  alvo={ALVO_LUMINANCIA}  "
              f"correcao={stops:+.2f} stops  ({len(objeto)} px de objeto)")

    sc.view_settings.exposure = stops
    sc.render.resolution_x, sc.render.resolution_y = rx, ry
    sc.render.image_settings.file_format = fmt
    sc.render.image_settings.color_mode = "RGBA"
    if CFG["engine"] == "CYCLES":
        sc.cycles.samples = amostras


def analise_visibilidade(pivo, cam, malhas, n_frames=12, grade=90):
    """Dispara uma grade de raios da camera em varios angulos e conta quais
    pecas realmente aparecem por fora. Serve para escolher os pontos clicaveis."""
    from collections import Counter

    sc = bpy.context.scene
    conta = Counter()
    area = Counter()

    print(f"\n=== VISIBILIDADE EXTERNA ({n_frames} angulos x {grade}x{grade} raios) ===")
    for i in range(n_frames):
        pivo.rotation_euler[2] = 2 * math.pi * i / n_frames
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        origem = cam.matrix_world.translation
        for gy in range(grade):
            for gx in range(grade):
                co = Vector(((gx + 0.5) / grade, (gy + 0.5) / grade, 0))
                # reconstroi a direcao do raio a partir do frustum da camera
                fr = cam.data.view_frame(scene=sc)
                tl, bl = fr[3], fr[2]
                tr = fr[0]
                p = tl + (tr - tl) * co.x + (bl - tl) * co.y
                d = (cam.matrix_world @ p - origem).normalized()
                hit, _, _, _, obj, _ = sc.ray_cast(dg, origem, d)
                if hit and obj is not None and obj.type == "MESH":
                    conta[obj.data.name] += 1
                    area[obj.data.name] += 1

    total = sum(conta.values())
    print(f"{'PECA':<46}{'RAIOS':>8}{'%':>8}")
    print("-" * 62)
    for nome, c in conta.most_common(30):
        print(f"{nome[:45]:<46}{c:>8}{100 * c / total:>7.1f}%")
    print(f"\n{len(conta)} pecas visiveis de {len(malhas)} totais")


def renderizar(pivo, cam, pontos):
    n = CFG["frames"]
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    sc = bpy.context.scene

    so_pontos = "--somente-pontos" in sys.argv
    dados = {
        "quadros": n,
        "resolucao": CFG["res"],
        "pontos": {r: {"rotulo": r, "pos": []} for r, _, _ in pontos},
    }

    acao = "recalculando pontos de" if so_pontos else "renderizando"
    print(f"[6/6] {acao} {n} quadros a {CFG['res']}px / {CFG['samples']} amostras")
    for i in range(n):
        pivo.rotation_euler[2] = 2 * math.pi * i / n
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        origem = cam.matrix_world.translation
        M = pivo.matrix_world

        for rotulo, cands, nomes in pontos:
            ref = world_to_camera_view(sc, cam, M @ cands[0])
            melhor, dist_melhor = None, 1e9
            for c in cands:
                p = M @ c
                co = world_to_camera_view(sc, cam, p)
                if not (0.02 < co.x < 0.98 and 0.02 < co.y < 0.98 and co.z > 0):
                    continue
                hit, _, _, _, obj, _ = sc.ray_cast(
                    dg, origem, (p - origem).normalized())
                if not hit or obj is None or obj.name not in nomes:
                    continue
                d = (co.x - ref.x) ** 2 + (co.y - ref.y) ** 2
                if d < dist_melhor:            # a visivel mais perto do centro
                    melhor, dist_melhor = co, d

            co = melhor if melhor is not None else ref
            dados["pontos"][rotulo]["pos"].append(
                {"x": round(co.x, 4), "y": round(1 - co.y, 4),
                 "v": melhor is not None})

        if not so_pontos:
            sc.render.filepath = str(FRAMES_DIR / f"frame_{i:03d}.png")
            bpy.ops.render.render(write_still=True)
        if (i + 1) % 6 == 0 or i == n - 1:
            print(f"      {i + 1}/{n}")

    (WEB_DIR / "hotspots.json").write_text(
        json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")

    vis = {r: sum(1 for q in d["pos"] if q["v"]) for r, d in dados["pontos"].items()}
    print(f"      quadros com ponto visivel: {vis}")

    BLEND_OUT.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_OUT))
    print(f"      hotspots -> {WEB_DIR / 'hotspots.json'}")
    print(f"      blend    -> {BLEND_OUT}")


def main():
    malhas = importar()
    aplicar_materiais(malhas)
    pivo, alvo, raio = criar_pivo(malhas)
    cam = montar_camera(alvo, raio)
    configurar_render()

    if "--diag" in sys.argv:
        analise_visibilidade(pivo, cam, malhas)
        print("\nOK (diagnostico)")
        return

    if "--somente-pontos" not in sys.argv:
        print("[exposicao] calibrando")
        calibrar_exposicao()
    pontos = criar_pontos(malhas, pivo)
    renderizar(pivo, cam, pontos)
    print("\nOK")


main()
