#!/usr/bin/env python3
"""Encode l'OBJ Y-up en buffers compacts pour le visualiseur WebGL."""
import base64, struct, sys, json, os, re

OBJ = "reconstruction/san_patrizio_Yup.obj"
SKIP = {"sol"}                       # la dalle est remplacee par la grille metrique
MATS = ["mur", "enduitext", "brique", "pierre", "pierrecl", "opaline", "breche", "tuile", "bois", "metal", "sombre",
        "porte", "portemet", "mosaique", "mosfront", "mostymp", "toitplat",
        "marbrecol", "enduitint", "caisson", "solint", "solmotif", "marbrevert",
        "inscript", "dorure", "arcpeint", "arcsurr", "mosabside", "blason", "blasonb",
        "ocre", "ardoise", "solbande", "tableau",
        "solcham", "solcuis", "solbain", "damiern", "damierb", "portebois",
        "laque", "plantrav", "inox", "assise", "tissu", "boisclair", "terrasse",
        "poche",
        "vitrage", "vitrail"]

# La palette du visualiseur est indexee par la position dans MATS. Ajouter un
# materiau ici sans l'ajouter la-bas peint la geometrie en brique : on verifie.
_tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "viewer.tpl.html")).read()
_arr = _tpl[_tpl.index("const HEX=["):]
_hex = re.findall(r'"#[0-9A-Fa-f]{6}"', _arr[:_arr.index("];")])
assert len(_hex) == len(MATS), (
    f"palette desynchronisee : {len(_hex)} couleurs pour {len(MATS)} materiaux")
_cap = int(re.search(r"uniform vec3 uPal\[(\d+)\]", _tpl).group(1))
assert len(MATS) <= _cap, (
    f"uPal[{_cap}] est trop petit pour {len(MATS)} materiaux : le shader lit "
    "hors bornes et peint au hasard")

verts, tris, mats = [], [], []
cur = None
for line in open(OBJ):
    if line.startswith("v "):
        p = line.split()
        verts.append((float(p[1]), float(p[2]), float(p[3])))
    elif line.startswith("usemtl "):
        cur = line.split()[1]
    elif line.startswith("f "):
        if cur in SKIP:
            continue
        idx = [int(t.split("/")[0]) - 1 for t in line.split()[1:]]
        m = MATS.index(cur) if cur in MATS else 0
        for k in range(1, len(idx) - 1):          # eventail : quads et n-gons
            tris.append((idx[0], idx[k], idx[k + 1]))
            mats.append(m)

# Nomenclature des pieces : rectangles poses au sol, exprimes dans le repere
# du generateur ; on les bascule dans celui du visualiseur avec la meme
# transformation que le maillage (x-cx, z-gy, -y-cz).
_R = os.path.dirname(os.path.abspath(__file__)) + "/../reconstruction"
try:
    _T = json.load(open(_R + "/yup.json"))
    PIECES = [{"l": p["l"], "n": p["n"], "a": p["a"],
               "x0": round(p["x0"] - _T["cx"], 2), "x1": round(p["x1"] - _T["cx"], 2),
               "z0": round(-p["y1"] - _T["cz"], 2), "z1": round(-p["y0"] - _T["cz"], 2),
               "y":  round(p["z"] - _T["gy"], 2)}
              for p in json.load(open(_R + "/pieces.json"))]
except FileNotFoundError:
    PIECES = []

xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
bbox = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
SCALE = 0.002                                     # quantification 2 mm -> Int16

# --- rattachement de chaque triangle a une piece -------------------------
# Un octet par sommet : 0 = hors piece, sinon rang dans PIECES + 1. C'est ce
# qui permet d'eclairer une chambre occupee et d'en ouvrir la fiche d'un clic.
_HAB = [(i, p) for i, p in enumerate(PIECES) if p["l"] >= 1]


def room_of(cx, cy, cz):
    best, bd = 0, 1e9
    for i, p in _HAB:
        if not (p["x0"] - 0.35 <= cx <= p["x1"] + 0.35): continue
        if not (p["z0"] - 0.35 <= cz <= p["z1"] + 0.35): continue
        d = cy - p["y"]
        if -0.45 <= d <= 5.6 and d < bd:
            bd, best = d, i + 1
    return best


