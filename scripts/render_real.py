"""Rendu photoreel de la reconstruction (Blender headless, Cycles).

  blender -b -P scripts/render_real.py -- <obj> <sortie.png> <azimut> <elevation> [samples]

Range dans le projet : la premiere version vivait dans le repertoire temporaire
de session, qui a ete purge.
"""
import bpy, math, sys, os
from mathutils import Vector

av = sys.argv[sys.argv.index("--") + 1:]
OBJ, OUT = av[0], av[1]
AZ, EL = float(av[2]), float(av[3])
SAMPLES = int(av[4]) if len(av) > 4 else 140
DMULT = float(av[5]) if len(av) > 5 else 1.62          # rapprochement
TARGET = [float(x) for x in av[6:9]] if len(av) > 8 else None
# Prise de vue libre : EYE et LOOK court-circuitent l'orbite, indispensable
# pour les vues interieures a hauteur d'homme.
def _v(name):
    raw = os.environ.get(name, "")
    return [float(x) for x in raw.split(",")] if raw else None
EYE, LOOK = _v("EYE"), _v("LOOK")
SUNSET = os.environ.get("SUNSET", "") not in ("", "0")
LENS = float(os.environ.get("LENS", "0") or 0)
RESX = int(os.environ.get("RESX", "1500"))
RESY = int(os.environ.get("RESY", "1000"))
HERE = os.path.dirname(os.path.abspath(__file__))
TEX_MOSAIC = os.path.join(HERE, "..", "assets", "mosaique_fronton_hd.png")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.obj(filepath=OBJ, axis_forward='Y', axis_up='Z')
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']

for o in objs:                       # angles vifs conserves, courbes adoucies
    for p in o.data.polygons:
        p.use_smooth = True
    o.modifiers.new("sharp", 'EDGE_SPLIT').split_angle = math.radians(28)