pos = bytearray(); mid = bytearray(); rid = bytearray()
for t, m in zip(tris, mats):
    a, b, c = (verts[i] for i in t)
    r = room_of((a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3,
                (a[2] + b[2] + c[2]) / 3)
    for vi in t:
        x, y, z = verts[vi]
        pos += struct.pack("<hhh", round(x / SCALE), round(y / SCALE), round(z / SCALE))
        mid.append(m); rid.append(r)

# Les faces de l'OBJ sont triees par materiau : le verre se retrouve en fin de
# liste, on peut donc le dessiner dans une seconde passe, en transparence.
GLASS = {MATS.index("vitrage"), MATS.index("vitrail")}
glass0 = next((i for i, m in enumerate(mats) if m in GLASS), len(mats))
assert all(m in GLASS for m in mats[glass0:]), "le verre n'est pas contigu"

# Boites englobantes des panneaux de mosaique : le maillage n'a pas d'UV, le
# shader les recalcule depuis la position (le panneau est plan et vertical).
MOSF, MOST = MATS.index("mosfront"), MATS.index("mostymp")
MOSA = MATS.index("mosabside")
def bbox_of(mi):
    xs, ys = [], []
    for t, m in zip(tris, mats):
        if m != mi:
            continue
        for vi in t:
            xs.append(verts[vi][0]); ys.append(verts[vi][1])
    return [min(xs), max(xs), min(ys), max(ys)] if xs else [0, 1, 0, 1]


def hinge_of(mi):
    """Emprise des vantaux : bornes en x et plan moyen en z. Le visualiseur en
    deduit les deux axes de rotation pour ouvrir la porte."""
    xs, zs = [], []
    for t, m in zip(tris, mats):
        if m != mi:
            continue
        for vi in t:
            xs.append(verts[vi][0]); zs.append(verts[vi][2])
    if not xs:
        return [0.0, 0.0, 0.0]
    return [round(min(xs), 4), round(max(xs), 4), round(sum(zs) / len(zs), 4)]

import base64 as _b64
from io import BytesIO


def _img64(path, jpeg=False, q=84, cap=1800):
    """Les restitutions photographiques pesaient 8 Mo en PNG dans le fichier.
    En JPEG, a taille utile, elles en font moins de deux — a l'oeil nu, sur un
    panneau de 7 m, la difference ne se voit pas. Les blasons restent en PNG :
    ils ont besoin de leur couche alpha."""
    if not path:
        return ""
    if not jpeg:
        return _b64.b64encode(open(path, "rb").read()).decode()
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > cap:
        r = cap / max(im.size)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    b = BytesIO(); im.save(b, "JPEG", quality=q, optimize=True, progressive=True)
    return _b64.b64encode(b.getvalue()).decode()
# texture rangee dans le projet : le repertoire temporaire est purge
TEXPATH = os.environ.get("MOSAIC_TEX",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "assets", "mosaique_fronton.png"))
TEXPATH = TEXPATH if os.path.exists(TEXPATH) else ""
tex_b64 = _img64(TEXPATH, jpeg=True)
# Ces deux-la n'avaient pas de chemin par defaut : elles ne s'embarquaient que
# si le build etait lance avec APSE_TEX= et TYMP_TEX=, et disparaissaient
# silencieusement sinon. La conque et le tympan se peignaient alors a plat.
_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
TEXA = os.environ.get("APSE_TEX", os.path.join(_ASSETS, "mosaique_abside.png"))
TEXA = TEXA if os.path.exists(TEXA) else ""
TEXT = os.environ.get("TYMP_TEX", os.path.join(_ASSETS, "mosaique_tympan_hd.png"))
TEXT = TEXT if os.path.exists(TEXT) else ""
assert TEXA and TEXT, "conque ou tympan introuvable dans assets/"
# La Cene de la tribune, decoupee dans le cliche de contre-facade
TEXP = os.environ.get("CENE_TEX",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "cene.png"))
TEXP = TEXP if os.path.exists(TEXP) else ""
# Armoiries de Francois, d'apres le trace vectoriel de Wikimedia Commons
TEXB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "assets", "blason_francois.png")
TEXB = TEXB if os.path.exists(TEXB) else ""
# Armes du cardinal-titulaire, dans l'alcove est
TEXB2 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "assets", "blason_collins.png")
TEXB2 = TEXB2 if os.path.exists(TEXB2) else ""
_A = os.path.dirname(os.path.abspath(__file__)) + "/../assets"
TEXI = _A + "/inscription.png"; TEXI = TEXI if os.path.exists(TEXI) else ""
TEXD = _A + "/arc_peint.png";   TEXD = TEXD if os.path.exists(TEXD) else ""

out = {
    "glass0": glass0,
    "mosF": MOSF, "mosT": MOST,
    "bbF": [round(v, 4) for v in bbox_of(MOSF)],
    "bbT": [round(v, 4) for v in bbox_of(MOST)],
    "mosA": MOSA, "vit": MATS.index("vitrail"),
    "names": MATS,
    "pieces": PIECES,
    "porte": MATS.index("porte"), "hinge": hinge_of(MATS.index("porte")),
    "mosB": MATS.index("blason"), "mosB2": MATS.index("blasonb"),
    "bbB": [round(v, 4) for v in bbox_of(MATS.index("blason"))],
    "bbB2": [round(v, 4) for v in bbox_of(MATS.index("blasonb"))],
    "texB": _img64(TEXB, jpeg=False),
    "texB2": _img64(TEXB2, jpeg=False),
    "mosI": MATS.index("inscript"),
    "bbI": [round(v, 4) for v in bbox_of(MATS.index("inscript"))],
    "texI": _img64(TEXI, jpeg=False),
    "mosD": MATS.index("arcpeint"),
    "bbD": [round(v, 4) for v in bbox_of(MATS.index("arcpeint"))],
    "texD": _img64(TEXD, jpeg=True),
    "mosP": MATS.index("tableau"),
    "bbP": [round(v, 4) for v in bbox_of(MATS.index("tableau"))],
    "texP": _img64(TEXP, jpeg=True), "bbA": [round(v, 4) for v in bbox_of(MOSA)],
    "texA": _img64(TEXA, jpeg=True),
    "texT": _img64(TEXT, jpeg=True),
    "tex": tex_b64,
    "scale": SCALE,
    "bbox": [round(v, 3) for v in bbox],
    "count": len(tris) * 3,
    "pos": base64.b64encode(bytes(pos)).decode(),
    "mat": base64.b64encode(bytes(mid)).decode(),
    "room": base64.b64encode(bytes(rid)).decode(),
}
os.makedirs("reconstruction", exist_ok=True)
json.dump(out, open("reconstruction/geom.json", "w"))
print(f"triangles {len(tris)}  sommets {len(tris)*3}")
print(f"bbox {out['bbox']}")
print(f"pos b64 {len(out['pos'])/1024:.0f} Ko   mat b64 {len(out['mat'])/1024:.0f} Ko")
print(f"opaques {glass0} triangles, verre {len(mats)-glass0}")
print(f"mosaique fronton bbox {out['bbF']}  tympan {out['bbT']}")
print(f"texture b64 {len(tex_b64)/1024:.0f} Ko")