mn = Vector((1e18,) * 3); mx = Vector((-1e18,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
ctr, span = (mn + mx) / 2, mx - mn
radius = max(span.x, span.y, span.z)


# ─────────────────────────────────────────────────── outils de shading
def nodes_of(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return nt, b


def coords(nt):
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def noise(nt, v, scale=4.0, detail=6.0):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    nt.links.new(v, n.inputs["Vector"])
    return n


def vary(nt, v, c1, c2, scale=0.5):
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].color = (*c1, 1)
    r.color_ramp.elements[1].color = (*c2, 1)
    nt.links.new(noise(nt, v, scale).outputs["Fac"], r.inputs["Fac"])
    return r.outputs["Color"]


def bevel(nt, b, r=0.016):
    """Micro-chanfrein : les aretes accrochent la lumiere au lieu d'etre
    mathematiquement vives. Principal gain de realisme sur ce modele."""
    bv = nt.nodes.new("ShaderNodeBevel")
    bv.inputs["Radius"].default_value = r
    bv.samples = 3
    nt.links.new(bv.outputs["Normal"], b.inputs["Normal"])
    return bv


def bumped(nt, b, height, strength=0.2, r=0.016):
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = strength
    bp.inputs["Distance"].default_value = 0.02
    bv = nt.nodes.new("ShaderNodeBevel")
    bv.inputs["Radius"].default_value = r
    bv.samples = 3
    nt.links.new(height, bp.inputs["Height"])
    nt.links.new(bv.outputs["Normal"], bp.inputs["Normal"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])


def mat_bbox(name):
    lo, hi = [1e18] * 3, [-1e18] * 3
    for o in objs:
        ids = [i for i, m in enumerate(o.data.materials) if m and m.name == name]
        if not ids:
            continue
        for poly in o.data.polygons:
            if poly.material_index in ids:
                for vi in poly.vertices:
                    w = o.matrix_world @ o.data.vertices[vi].co
                    for k in range(3):
                        lo[k] = min(lo[k], w[k]); hi[k] = max(hi[k], w[k])
    return (lo, hi) if hi[0] > lo[0] else (None, None)


def photo_panel(name, path, flip=False):
    """Plaque une image sur un panneau plan vertical. Le maillage n'a pas d'UV :
    on projette depuis les coordonnees objet, en calant sur la boite englobante
    des faces du materiau. Cadrage « cover » pour ne jamais etirer."""
    mat = bpy.data.materials.get(name)
    lo, hi = mat_bbox(name)
    if not mat or lo is None or not os.path.exists(path):
        return
    nt, b = nodes_of(mat)
    w = max(1e-4, hi[0] - lo[0]); h = max(1e-4, hi[2] - lo[2])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    com = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["X"], com.inputs["X"])
    nt.links.new(sep.outputs["Z"], com.inputs["Y"])
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(path)
    img.extension = 'EXTEND'
    iw, ih = img.image.size
    k = (w / h) / (iw / ih) if iw and ih else 1.0
    ku, kv = (k, 1.0) if k <= 1.0 else (1.0, 1.0 / k)
    mp = nt.nodes.new("ShaderNodeMapping")
    # flip : le panneau est vu de dos par rapport a l'axe x du modele, il faut
    # retourner la projection pour que la scene se lise dans le bon sens.
    sx = -ku / w if flip else ku / w
    lx = (hi[0] if flip else -lo[0]) * ku / w + (1 - ku) / 2
    mp.inputs["Scale"].default_value = (sx, kv / h, 1)
    mp.inputs["Location"].default_value = (lx, -lo[2] * kv / h + (1 - kv) / 2, 0)
    nt.links.new(com.outputs["Vector"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.34
    b.inputs["Specular"].default_value = 0.55
    bumped(nt, b, noise(nt, mp.outputs["Vector"], 220.0).outputs["Fac"], 0.30, 0.004)


# ─────────────────────────────────────────────────────────── materiaux
def build(name):
    mat = bpy.data.materials.get(name)
    if not mat:
        return
    # Point de depart : la couleur du fichier MTL. Sans elle, tout materiau
    # sans branche dediee sortait dans le gris par defaut de Blender — c'est
    # a dire les deux tiers de l'eglise.
    dc = tuple(mat.diffuse_color)[:3]
    nt, b = nodes_of(mat)
    b.inputs["Base Color"].default_value = (dc[0], dc[1], dc[2], 1.0)
    b.inputs["Roughness"].default_value = 0.74
    b.inputs["Specular"].default_value = 0.28
    v = coords(nt)

    if name in ("mur", "brique"):
        # brique orangee en facade, enduit rouge rose sur les flancs
        # tout le batiment est en brique apparente (photos du 31 aout) ; on garde
        # juste une nuance entre facade et flancs
        # Le noeud de brique ne pilotait que le relief : la facade restait un
        # aplat orange. Il donne maintenant aussi la couleur, aux dimensions
        # reelles d'une brique romaine (30 x 6,2 cm, joint de 1,2 cm).
        b.inputs["Roughness"].default_value = 0.88
        b.inputs["Specular"].default_value = 0.18
        brick = nt.nodes.new("ShaderNodeTexBrick")
        brick.inputs["Scale"].default_value = 1.0        # coordonnees en metres
        brick.inputs["Brick Width"].default_value = 0.30
        brick.inputs["Row Height"].default_value = 0.074
        brick.inputs["Mortar Size"].default_value = 0.006
        brick.inputs["Bias"].default_value = 0.0
        brick.offset, brick.squash = 0.5, 1.0
        brick.inputs["Color1"].default_value = (0.40, 0.155, 0.090, 1)
        brick.inputs["Color2"].default_value = (0.50, 0.215, 0.125, 1)
        brick.inputs["Mortar"].default_value = (0.52, 0.44, 0.35, 1)
        # Le noeud de brique ne lit que X et Y du vecteur. Sur un mur vertical
        # il faut donc lui donner (horizontal, vertical) : sinon la coordonnee
        # constante du plan ecrase le motif en simples rayures verticales.
        _sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(v, _sep.inputs["Vector"])
        _sum = nt.nodes.new("ShaderNodeMath"); _sum.operation = 'ADD'
        nt.links.new(_sep.outputs["X"], _sum.inputs[0])
        nt.links.new(_sep.outputs["Y"], _sum.inputs[1])
        _cmb = nt.nodes.new("ShaderNodeCombineXYZ")
        nt.links.new(_sum.outputs[0], _cmb.inputs["X"])       # court sur les deux
        nt.links.new(_sep.outputs["Z"], _cmb.inputs["Y"])     # orientations de mur
        nt.links.new(_cmb.outputs["Vector"], brick.inputs["Vector"])
        nt.links.new(brick.outputs["Color"], b.inputs["Base Color"])
        bumped(nt, b, brick.outputs["Fac"], 0.55 if name == "mur" else 0.60)

    elif name == "opaline":
        # Globes allumes : au crepuscule ce sont eux qui portent l'interieur.
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = (1.0, 0.92, 0.78, 1)
        em.inputs["Strength"].default_value = float(os.environ.get("LAMPES", "26"))
        out = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'][0]
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])

    elif name == "pierre":
        nt.links.new(vary(nt, v, (0.60, 0.57, 0.49), (0.82, 0.79, 0.71), 0.55),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.62
        b.inputs["Specular"].default_value = 0.32
        bumped(nt, b, noise(nt, v, 4.5).outputs["Fac"], 0.08, 0.012)

    elif name == "tuile":
        # coppi patines gris-beige, releve sur la photo du toit
        nt.links.new(vary(nt, v, (0.115, 0.100, 0.080), (0.300, 0.268, 0.212), 1.6),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.88
        b.inputs["Specular"].default_value = 0.16
        bumped(nt, b, noise(nt, v, 9.0).outputs["Fac"], 0.10, 0.012)

    elif name == "terrasse":
        # revetement stabilise : granuleux, mat, rouge brique eclairci
        nt.links.new(vary(nt, v, (0.30, 0.13, 0.09), (0.46, 0.22, 0.15), 2.4),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.94
        b.inputs["Specular"].default_value = 0.10
        bumped(nt, b, noise(nt, v, 26.0).outputs["Fac"], 0.22, 0.006)

    elif name in ("damiern", "damierb"):
        b.inputs["Base Color"].default_value = (
            (0.012, 0.012, 0.016, 1) if name == "damiern"
            else (0.84, 0.82, 0.77, 1))
        b.inputs["Roughness"].default_value = 0.14
        b.inputs["Specular"].default_value = 0.62
        bumped(nt, b, noise(nt, v, 3.0).outputs["Fac"], 0.03, 0.004)

    elif name in ("solcham", "solcuis", "solbain"):
        col = {"solcham": (0.70, 0.68, 0.63),
               "solcuis": (0.63, 0.24, 0.16),
               "solbain": (0.60, 0.58, 0.55)}[name]
        nt.links.new(vary(nt, v, tuple(c * 0.82 for c in col), col, 1.1),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.28
        b.inputs["Specular"].default_value = 0.44

    elif name == "laque":
        b.inputs["Base Color"].default_value = (0.88, 0.87, 0.85, 1)
        b.inputs["Roughness"].default_value = 0.22
        b.inputs["Specular"].default_value = 0.58

    elif name == "plantrav":
        b.inputs["Base Color"].default_value = (0.035, 0.035, 0.038, 1)
        b.inputs["Roughness"].default_value = 0.35
        bumped(nt, b, noise(nt, v, 30.0).outputs["Fac"], 0.06, 0.003)

    elif name == "inox":
        b.inputs["Base Color"].default_value = (0.55, 0.57, 0.59, 1)
        b.inputs["Metallic"].default_value = 0.92
        b.inputs["Roughness"].default_value = 0.26

    elif name == "assise":
        b.inputs["Base Color"].default_value = (0.017, 0.017, 0.021, 1)
        b.inputs["Roughness"].default_value = 0.52

    elif name == "tissu":
        b.inputs["Base Color"].default_value = (0.15, 0.20, 0.21, 1)
        b.inputs["Roughness"].default_value = 0.88
        bumped(nt, b, noise(nt, v, 60.0).outputs["Fac"], 0.10, 0.002)

    elif name in ("boisclair", "portebois"):
        c0, c1 = ((0.45, 0.31, 0.15), (0.66, 0.50, 0.26)) if name == "boisclair" \
                 else ((0.38, 0.19, 0.07), (0.60, 0.33, 0.14))
        nt.links.new(vary(nt, v, c0, c1, 7.0), b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.42
        b.inputs["Specular"].default_value = 0.36

    elif name == "toitplat":
        b.inputs["Base Color"].default_value = (0.16, 0.16, 0.17, 1)
        b.inputs["Roughness"].default_value = 0.88
        bumped(nt, b, noise(nt, v, 6.0).outputs["Fac"], 0.10, 0.01)

    elif name == "vitrage":
        b.inputs["Base Color"].default_value = (0.86, 0.87, 0.83, 1)
        b.inputs["Transmission"].default_value = 0.92
        b.inputs["Roughness"].default_value = 0.07
        b.inputs["IOR"].default_value = 1.46
        b.inputs["Specular"].default_value = 0.9
        bevel(nt, b, 0.006)

    elif name == "sombre":
        b.inputs["Base Color"].default_value = (0.012, 0.013, 0.016, 1)
        b.inputs["Roughness"].default_value = 0.5
        b.inputs["Metallic"].default_value = 0.35
        bevel(nt, b, 0.006)

    elif name == "bois":
        nt.links.new(vary(nt, v, (0.055, 0.026, 0.013), (0.115, 0.058, 0.030), 2.2),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.52
        b.inputs["Specular"].default_value = 0.42
        bumped(nt, b, noise(nt, v, 3.0, 8.0).outputs["Fac"], 0.16, 0.01)

    elif name == "vitrail":
        # verre PALE, blanc chaud a miel, resille de plombs : releve sur les
        # photos d'interieur, ce n'est pas un vitrail sombre et sature
        diag = nt.nodes.new("ShaderNodeTexWave")
        diag.wave_type = 'BANDS'
        try:
            diag.bands_direction = 'DIAGONAL'
        except Exception:
            pass
        diag.inputs["Scale"].default_value = 34.0
        nt.links.new(v, diag.inputs["Vector"])
        lead = nt.nodes.new("ShaderNodeValToRGB")
        lead.color_ramp.elements[0].position = 0.42
        lead.color_ramp.elements[1].position = 0.50
        nt.links.new(diag.outputs["Color"], lead.inputs["Fac"])

        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.inputs["Scale"].default_value = 5.0
        nt.links.new(v, vor.inputs["Vector"])
        sep = nt.nodes.new("ShaderNodeSeparateRGB")
        nt.links.new(vor.outputs["Color"], sep.inputs["Image"])
        pal = nt.nodes.new("ShaderNodeValToRGB")
        e = pal.color_ramp.elements
        e[0].position, e[0].color = 0.0, (0.88, 0.84, 0.68, 1)
        e[1].position, e[1].color = 1.0, (0.80, 0.62, 0.24, 1)
        for pos, col in ((0.55, (0.86, 0.83, 0.70, 1)),
                         (0.80, (0.42, 0.30, 0.55, 1)),
                         (0.92, (0.24, 0.42, 0.52, 1))):
            pal.color_ramp.elements.new(pos).color = col
        nt.links.new(sep.outputs["R"], pal.inputs["Fac"])

        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.inputs["Color1"].default_value = (0.03, 0.028, 0.026, 1)
        nt.links.new(lead.outputs["Color"], mix.inputs["Fac"])
        nt.links.new(pal.outputs["Color"], mix.inputs["Color2"])
        nt.links.new(mix.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Transmission"].default_value = 0.72
        b.inputs["Roughness"].default_value = 0.22
        b.inputs["IOR"].default_value = 1.5
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Strength"].default_value = 1.1
        nt.links.new(mix.outputs["Color"], em.inputs["Color"])
        ms = nt.nodes.new("ShaderNodeMixShader")
        ms.inputs["Fac"].default_value = 0.30
        on = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'][0]
        nt.links.new(b.outputs["BSDF"], ms.inputs[1])
        nt.links.new(em.outputs["Emission"], ms.inputs[2])
        nt.links.new(ms.outputs["Shader"], on.inputs["Surface"])
        bumped(nt, b, lead.outputs["Color"], 0.12, 0.004)

    elif name == "mosaique":
        b.inputs["Base Color"].default_value = (0.62, 0.44, 0.13, 1)
        b.inputs["Metallic"].default_value = 0.8
        b.inputs["Roughness"].default_value = 0.32
        bumped(nt, b, noise(nt, v, 60.0).outputs["Fac"], 0.4, 0.005)

    elif name == "sol":
        nt.links.new(vary(nt, v, (0.20, 0.19, 0.18), (0.30, 0.29, 0.27), 12.0),
                     b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.94


# Tous les materiaux, pas seulement ceux qui ont une branche : chacun part au
# moins de sa couleur de fichier.
for _m in list(bpy.data.materials):
    build(_m.name)
# Chaque panneau porte SA propre image. Le tympan recevait celle du fronton,
# et les six autres materiaux textures du visualiseur n'avaient rien du tout
# ici : armoiries, conque, Cene, inscription, registre peint.
_A = lambda f: os.path.join(HERE, "..", "assets", f)
photo_panel("mosfront",  _A("mosaique_fronton_hd.png"))
photo_panel("mostymp",   _A("mosaique_tympan_hd.png"))
photo_panel("mosabside", _A("mosaique_abside.png"))
photo_panel("blason",    _A("blason_francois.png"))
photo_panel("blasonb",   _A("blason_collins.png"))
photo_panel("tableau",   _A("cene.png"), flip=True)
photo_panel("inscript",  _A("inscription.png"))
photo_panel("arcpeint",  _A("arc_peint.png"))

# ────────────────────────────────────── sol, ciel, soleil
bpy.ops.mesh.primitive_plane_add(size=radius * 14,
                                 location=(ctr.x, ctr.y, mn.z - 0.02))
gm = bpy.data.materials.new("terrain")
gnt, gb = nodes_of(gm)
gnt.links.new(vary(gnt, coords(gnt), (0.17, 0.16, 0.15), (0.26, 0.25, 0.23), 0.4),
              gb.inputs["Base Color"])
gb.inputs["Roughness"].default_value = 0.95
bpy.context.active_object.data.materials.append(gm)

world = bpy.data.worlds.new("W"); world.use_nodes = True
wnt = world.node_tree; wnt.nodes.clear()
wout = wnt.nodes.new("ShaderNodeOutputWorld")
bg = wnt.nodes.new("ShaderNodeBackground")
geo = wnt.nodes.new("ShaderNodeNewGeometry")
sepw = wnt.nodes.new("ShaderNodeSeparateXYZ")
wnt.links.new(geo.outputs["Incoming"], sepw.inputs["Vector"])
rng = wnt.nodes.new("ShaderNodeMapRange")
rng.inputs["From Min"].default_value = -0.12
rng.inputs["From Max"].default_value = 0.62
wnt.links.new(sepw.outputs["Z"], rng.inputs["Value"])
ramp = wnt.nodes.new("ShaderNodeValToRGB")
if SUNSET:
    ramp.color_ramp.elements[0].color = (1.00, 0.52, 0.22, 1)   # braise d'horizon
    ramp.color_ramp.elements[1].color = (0.09, 0.15, 0.36, 1)   # bleu profond
else:
    ramp.color_ramp.elements[0].color = (0.72, 0.78, 0.86, 1)   # brume d'horizon
    ramp.color_ramp.elements[1].color = (0.20, 0.38, 0.72, 1)   # bleu zenithal
wnt.links.new(rng.outputs["Result"], ramp.inputs["Fac"])
wnt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
# Les vues interieures ne recoivent qu'un rasant : on releve le ciel pour
# que la nef ne soit pas un trou noir.
bg.inputs["Strength"].default_value = float(os.environ.get(
    "WORLD", "0.85" if SUNSET else "1.15"))
wnt.links.new(bg.outputs["Background"], wout.inputs["Surface"])
bpy.context.scene.world = world

sd = bpy.data.lights.new("Soleil", 'SUN')
if SUNSET:
    sd.energy, sd.angle, sd.color = 8.5, math.radians(2.6), (1.0, 0.56, 0.26)
else:
    sd.energy, sd.angle, sd.color = 4.2, math.radians(1.2), (1.0, 0.94, 0.84)
sun = bpy.data.objects.new("Soleil", sd)
# Azimut du soleil independant de la camera : au couchant il doit raser la
# facade, sinon le relief ne se lit pas.
sa = math.radians(float(os.environ.get("SUNAZ", str(AZ + 34))))
se = math.radians(float(os.environ.get("SUNEL", "5.5" if SUNSET else "38")))
sun.location = ctr + Vector((math.cos(se) * math.cos(sa),
                             math.cos(se) * math.sin(sa),
                             math.sin(se))) * (radius * 3)
sun.rotation_euler = (ctr - sun.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.scene.collection.objects.link(sun)

# ───────────────────────────────────────────────────────── camera
cd = bpy.data.cameras.new("Cam"); cd.lens = LENS or (28 if EYE else 48)
cam = bpy.data.objects.new("Cam", cd)
bpy.context.scene.collection.objects.link(cam)
if EYE:
    cam.location = Vector(EYE)
    look = Vector(LOOK or (ctr.x, ctr.y, ctr.z))
else:
    a, e = math.radians(AZ), math.radians(EL)
    dist = radius * DMULT
    focus = Vector(TARGET) if TARGET else ctr
    cam.location = focus + Vector((dist * math.cos(e) * math.cos(a),
                                   dist * math.cos(e) * math.sin(a),
                                   dist * math.sin(e)))
    look = focus if TARGET else Vector((ctr.x, ctr.y, ctr.z - span.z * 0.06))
cam.rotation_euler = (look - cam.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.scene.camera = cam

s = bpy.context.scene
s.render.engine = 'CYCLES'
# Metal si la machine le propose : le rendu passe de plusieurs minutes a
# moins d'une par vue.
try:
    _p = bpy.context.preferences.addons['cycles'].preferences
    _p.compute_device_type = 'METAL'
    _p.get_devices()
    for _d in _p.devices:
        _d.use = True
    s.cycles.device = 'GPU'
except Exception:
    s.cycles.device = 'CPU'
s.cycles.samples = SAMPLES
s.cycles.use_denoising = True
s.cycles.max_bounces, s.cycles.diffuse_bounces = 8, 4
s.cycles.caustics_reflective = s.cycles.caustics_refractive = False
s.view_settings.view_transform = 'Filmic'
s.view_settings.look = 'Medium High Contrast'
s.render.resolution_x, s.render.resolution_y = RESX, RESY
s.render.filepath = OUT
s.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
print("RENDERED", OUT)
