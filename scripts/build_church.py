#!/usr/bin/env python3
"""
Reconstruction volumetrique de San Patrizio a Villa Ludovisi (Rome).

Le maillage Apple Flyover est une surface photogrammetrique fondue : pas de murs
nets, pas de volumes fermes, occlusions. Ce script reconstruit un volume propre
et complet, pilote par :

  - l'emprise reelle    : polygone OSM way 203996025 (residu du fit d'abside 0.18 m)
  - les hauteurs reelles: mesurees dans le maillage Flyover, a l'interieur de
                          cette emprise (profils transversal et longitudinal)
  - le programme        : description architecturale de la monographie
                          Brancart / Robino / van der Veen (2026)

Repere : x transverse, y de la facade (Via Boncompagni) vers l'abside
         (Via Sicilia), z vertical, sol a z=0. Unites : metres.
"""
import math, json, os

# ---------------------------------------------------------------- parametres
# Plan (mesure sur OSM, repere nef)
X_W, X_E = -13.43, 12.01          # murs gouttereaux exterieurs
Y_F, Y_B = -25.77, 21.60          # facade / fin du corps rectangulaire
XC = -1.00                        # axe de la nef
NAVE_HW = 7.25                    # demi-largeur de la nef
X_NW, X_NE = XC - NAVE_HW, XC + NAVE_HW
Y_NARTH = -9.00                   # fin du narthex / bloc conventuel
APSE_CX, APSE_CY, APSE_R = -1.08, 23.73, 6.62
# Arc etendu au-dela des 197.6/-18.3 releves sur OSM : la coque n'ayant pas
# d'epaisseur, elle doit penetrer le mur de nef, sinon il reste une fente.
APSE_A0, APSE_A1 = math.radians(206.0), math.radians(-26.0)

# Hauteurs (mesurees dans le maillage Flyover)
Z_AISLE_LOW  = 9.50               # bas-cotes le long de la nef
Z_AISLE_HIGH = 15.40              # bas-cotes en haut de facade, dominant le couvent
Z_EAVE       = 16.30              # arase du mur de nef (corniche 16.30-16.85)
Z_RIDGE      = 21.00              # faite de la nef / sommet du pignon
Z_APSE_EAVE  = 13.00              # corniche de l'abside
Z_APSE_APEX  = 16.60              # sommet du cul-de-four exterieur
SETBACK      = 0.50               # retrait des blocs conventuels sur la facade

WALL = 0.90                       # epaisseur apparente des corniches
verts, faces = [], []             # faces: (mat, [idx,...])


def V(x, y, z):
    verts.append((x, y, z))
    return len(verts)


def F(mat, *idx):
    faces.append((mat, list(idx)))


def quad(mat, a, b, c, d):
    F(mat, a, b, c, d)


# ------------------------------------------------------------------ volumes
def box(x0, x1, y0, y1, z0, z1, mat, top=True, bottom=False, skip=()):
    a = V(x0, y0, z0); b = V(x1, y0, z0); c = V(x1, y1, z0); d = V(x0, y1, z0)
    e = V(x0, y0, z1); f = V(x1, y0, z1); g = V(x1, y1, z1); h = V(x0, y1, z1)
    if "-y" not in skip: quad(mat, a, b, f, e)
    if "+x" not in skip: quad(mat, b, c, g, f)
    if "+y" not in skip: quad(mat, c, d, h, g)
    if "-x" not in skip: quad(mat, d, a, e, h)
    if top:    quad(mat, e, f, g, h)
    if bottom: quad(mat, d, c, b, a)
    return (a, b, c, d, e, f, g, h)


def frustum(cx, cy, bx, by, tx, ty, z0, z1, mat, top=True):
    """Tronc de pyramide : demi-cotes bx,by en bas et tx,ty en haut.
    Indispensable pour un fruit ou une moulure : en empilant des boites on
    obtient un escalier, pas une pente."""
    a = V(cx - bx, cy - by, z0); b = V(cx + bx, cy - by, z0)
    c = V(cx + bx, cy + by, z0); d = V(cx - bx, cy + by, z0)
    e = V(cx - tx, cy - ty, z1); f = V(cx + tx, cy - ty, z1)
    g = V(cx + tx, cy + ty, z1); h = V(cx - tx, cy + ty, z1)
    quad(mat, a, b, f, e); quad(mat, b, c, g, f)
    quad(mat, c, d, h, g); quad(mat, d, a, e, h)
    if top:
        quad(mat, e, f, g, h)


def gable(x0, x1, y0, y1, ze, zr, mat_roof, mat_wall):
    """Toit a deux pentes, faite parallele a y, au milieu de [x0,x1]."""
    xm = (x0 + x1) / 2
    a = V(x0, y0, ze); b = V(x1, y0, ze); c = V(x1, y1, ze); d = V(x0, y1, ze)
    r0 = V(xm, y0, zr); r1 = V(xm, y1, zr)
    quad(mat_roof, a, b, r0, r0)          # degenere -> triangle pignon avant
    faces.pop()
    F(mat_wall, a, b, r0)                 # pignon -y
    F(mat_wall, d, r1, c)                 # pignon +y
    quad(mat_roof, a, r0, r1, d)          # pente ouest
    quad(mat_roof, b, c, r1, r0)          # pente est
    return r0, r1


def arc_pts(cx, cy, r, a0, a1, n, z):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n), z) for i in range(n + 1)]


def apse(cx, cy, r, a0, a1, z0, z1, zapex, n=28, plain=False, apex_y=None,
         mat="mur", mat_roof="tuile"):
    """Mur semi-circulaire + toiture en demi-cone."""
    lo = [V(*p) for p in arc_pts(cx, cy, r, a0, a1, n, z0)]
    hi = [V(*p) for p in arc_pts(cx, cy, r, a0, a1, n, z1)]
    for i in range(n):
        quad(mat, lo[i], lo[i + 1], hi[i + 1], hi[i])
    if plain:                       # simple socle : ni corniche ni toiture
        return None
    # corniche
    lo2 = [V(*p) for p in arc_pts(cx, cy, r + 0.35, a0, a1, n, z1)]
    hi2 = [V(*p) for p in arc_pts(cx, cy, r + 0.35, a0, a1, n, z1 + 0.45)]
    hi3 = [V(*p) for p in arc_pts(cx, cy, r, a0, a1, n, z1 + 0.45)]
    for i in range(n):
        quad("pierre", hi[i], hi[i + 1], lo2[i + 1], lo2[i])
        quad("pierre", lo2[i], lo2[i + 1], hi2[i + 1], hi2[i])
        quad("pierre", hi2[i], hi2[i + 1], hi3[i + 1], hi3[i])
    # Croupe conique. Le sommet est ramene sur le plan du mur adjacent
    # (apex_y) : place au centre de l'abside il se trouvait en avant du mur et
    # la croupe le traversait, d'ou une jonction franchement ratee.
    ay = cy if apex_y is None else apex_y
    # Tronc de cone plutot qu'un eventail vers un sommet unique : les triangles
    # en pointe devenaient tres effiles, leur normale instable, et la croupe
    # rendait presque noire.
    base = arc_pts(cx, cy, r + 0.35, a0, a1, n, z1 + 0.45)
    zt = z1 + 0.45 + (zapex - z1 - 0.45) * 0.86
    apex_pts = []
    for i, p in enumerate(base):
        t = 0.86
        apex_pts.append((p[0] + (cx - p[0]) * t, p[1] + (ay - p[1]) * t, zt))
    lo_i = [V(*p) for p in base]
    hi_i = [V(*p) for p in apex_pts]
    for i in range(n):
        quad(mat_roof, lo_i[i], lo_i[i + 1], hi_i[i + 1], hi_i[i])
    top = V(cx, ay, zapex)
    for i in range(n):
        F(mat_roof, hi_i[i], hi_i[i + 1], top)
    # Fermeture cote nef. Un triangle de tuile tendu de la corde au sommet
    # etait une invention : il flottait en porte-a-faux au-dessus du vide. La
    # croupe meurt contre un pan VERTICAL, du materiau du mur, qui n'est que le
    # raccord entre la paroi et la coupe du cone.
    p0, p1 = base[0], base[n]
    quad(mat, V(*p0), V(*p1), V(p1[0], p1[1], zapex), V(p0[0], p0[1], zapex))
    return hi3


# --------------------------------------------------------- details muraux
def wall_pt(axis, plane, out, u, z, t=0.0):
    """Point sur un mur : axis='x' -> mur normal a x ; u = coord horizontale."""
    if axis == "x":
        return (plane + out * t, u, z)
    return (u, plane + out * t, z)


def opening(axis, plane, out, u, z_sill, z_spring, hw, mat="vitrage",
            depth=0.06, n=12):
    """Panneau sombre en arc plein cintre (baie)."""
    pts = [wall_pt(axis, plane, out, u - hw, z_sill, depth),
           wall_pt(axis, plane, out, u + hw, z_sill, depth),
           wall_pt(axis, plane, out, u + hw, z_spring, depth)]
    for i in range(n + 1):
        a = math.pi * i / n
        pts.append(wall_pt(axis, plane, out, u + hw * math.cos(a),
                           z_spring + hw * math.sin(a), depth))
    pts.append(wall_pt(axis, plane, out, u - hw, z_spring, depth))
    idx = [V(*p) for p in pts]
    for i in range(1, len(idx) - 1):
        F(mat, idx[0], idx[i], idx[i + 1])


def archivolt(axis, plane, out, u, z_sill, z_spring, hw, w=0.30, d=0.28,
              n=14, mat="pierre", jambs=True):
    """Archivolte saillante (le 'sourcil' decrit dans la monographie)."""
    inner, outer = [], []
    for i in range(n + 1):
        a = math.pi * i / n
        inner.append((u + hw * math.cos(a), z_spring + hw * math.sin(a)))
        outer.append((u + (hw + w) * math.cos(a), z_spring + (hw + w) * math.sin(a)))
    ii = [V(*wall_pt(axis, plane, out, p[0], p[1], d)) for p in inner]
    oo = [V(*wall_pt(axis, plane, out, p[0], p[1], d)) for p in outer]
    i0 = [V(*wall_pt(axis, plane, out, p[0], p[1], 0)) for p in inner]
    o0 = [V(*wall_pt(axis, plane, out, p[0], p[1], 0)) for p in outer]
    for i in range(n):
        quad(mat, ii[i], ii[i + 1], oo[i + 1], oo[i])       # face
        quad(mat, oo[i], oo[i + 1], o0[i + 1], o0[i])       # chant exterieur
        quad(mat, i0[i], i0[i + 1], ii[i + 1], ii[i])       # intrados
    if jambs:
        for s in (-1, 1):
            uu = u + s * hw
            box_wall(axis, plane, out, uu - w / 2, uu + w / 2, z_sill, z_spring, d, mat)


def box_wall(axis, plane, out, u0, u1, z0, z1, d, mat):
    """Petit bloc plaque sur un mur (piedroit, lesene, bandeau)."""
    p = [wall_pt(axis, plane, out, u0, z0, 0), wall_pt(axis, plane, out, u1, z0, 0),
         wall_pt(axis, plane, out, u1, z1, 0), wall_pt(axis, plane, out, u0, z1, 0),
         wall_pt(axis, plane, out, u0, z0, d), wall_pt(axis, plane, out, u1, z0, d),
         wall_pt(axis, plane, out, u1, z1, d), wall_pt(axis, plane, out, u0, z1, d)]
    a, b, c, dd, e, f, g, h = [V(*q) for q in p]
    quad(mat, e, f, g, h); quad(mat, a, e, h, dd)
    quad(mat, b, c, g, f); quad(mat, a, b, f, e); quad(mat, dd, h, g, c)


def blind_arcade(axis, plane, out, u0, u1, z_spring, count, hw=None,
                 d=0.16, mat="pierre", colonnettes=True):
    """Frise d'arcatures aveugles (arcades pendantes en plein cintre)."""
    span = (u1 - u0) / count
    if hw is None:
        hw = span * 0.42
    for k in range(count):
        uc = u0 + span * (k + 0.5)
        archivolt(axis, plane, out, uc, z_spring, z_spring, hw,
                  w=0.16, d=d, n=8, mat=mat, jambs=False)
        if colonnettes:
            for sgn in (-1, 1):
                uu = uc + sgn * hw
                z0c = z_spring - 1.28
                box_wall(axis, plane, out, uu - 0.055, uu + 0.055,
                         z0c + 0.10, z_spring - 0.15, d, mat)          # fut
                box_wall(axis, plane, out, uu - 0.095, uu + 0.095,
                         z_spring - 0.16, z_spring, d + 0.05, mat)     # chapiteau
                box_wall(axis, plane, out, uu - 0.085, uu + 0.085,
                         z0c, z0c + 0.11, d + 0.03, mat)               # culot


def cornice(x0, x1, y0, y1, z, h=0.5, proj=0.45, mat="pierre", roof=True,
            skip=(), sol="toitplat"):
    """Bandeau de corniche sur le pourtour (pas une dalle pleine) + toit plat.

    skip permet d'omettre un cote : un bandeau qui bute exactement sur un mur
    voisin y pose une face coplanaire, donc du z-fighting.
    """
    # Chaque bandeau mord d'un centimetre dans le mur qu'il longe : pose a son
    # nu exact, il lui opposait une face coplanaire.
    q = 0.01
    if "front" not in skip: box(x0 - proj, x1 + proj, y0 - proj, y0 + q, z, z + h, mat)
    if "back"  not in skip: box(x0 - proj, x1 + proj, y1 - q, y1 + proj, z, z + h, mat)
    if "left"  not in skip: box(x0 - proj, x0 + q, y0, y1, z, z + h, mat)
    if "right" not in skip: box(x1 - q, x1 + proj, y0, y1, z, z + h, mat)
    if roof:
        i = 0.06                       # leger retrait : evite le z-fighting
        a = V(x0 + i, y0 + i, z + h * 0.42); b = V(x1 - i, y0 + i, z + h * 0.42)
        c = V(x1 - i, y1 - i, z + h * 0.42); d = V(x0 + i, y1 - i, z + h * 0.42)
        quad(sol, a, b, c, d)


def cylinder(cx, cy, r, z0, z1, n=12, mat="pierre"):
    lo = [V(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n), z0) for i in range(n)]
    hi = [V(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n), z1) for i in range(n)]
    for i in range(n):
        j = (i + 1) % n
        quad(mat, lo[i], lo[j], hi[j], hi[i])
    F(mat, *hi)


def toothed_ring(cx, cy, cz, r_in, r_val, r_tip, teeth, half_y, mat="pierre"):
    """Disque ajoure a dents triangulaires, dans le plan xz.

    Le nimbe de la croix n'est ni un anneau lisse ni une couronne de blocs :
    la photo montre une roue dont le bord exterieur est dente, et evidee en
    quatre quartiers autour des bras.
    """
    n = teeth * 2
    out_p, in_p = [], []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = r_tip if i % 2 == 0 else r_val
        out_p.append((cx + r * math.cos(t), cz + r * math.sin(t)))
        in_p.append((cx + r_in * math.cos(t), cz + r_in * math.sin(t)))
    for i in range(n):
        j = (i + 1) % n
        for dy in (-half_y, half_y):                       # les deux joues
            quad(mat, V(in_p[i][0], cy + dy, in_p[i][1]),
                      V(out_p[i][0], cy + dy, out_p[i][1]),
                      V(out_p[j][0], cy + dy, out_p[j][1]),
                      V(in_p[j][0], cy + dy, in_p[j][1]))
        quad(mat, V(out_p[i][0], cy - half_y, out_p[i][1]),   # chant exterieur
                  V(out_p[j][0], cy - half_y, out_p[j][1]),
                  V(out_p[j][0], cy + half_y, out_p[j][1]),
                  V(out_p[i][0], cy + half_y, out_p[i][1]))
        quad(mat, V(in_p[j][0], cy - half_y, in_p[j][1]),     # chant interieur
                  V(in_p[i][0], cy - half_y, in_p[i][1]),
                  V(in_p[i][0], cy + half_y, in_p[i][1]),
                  V(in_p[j][0], cy + half_y, in_p[j][1]))


def celtic_cross(x, y, z, h=3.15, mat="pierre"):
    """Croix celtique du faite.

    Volontairement synthetique : la piece est sculptee (volutes, feuillages),
    et l'imiter en empilant des boites donnait une pate d'escalier. On garde
    donc les masses justes — de fruste d'un seul tenant, tailloir moulure,
    conge, roue dentee, bras a section constante — et rien de plus.
    """
    S = lambda f: z + f * h
    t = h * 0.085
    aw, ad = t * 0.44, t * 0.52

    frustum(x, y, 0.152 * h, 0.107 * h, 0.146 * h, 0.103 * h, S(0.000), S(0.030), mat)
    frustum(x, y, 0.146 * h, 0.103 * h, 0.121 * h, 0.086 * h, S(0.030), S(0.268), mat)
    frustum(x, y, 0.121 * h, 0.086 * h, 0.155 * h, 0.109 * h, S(0.268), S(0.300), mat)
    box(x - 0.155 * h, x + 0.155 * h, y - 0.109 * h, y + 0.109 * h,
        S(0.300), S(0.328), mat)
    frustum(x, y, 0.155 * h, 0.109 * h, 0.108 * h, 0.078 * h, S(0.328), S(0.362), mat)
    # conge : reprend la masse des volutes sans essayer de les sculpter
    frustum(x, y, 0.108 * h, 0.078 * h, aw * 1.35, ad * 1.35, S(0.362), S(0.468), mat)

    zc = S(0.700)                                     # centre du croisillon
    toothed_ring(x, y, zc, h * 0.092, h * 0.128, h * 0.150, 24, t * 0.30, mat)
    box(x - aw, x + aw, y - ad, y + ad, S(0.455), S(0.960), mat)          # fut
    box(x - h * 0.190, x + h * 0.190, y - ad, y + ad, zc - aw, zc + aw, mat)
    frustum(x, y, aw * 1.45, ad * 1.30, aw * 1.45, ad * 1.30,             # bossage
            zc - aw * 1.45, zc + aw * 1.45, mat)
    frustum(x, y, aw, ad, aw * 1.15, ad * 1.15, S(0.960), S(0.985), mat)  # bout du bras haut

def rake_band(u0, z0, u1, z1, plane, out, depth, t, mat="pierre"):
    """Bandeau incline (corniche rampante) dans le plan de facade."""
    P = [(u0, z0), (u1, z1), (u1, z1 - t), (u0, z0 - t)]
    fr = [V(*wall_pt("y", plane, out, u, z, depth)) for u, z in P]
    bk = [V(*wall_pt("y", plane, out, u, z, 0.0)) for u, z in P]
    quad(mat, fr[0], fr[1], fr[2], fr[3])
    quad(mat, bk[3], bk[2], bk[1], bk[0])
    quad(mat, bk[0], bk[1], fr[1], fr[0])
    quad(mat, bk[2], bk[3], fr[3], fr[2])
    quad(mat, bk[1], bk[2], fr[2], fr[1])
    quad(mat, bk[3], bk[0], fr[0], fr[3])


def pediment_face(uc, hw, zb, za, plane, out, depth, mat="brique"):
    """Triangle du tympan, legerement en saillie sur le plan de facade."""
    T = ((uc - hw, zb), (uc + hw, zb), (uc, za))
    fr = [V(*wall_pt("y", plane, out, u, z, depth)) for u, z in T]
    bk = [V(*wall_pt("y", plane, out, u, z, 0.0)) for u, z in T]
    F(mat, fr[0], fr[1], fr[2])
    # pas de face arriere : elle serait exactement dans le plan de facade
    quad(mat, bk[0], bk[1], fr[1], fr[0])
    quad(mat, bk[1], bk[2], fr[2], fr[1])
    quad(mat, bk[2], bk[0], fr[0], fr[2])


# ─────────────────── geometrie sur plan quelconque (murs courbes) ─────────
def cyl_frame(cx, cy, r, a):
    """Repere tangent a un cylindre : origine, tangente, normale sortante."""
    ca, sa = math.cos(a), math.sin(a)
    return ((cx + r * ca, cy + r * sa, 0.0), (-sa, ca, 0.0), (ca, sa, 0.0))


def _fp(o, ud, nd, u, z, t):
    return (o[0] + ud[0] * u + nd[0] * t, o[1] + ud[1] * u + nd[1] * t, z)


def frame_arch(o, ud, nd, uc, z_spring, hw, w=0.15, d=0.20, n=10, mat="pierre"):
    """Archivolte en plein cintre dans un plan quelconque."""
    ii, oo, i0, o0 = [], [], [], []
    for i in range(n + 1):
        a = math.pi * i / n
        pi_ = (uc + hw * math.cos(a), z_spring + hw * math.sin(a))
        po = (uc + (hw + w) * math.cos(a), z_spring + (hw + w) * math.sin(a))
        ii.append(V(*_fp(o, ud, nd, pi_[0], pi_[1], d)))
        oo.append(V(*_fp(o, ud, nd, po[0], po[1], d)))
        i0.append(V(*_fp(o, ud, nd, pi_[0], pi_[1], 0)))
        o0.append(V(*_fp(o, ud, nd, po[0], po[1], 0)))
    for i in range(n):
        quad(mat, ii[i], ii[i + 1], oo[i + 1], oo[i])
        quad(mat, oo[i], oo[i + 1], o0[i + 1], o0[i])
        quad(mat, i0[i], i0[i + 1], ii[i + 1], ii[i])


def frame_box(o, ud, nd, u0, u1, z0, z1, d, mat="pierre"):
    q = [_fp(o, ud, nd, u0, z0, 0), _fp(o, ud, nd, u1, z0, 0),
         _fp(o, ud, nd, u1, z1, 0), _fp(o, ud, nd, u0, z1, 0),
         _fp(o, ud, nd, u0, z0, d), _fp(o, ud, nd, u1, z0, d),
         _fp(o, ud, nd, u1, z1, d), _fp(o, ud, nd, u0, z1, d)]
    a, b, c, dd, e, f, g, h = [V(*x) for x in q]
    quad(mat, e, f, g, h); quad(mat, a, e, h, dd)
    quad(mat, b, c, g, f); quad(mat, a, b, f, e); quad(mat, dd, h, g, c)


def frame_panel(o, ud, nd, uc, z_sill, z_spring, hw, mat="vitrage", d=0.07, n=10):
    pts = [(uc - hw, z_sill), (uc + hw, z_sill), (uc + hw, z_spring)]
    for i in range(n + 1):
        a = math.pi * i / n
        pts.append((uc + hw * math.cos(a), z_spring + hw * math.sin(a)))
    pts.append((uc - hw, z_spring))
    idx = [V(*_fp(o, ud, nd, p[0], p[1], d)) for p in pts]
    for i in range(1, len(idx) - 1):
        F(mat, idx[0], idx[i], idx[i + 1])


def curved_arcade(cx, cy, r, a0, a1, z_spring, count, hw=0.30, d=0.15):
    """Arcature pendante courant sur un mur courbe (abside, absidioles)."""
    for k in range(count):
        a = a0 + (a1 - a0) * (k + 0.5) / count
        o, ud, nd = cyl_frame(cx, cy, r, a)
        frame_arch(o, ud, nd, 0.0, z_spring, hw, w=0.13, d=d, n=8)
        for sgn in (-1, 1):
            frame_box(o, ud, nd, sgn * hw - 0.07, sgn * hw + 0.07,
                      z_spring - 0.85, z_spring, d)


def curved_windows(cx, cy, r, angles, z_sill, z_spring, hw, mat="vitrage"):
    for a in angles:
        o, ud, nd = cyl_frame(cx, cy, r, a)
        frame_panel(o, ud, nd, 0.0, z_sill, z_spring, hw, mat=mat, d=-0.14)
        frame_box(o, ud, nd, -0.05, 0.05, z_sill, z_spring + hw * 0.6, -0.09)
        frame_arch(o, ud, nd, 0.0, z_spring, hw, w=0.19, d=0.22, n=10)


# ─────────────────── figure sculptee (niche du tympan) ────────────────────
def lathe(cx, cy, z0, h, profile, n=14, mat="pierre"):
    rings = [[V(cx + rr * h * math.cos(2 * math.pi * i / n),
                cy + rr * h * math.sin(2 * math.pi * i / n), z0 + t * h)
              for i in range(n)] for rr, t in profile]
    for k in range(len(rings) - 1):
        A, B = rings[k], rings[k + 1]
        for i in range(n):
            j = (i + 1) % n
            quad(mat, A[i], A[j], B[j], B[i])


def statue(cx, cy, z0, h=1.62, mat="pierre"):
    """Saint Patrick en pied : silhouette drapee, bras, mitre."""
    prof = [(0.000,0.00),(0.165,0.015),(0.170,0.10),(0.158,0.34),(0.135,0.52),
            (0.146,0.60),(0.128,0.70),(0.072,0.765),(0.056,0.795),
            (0.084,0.845),(0.082,0.905),(0.052,0.945),(0.030,0.975),(0.000,1.00)]
    lathe(cx, cy, z0, h, prof, 14, mat)
    for sgn in (-1, 1):                                   # bras le long du corps
        box(cx + sgn * 0.132 * h - 0.035, cx + sgn * 0.132 * h + 0.035,
            cy - 0.038, cy + 0.038, z0 + 0.47 * h, z0 + 0.70 * h, mat)
    box(cx - 0.028, cx + 0.028, cy - 0.028, cy + 0.10,    # crosse
        z0 + 0.42 * h, z0 + 0.98 * h, mat)


def recess(axis, plane, out, u, z_sill, z_spring, hw, depth=0.30, n=12,
           mat="vitrage", sill=True):
    """Ebrasement + vitrage, poses DANS la baie percee par wall_panel."""
    prof = [(u - hw, z_sill), (u - hw, z_spring)]
    for i in range(n + 1):
        a = math.pi - math.pi * i / n
        prof.append((u + hw * math.cos(a), z_spring + hw * math.sin(a)))
    prof.append((u + hw, z_sill))

    o = [V(*wall_pt(axis, plane, out, p[0], p[1], 0.0)) for p in prof]
    i2 = [V(*wall_pt(axis, plane, out, p[0], p[1], -depth)) for p in prof]
    for k in range(len(prof) - 1):
        quad("pierre", o[k], o[k + 1], i2[k + 1], i2[k])       # ebrasement
    g = [V(*wall_pt(axis, plane, out, p[0], p[1], -depth * 0.72)) for p in prof]
    for k in range(1, len(g) - 1):
        F(mat, g[0], g[k], g[k + 1])                            # vitrage en retrait
    if sill:
        box_wall(axis, plane, out, u - hw - 0.16, u + hw + 0.16,
                 z_sill - 0.16, z_sill, 0.24, "pierre")


def glazing(axis, plane, out, u, z_sill, z_top, hw, depth, nh=3, mat="sombre"):
    """Barlotieres : sans elles une baie n'est qu'un trou sombre, jamais une
    fenetre. Meneau vertical et traverses, poses devant le vitrage."""
    t = -depth * 0.55
    box_wall(axis, plane, out, u - 0.030, u + 0.030, z_sill, z_top - hw * 0.35, t, mat)
    for k in range(1, nh + 1):
        z = z_sill + (z_top - z_sill) * k / (nh + 1)
        w = hw * (1.0 if z < z_top - hw else 0.55)
        box_wall(axis, plane, out, u - w, u + w, z - 0.026, z + 0.026, t, mat)


def mullion(axis, plane, out, u, z0, z1, hw, depth=0.30):
    """Meneau central + deux archivoltes : la claire-voie est a deux jours."""
    box_wall(axis, plane, out, u - 0.085, u + 0.085, z0, z1, 0.10, "pierre")
    for sgn in (-1, 1):
        uc = u + sgn * hw * 0.5
        archivolt(axis, plane, out, uc, z0, z1 - hw * 0.5, hw * 0.42,
                  w=0.10, d=0.14, n=8, jambs=False)


def coppi(x0, x1, y0, y1, ze, zr, pitch=0.30, rad=0.105, mat="tuile"):
    """Couverture en coppi : barils demi-ronds du faite a l'egout, comme sur
    les toits romains. Un pan lisse trahissait immediatement la maquette."""
    xm = (x0 + x1) / 2
    n = max(2, int(round((y1 - y0) / pitch)))
    seg = 5
    for side in (-1, 1):
        xe = x0 if side < 0 else x1
        dx, dz = xe - xm, ze - zr
        L = math.hypot(dx, dz)
        ux, uz = dx / L, dz / L                      # descente du rampant
        nx, nz = -uz, ux                             # normale, ramenee vers le haut
        if nz < 0:
            nx, nz = -nx, -nz
        for k in range(n):
            yy = y0 + (y1 - y0) * (k + 0.5) / n
            rings = []
            for base in ((xm, zr), (xe, ze)):
                r = []
                for i in range(seg + 1):
                    t = math.pi * i / seg
                    c, sn = math.cos(t) * rad, math.sin(t) * rad
                    r.append(V(base[0] + nx * sn, yy + c, base[1] + nz * sn))
                rings.append(r)
            A, B = rings
            for i in range(seg):
                quad(mat, A[i], A[i + 1], B[i + 1], B[i])
    # faitiere : rang de coppi couches sur l'arete
    m = max(2, int(round((y1 - y0) / pitch)))
    for k in range(m):
        yy = y0 + (y1 - y0) * (k + 0.5) / m
        ring = []
        for i in range(seg + 1):
            t = math.pi * i / seg
            ring.append((math.cos(t) * rad * 1.25, math.sin(t) * rad * 1.25))
        for i in range(seg):
            a = V(xm + ring[i][0], yy - pitch * 0.45, zr + ring[i][1])
            b = V(xm + ring[i + 1][0], yy - pitch * 0.45, zr + ring[i + 1][1])
            c = V(xm + ring[i + 1][0], yy + pitch * 0.45, zr + ring[i + 1][1])
            d = V(xm + ring[i][0], yy + pitch * 0.45, zr + ring[i][1])
            quad(mat, a, b, c, d)


def dentils(x0, x1, y0, y1, z, size=0.11, gap=0.14, proj=0.16, mat="pierre"):
    """Corniche a denticules, visible sous l'egout sur la photo du toit."""
    step = size + gap
    n = max(1, int((y1 - y0) / step))
    for k in range(n):
        yy = y0 + step * (k + 0.5)
        for xx, sgn in ((x0, -1), (x1, 1)):
            a, b = sorted((xx, xx + sgn * proj))    # ordonne : evite les boites inversees
            box(a, b, yy - size / 2, yy + size / 2, z, z + size * 1.5, mat)


def velux(x0, x1, ycenter, ze, zr, side=1, w=0.78, h=0.95, t=0.62):
    """Fenetre de toit, telle qu'on la voit depuis la terrasse : dormant sombre
    en bordure et verre au milieu.

    La version precedente posait un panneau plein sur toute la surface et
    glissait la vitre DERRIERE : on ne voyait qu'un rectangle noir. Ce sont des
    fenetres, le regard doit passer au travers.
    """
    xm = (x0 + x1) / 2
    xe = x1 if side > 0 else x0
    dx, dz = xe - xm, ze - zr
    L = math.hypot(dx, dz); ux, uz = dx / L, dz / L
    nx, nz = -uz, ux
    if nz < 0:
        nx, nz = -nx, -nz
    cx, cz = xm + ux * L * t, zr + uz * L * t          # centre sur la pente
    def P(a, b, lift):
        return V(cx + ux * a + nx * lift, ycenter + b, cz + uz * a + nz * lift)
    hh, hw, FR = h / 2, w / 2, 0.085                   # FR : largeur du dormant
    quad("vitrage", P(-hh + FR, -hw + FR, 0.13), P(hh - FR, -hw + FR, 0.13),
                    P(hh - FR, hw - FR, 0.13), P(-hh + FR, hw - FR, 0.13))
    for a0, b0, a1, b1 in ((-hh, -hw, hh, -hw + FR), (-hh, hw - FR, hh, hw),
                           (-hh, -hw + FR, -hh + FR, hw - FR),
                           (hh - FR, -hw + FR, hh, hw - FR)):
        quad("metal", P(a0, b0, 0.17), P(a1, b0, 0.17),
                      P(a1, b1, 0.17), P(a0, b1, 0.17))
    for a0, b0, a1, b1 in ((-hh, -hw, hh, -hw), (hh, -hw, hh, hw),
                           (hh, hw, -hh, hw), (-hh, hw, -hh, -hw)):
        quad("metal", P(a0, b0, 0.0), P(a1, b1, 0.0),
                      P(a1, b1, 0.17), P(a0, b0, 0.17))   # tableau du chassis


def wall_panel(axis, plane, out, u0, u1, z0, z1, holes, mat="mur", nz=10):
    """Face de mur reellement PERCEE.

    Sans cela le vitrage n'est qu'un film transparent pose devant un mur plein.
    On decoupe en bandes horizontales, et dans chaque bande on emet les pleins
    entre les baies. La demi-largeur d'une baie est recalculee a chaque bande,
    ce qui dessine l'arc et permet a deux baies de se superposer en largeur a
    des hauteurs differentes (portail et trifora, par exemple).
    holes = [(centre, demi-largeur, allege, naissance d'arc)].
    """
    def Q(ua, ub, za, zb):
        if ub - ua < 1e-6 or zb - za < 1e-6:
            return
        p = [wall_pt(axis, plane, out, ua, za, 0), wall_pt(axis, plane, out, ub, za, 0),
             wall_pt(axis, plane, out, ub, zb, 0), wall_pt(axis, plane, out, ua, zb, 0)]
        q = [V(*x) for x in p]
        quad(mat, q[0], q[1], q[2], q[3])

    bounds = {z0, z1}
    for uc, hw, zs, zp in holes:
        bounds |= {zs, zp, zp + hw}
        for i in range(1, nz):                       # subdivise l'arc
            bounds.add(zp + hw * i / nz)
    zl = sorted(z for z in bounds if z0 - 1e-9 <= z <= z1 + 1e-9)

    for za, zb in zip(zl, zl[1:]):
        if zb - za < 1e-6:
            continue
        zm = (za + zb) / 2
        spans = []
        for uc, hw, zs, zp in holes:
            if not (zs <= zm <= zp + hw):
                continue
            w = hw if zm <= zp else math.sqrt(max(0.0, hw * hw - (zm - zp) ** 2))
            if w > 1e-4:
                spans.append((uc - w, uc + w))
        spans.sort()
        cur = u0
        for sa, sb in spans:
            if sa > cur:
                Q(cur, sa, za, zb)
            cur = max(cur, sb)
        Q(cur, u1, za, zb)



def portal(axis, plane, out, u, z_sill, z_spring, hw, depth=0.55, n=14):
    """Portail : ebrasement, chambranle moulure, vantaux et lunette de mosaique.

    Cotes relevees sur la photographie de facade. La baie de porte fait 1,93 m
    de large pour 2,64 m sous linteau ; l'entablement du chambranle monte a
    3,22 m et la lunette n'a que 1,11 m de rayon. Les vantaux ne remplissent
    donc pas l'arc : ils tiennent dans un chambranle nettement plus etroit,
    ce que la version precedente ignorait.
    """
    DHW, DH, ENT, LHW = 0.965, 2.64, 3.22, 1.11
    SEUIL = 0.30            # exactement le palier du portique et le dallage
    dB, dL, dD, dC = -0.88, -0.42, -0.30, -0.22    # ebrasement traversant

    # ebrasement, de la face du mur jusqu'au fond de la baie
    prof = [(u - hw, z_sill), (u - hw, z_spring)]
    for i in range(n + 1):
        a = math.pi - math.pi * i / n
        prof.append((u + hw * math.cos(a), z_spring + hw * math.sin(a)))
    prof.append((u + hw, z_sill))
    o = [V(*wall_pt(axis, plane, out, q[0], q[1], 0.0)) for q in prof]
    i2 = [V(*wall_pt(axis, plane, out, q[0], q[1], dB)) for q in prof]
    for k in range(len(prof) - 1):
        quad("pierre", o[k], o[k + 1], i2[k + 1], i2[k])

    # Remplissage : seuls le tympan et les ecoincons sont pleins ; la baie de
    # porte reste ouverte, sinon les vantaux s'ouvrent sur un mur.
    def Q(a0, z0, a1, z1, t, mat="pierre"):
        P = lambda uu, zz: V(*wall_pt(axis, plane, out, uu, zz, t))
        quad(mat, P(a0, z0), P(a1, z0), P(a1, z1), P(a0, z1))
    opening(axis, plane, out, u, ENT, z_spring, hw, mat="pierre", depth=dL)
    Q(u - hw, DH, u + hw, ENT, dL)                      # bandeau sous l'entablement
    for _a0, _a1 in ((u - hw, u - DHW), (u + DHW, u + hw)):
        Q(_a0, z_sill, _a1, DH, dL)                     # ecoincons lateraux
    Q(u - DHW, z_sill, u + DHW, SEUIL, dL)              # seuil
    # lunette de mosaique, au-dessus de l'entablement
    opening(axis, plane, out, u, ENT, ENT, LHW, mat="mostymp", depth=dL + 0.03)
    # chambranle : deux piedroits moulures et leur entablement
    for sgn in (-1, 1):
        box_wall(axis, plane, out, u + sgn * DHW, u + sgn * (DHW + 0.24),
                 SEUIL, ENT, dC, "pierre")
    box_wall(axis, plane, out, u - DHW - 0.24, u + DHW + 0.24, DH, ENT, dC, "pierre")
    box_wall(axis, plane, out, u - DHW - 0.34, u + DHW + 0.34,
             ENT - 0.14, ENT + 0.10, dC - 0.06, "pierre")
    # deux vantaux de bois, avec leur battement central
    for sgn in (-1, 1):
        a0 = u + (0.035 if sgn > 0 else -DHW)
        a1 = u + (DHW if sgn > 0 else -0.035)
        box_wall(axis, plane, out, a0, a1, SEUIL, DH, dD, "porte")
        for r in range(4):                                    # panneaux moulures
            zz = SEUIL + (DH - SEUIL) * (r + 0.5) / 4
            box_wall(axis, plane, out, a0 + 0.09, a1 - 0.09,
                     zz - 0.20, zz + 0.20, dD + 0.03, "porte")


def railing_run(x0, x1, y0, y1, z, h=1.02, mat="sombre", pitch=0.22):
    """Une volee droite de garde-corps (et non tout un pourtour)."""
    pw, bw = 0.035, 0.028
    horiz = abs(x1 - x0) >= abs(y1 - y0)
    n = max(2, int((abs(x1 - x0) if horiz else abs(y1 - y0)) / pitch))
    for k in range(n + 1):
        t = k / n
        xx = x0 + (x1 - x0) * t; yy = y0 + (y1 - y0) * t
        box(xx - pw / 2, xx + pw / 2, yy - pw / 2, yy + pw / 2, z, z + h, mat)
    for zz in (z + h - bw, z + h * 0.5):
        if horiz:
            box(min(x0, x1), max(x0, x1), y0 - bw, y0 + bw, zz - bw, zz + bw, mat)
        else:
            box(x0 - bw, x0 + bw, min(y0, y1), max(y0, y1), zz - bw, zz + bw, mat)


def railing(x0, x1, y0, y1, z, h=1.02, mat="sombre", pitch=0.22):
    """Garde-corps metallique des toits-terrasses des blocs conventuels.
    Visible sur les photos du 31 aout : c'est le « rooftop » d'ou a ete prise
    la vue du toit. Il manquait completement."""
    pw, bw = 0.035, 0.028
    for (a, b, horiz) in ((y0, None, True), (y1, None, True),
                          (x0, None, False), (x1, None, False)):
        if horiz:
            n = max(2, int((x1 - x0) / pitch))
            for k in range(n + 1):
                xx = x0 + (x1 - x0) * k / n
                box(xx - pw / 2, xx + pw / 2, a - pw / 2, a + pw / 2, z, z + h, mat)
            for zz in (z + h - bw, z + h * 0.5):
                box(x0, x1, a - bw, a + bw, zz - bw, zz + bw, mat)
        else:
            n = max(2, int((y1 - y0) / pitch))
            for k in range(n + 1):
                yy = y0 + (y1 - y0) * k / n
                box(a - pw / 2, a + pw / 2, yy - pw / 2, yy + pw / 2, z, z + h, mat)
            for zz in (z + h - bw, z + h * 0.5):
                box(a - bw, a + bw, y0, y1, zz - bw, zz + bw, mat)


def rake_dentils(u0, z0, u1, z1, plane, out, size=0.10, pitch=0.20, mat="pierre"):
    """Denticules suivant un rampant : la corniche du fronton en porte un rang
    net sur les photos, la mienne etait lisse."""
    L = math.hypot(u1 - u0, z1 - z0)
    n = max(1, int(L / pitch))
    for k in range(n):
        t = (k + 0.5) / n
        u = u0 + (u1 - u0) * t
        z = z0 + (z1 - z0) * t
        box_wall("y", plane, out, u - size / 2, u + size / 2,
                 z - size * 0.75, z + size * 0.75, 0.30, mat)


def disc_ring(cx, cy, cz, r_in, r_out, half_y, n=40, mat="pierre"):
    """Anneau plat dans le plan xz, d'epaisseur 2*half_y en y.

    Ma premiere version semait des petits cubes le long d'un cercle : de loin
    ca ne lisait pas comme une moulure mais comme du bruit. Un vrai bandeau
    annulaire donne la courbe franche du nimbe et de l'oculus.
    """
    A, B = [], []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        c, s_ = math.cos(t), math.sin(t)
        A.append((cx + r_in * c, cz + r_in * s_))
        B.append((cx + r_out * c, cz + r_out * s_))
    for i in range(n):
        for dy in (-half_y, half_y):                        # deux joues
            a = V(A[i][0], cy + dy, A[i][1]); b = V(B[i][0], cy + dy, B[i][1])
            c2 = V(B[i + 1][0], cy + dy, B[i + 1][1]); d = V(A[i + 1][0], cy + dy, A[i + 1][1])
            quad(mat, a, b, c2, d)
        for (P, sgn) in ((A, -1), (B, 1)):                  # chants interne/externe
            a = V(P[i][0], cy - half_y, P[i][1]); b = V(P[i + 1][0], cy - half_y, P[i + 1][1])
            c2 = V(P[i + 1][0], cy + half_y, P[i + 1][1]); d = V(P[i][0], cy + half_y, P[i][1])
            quad(mat, a, b, c2, d)


def rooftop_hut(x0, x1, y0, y1, z, h=2.05, mat="mur"):
    """Edicule d'acces a la terrasse, releve sur la vue aerienne immersive.

    Toit en PENTE (et non une dalle plate) : deux tiers couverts en coppi comme
    le grand comble, dernier tiers vitre en resille de 2 x 46 carreaux qui
    eclaire la cage d'escalier. Porte metallique rectangulaire brun fonce sur
    la face nord, dans son tiers est.
    """
    Z_HAUT, Z_BAS = z + 2.88, z + 1.30        # haut cote nef, bas cote est

    def zp(t):                                   # t = 0 a l'ouest, 1 a l'est
        return Z_BAS + (Z_HAUT - Z_BAS) * (1 - t)
    # Les murs montent JUSQU'AU rampant : une boite a sommet plat laissait un
    # decrochement de 86 cm sous le haut de la pente.
    def _wz(xx):
        return zp((xx - x0) / (x1 - x0))
    for _yf in (y0, y1):
        quad(mat, V(x0, _yf, z), V(x1, _yf, z),
                  V(x1, _yf, _wz(x1)), V(x0, _yf, _wz(x0)))
    quad(mat, V(x0, y0, z), V(x0, y1, z), V(x0, y1, zp(0)), V(x0, y0, zp(0)))
    quad(mat, V(x1, y0, z), V(x1, y1, z), V(x1, y1, zp(1)), V(x1, y0, zp(1)))

    # rampant : haut cote ouest (mur de nef), bas cote est
    NT = 22                                      # segments de la partie tuilee
    xt = x0 + (x1 - x0) * 0.66                   # limite tuiles / verriere
    a0 = V(x0, y0, zp(0)); b0 = V(xt, y0, zp(0.66))
    c0 = V(xt, y1, zp(0.66)); d0 = V(x0, y1, zp(0))
    quad("tuile", a0, b0, c0, d0)                # pan tuile
    # coppi : memes barils que le grand comble
    nrows = max(2, int((y1 - y0) / 0.30))
    for k in range(nrows):
        yy = y0 + (y1 - y0) * (k + 0.5) / nrows
        for seg in range(5):
            t0, t1 = math.pi * seg / 5, math.pi * (seg + 1) / 5
            pts = []
            for (xx, tt) in ((x0, 0.0), (xt, 0.66)):
                for t in (t0, t1):
                    pts.append((xx, yy + math.cos(t) * 0.095,
                                zp(tt) + math.sin(t) * 0.095))
            quad("tuile", V(*pts[0]), V(*pts[1]), V(*pts[3]), V(*pts[2]))
    # verriere : dernier tiers, resille 2 x 46
    g0 = V(xt, y0, zp(0.66)); g1 = V(x1, y0, zp(1))
    g2 = V(x1, y1, zp(1)); g3 = V(xt, y1, zp(0.66))
    quad("vitrage", g0, g1, g2, g3)
    for i in range(1, 46):                       # 46 carreaux dans la longueur
        yy = y0 + (y1 - y0) * i / 46
        quad("metal", V(xt, yy - 0.012, zp(0.66)), V(x1, yy - 0.012, zp(1)),
                      V(x1, yy + 0.012, zp(1)), V(xt, yy + 0.012, zp(0.66)))
    xm = (xt + x1) / 2                           # 2 carreaux dans la largeur
    quad("metal", V(xm, y0, zp(0.83) - 0.012), V(xm, y1, zp(0.83) - 0.012),
                  V(xm, y1, zp(0.83) + 0.012), V(xm, y0, zp(0.83) + 0.012))
    for xx, tt in ((x0, 0.0), (x1, 1.0)):        # rives
        box(xx - 0.05, xx + 0.05, y0 - 0.05, y1 + 0.05, zp(tt) - 0.10, zp(tt) + 0.06, "pierre")

    # Deux portes metalliques identiques : l'une au nord, l'autre au sud sur la
    # terrasse meublee, disposees symetriquement par rapport a l'axe.
    # Sous une pente aussi franche, un vantail de 2,10 m ne tient plus que
    # dans le premier cinquieme de l'edicule, contre le mur de nef.
    # Aussi loin vers l'est que la pente le permet : au-dela, le linteau
    # mordrait sur le rampant. Vantail de 0,80 m sur 1,95 m.
    _dc = x0 + (x1 - x0) * 0.37
    for _yf, _ou in ((y1, +1), (y0, -1)):
        box_wall("y", _yf, _ou, _dc - 0.48, _dc + 0.48, z + 0.00, z + 2.03,
                 0.03, "pierrecl")                       # chambranle
        box_wall("y", _yf, _ou, _dc - 0.40, _dc + 0.40, z + 0.03, z + 1.95,
                 0.07, "portemet")                       # vantail
        for _r in range(3):                              # panneaux du vantail
            _zz = z + 0.18 + _r * 0.58
            box_wall("y", _yf, _ou, _dc - 0.32, _dc + 0.32, _zz, _zz + 0.40,
                     0.10, "portemet")
        box_wall("y", _yf, _ou, _dc + 0.25, _dc + 0.33, z + 0.96, z + 1.08,
                 0.12, "metal")                          # poignee



def garden_set(cx, cy, mat_t="metal", mat_s="sombre"):
    """Table ronde et quatre chaises de jardin, aux cotes usuelles :
    plateau 90 cm de diametre a 74 cm, assise a 45 cm, dossier a 90 cm.
    Modelise plutot qu'importe : un modele libre du commerce aurait impose une
    echelle et un format a reconcilier avec ce maillage procedural."""
    cylinder(cx, cy, 0.45, 0.72, 0.755, n=18, mat=mat_t)          # plateau
    cylinder(cx, cy, 0.055, 0.02, 0.72, n=10, mat=mat_t)          # fut
    cylinder(cx, cy, 0.26, 0.02, 0.055, n=14, mat=mat_t)          # pied
    for k in range(4):
        a = math.pi / 2 * k + math.pi / 4
        sx, sy = cx + 0.86 * math.cos(a), cy + 0.86 * math.sin(a)
        box(sx - 0.22, sx + 0.22, sy - 0.22, sy + 0.22, 0.43, 0.475, mat_s)
        for dx in (-0.19, 0.19):
            for dy in (-0.19, 0.19):
                box(sx + dx - 0.018, sx + dx + 0.018, sy + dy - 0.018,
                    sy + dy + 0.018, 0.0, 0.43, mat_s)
        bx, by = cx + 1.06 * math.cos(a), cy + 1.06 * math.sin(a)
        box(bx - 0.22, bx + 0.22, by - 0.03, by + 0.03, 0.475, 0.90, mat_s)


def verriere(x0, x1, ycenter, ze, zr, side=1, w=1.65, h=3.30, t=0.52, ny=8):
    """Verriere de toit : chassis metallique et resille, dans le plan du
    rampant. Plus large que la fenetre de toit, comme la vue aerienne le montre."""
    xm = (x0 + x1) / 2
    xe = x1 if side > 0 else x0
    dx, dz = xe - xm, ze - zr
    L = math.hypot(dx, dz); ux, uz = dx / L, dz / L
    nx, nz = -uz, ux
    if nz < 0:
        nx, nz = -nx, -nz
    cx, cz = xm + ux * L * t, zr + uz * L * t

    def P(a, b, lift):
        return (cx + ux * a + nx * lift, ycenter + b, cz + uz * a + nz * lift)

    for lift, hw, hh, mat in ((0.15, w / 2, h / 2, "metal"),
                              (0.12, w / 2 - 0.07, h / 2 - 0.07, "vitrage")):
        a_ = V(*P(-hh, -hw, lift)); b_ = V(*P(hh, -hw, lift))
        c_ = V(*P(hh, hw, lift)); d_ = V(*P(-hh, hw, lift))
        quad(mat, a_, b_, c_, d_)
        if mat == "metal":
            a0 = V(*P(-hh, -hw, 0)); b0 = V(*P(hh, -hw, 0))
            c0 = V(*P(hh, hw, 0)); d0 = V(*P(-hh, hw, 0))
            quad(mat, a0, b0, b_, a_); quad(mat, b0, c0, c_, b_)
            quad(mat, c0, d0, d_, c_); quad(mat, d0, a0, a_, d_)
    for i in range(1, ny):                       # traverses de la resille
        aa = -h / 2 + h * i / ny
        quad("metal", V(*P(aa - 0.015, -w / 2 + 0.07, 0.13)),
                      V(*P(aa - 0.015,  w / 2 - 0.07, 0.13)),
                      V(*P(aa + 0.015,  w / 2 - 0.07, 0.13)),
                      V(*P(aa + 0.015, -w / 2 + 0.07, 0.13)))
    quad("metal", V(*P(-h / 2 + 0.07, -0.015, 0.13)), V(*P(h / 2 - 0.07, -0.015, 0.13)),
                  V(*P(h / 2 - 0.07, 0.015, 0.13)), V(*P(-h / 2 + 0.07, 0.015, 0.13)))


def blason(axis, plane, out, u, z, r=0.34, mat="blason"):
    """Armoiries en ovale. Rapport 1 : 1,44, releve sur la plaque photographiee
    a l'entree ; ce sont les armes de Francois, MISERANDO ATQUE ELIGENDO."""
    n = 26
    pts = [(u + r * 0.695 * math.cos(2 * math.pi * i / n),
            z + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    idx = [V(*wall_pt(axis, plane, out, p[0], p[1], 0.12)) for p in pts]
    for i in range(1, n - 1):
        F(mat, idx[0], idx[i], idx[i + 1])
    o = [V(*wall_pt(axis, plane, out, p[0], p[1], 0.0)) for p in pts]
    for i in range(n):
        j = (i + 1) % n
        quad("pierre", o[i], o[j], idx[j], idx[i])

# =============================================================== CONSTRUCTION
# --- 1. Bas-cotes : deux niveaux (haut cote facade, bas le long de la nef)
AISLE_W_HOLES, AISLE_E_HOLES = [], []
for (xa, xb) in ((X_W, X_NW), (X_NE, X_E)):
    face = "-x" if xa == X_W else "+x"
    inner = "+x" if xa == X_W else "-x"
    # On garde "+y" sur le bloc haut : a Y_NARTH il fait 15,40 m contre 9,50 m
    # pour le bas-cote, il y a donc un vrai pan a fermer. C'est le bas-cote qui
    # omet son "-y", ce qui evite le doublon sans ouvrir le volume.
    box(xa, xb, Y_F + SETBACK, Y_NARTH, 0, Z_AISLE_HIGH, "mur",
        skip=(face, inner, "-y"))
    box(xa, xb, Y_NARTH, Y_B, 0, Z_AISLE_LOW, "mur",
        skip=(face, inner, "-y", "+y"))
    wall_panel("y", Y_B, +1, xa, xb, 0, Z_AISLE_LOW,
               [((xa + xb) / 2, 2.03, 0, 5.00)], mat="mur")
    nave_side = "right" if xa == X_W else "left"
    cornice(xa, xb, Y_NARTH, Y_B, Z_AISLE_LOW, skip=(nave_side, "front"))
    # Terrasses accessibles : revetement stabilise granuleux, rouge brique
    # un peu plus clair que l'enduit de facade.
    cornice(xa, xb, Y_F + SETBACK, Y_NARTH, Z_AISLE_HIGH, skip=(nave_side,),
            sol="terrasse")
    railing(xa + 0.25, xb - 0.25, Y_F + SETBACK + 0.25, Y_NARTH - 0.25,
            Z_AISLE_HIGH + 0.30)
    if xa == X_NE:
        # Emprise MESUREE dans le scan Flyover complet : l'edicule est plaque
        # contre le mur de nef, et la terrasse ouest ne porte rien.
        _HX1 = xb - 1.25                      # un metre avant le garde-corps
        rooftop_hut(6.47, _HX1, -19.12, -14.61, Z_AISLE_HIGH + 0.30)
        for yr in (-19.12, -14.61):           # retours vers le garde-corps
            railing_run(_HX1, xb - 0.25, yr, yr, Z_AISLE_HIGH + 0.30)
        # salon de jardin sur la partie degagee de la terrasse
        _TZ = Z_AISLE_HIGH + 0.30
        for _gx, _gy in ((8.9, -23.0),):        # un seul salon, cote facade
            for _o in ("t",):
                pass
            _save = len(verts)
            garden_set(_gx, _gy)
            for _i in range(_save, len(verts)):          # on pose le mobilier
                _v = verts[_i]                            # au niveau de la terrasse
                verts[_i] = (_v[0], _v[1], _v[2] + _TZ)

# --- 2. Nef : murs + toit en batiere, de la facade a l'abside
box(X_NW, X_NE, Y_F, Y_B, 0, Z_EAVE, "mur", top=False,
    skip=("-x", "+x", "-y", "+y"))   # les deux pignons sont des panneaux perces
# Bandeau de pignon au-dessus de l'arc triomphal : sans lui il reste une
# fente entre le haut du mur et la naissance du comble, et l'on voit dans
# l'eglise depuis l'exterieur, par-dessus l'abside.
# Pignon d'abside vu de l'exterieur : perce du seul arc triomphal, dont le
# trace suit exactement la rive de la conque (meme rayon, meme naissance).
wall_panel("y", Y_B, +1, X_NW, X_NE, 0, Z_EAVE,
           [(APSE_CX, APSE_R - 0.62, 0, 7.90)], mat="mur", nz=54)
box(X_NW, X_NE, Y_B - 0.08, Y_B - 0.02, Z_EAVE, Z_EAVE + 0.60, "mur")
cornice(X_NW, X_NE, Y_F, Y_B, Z_EAVE, h=0.55, proj=0.5, skip=("front",),
        roof=False)
gable(X_NW - 0.5, X_NE + 0.5, Y_F + 0.35, Y_B, Z_EAVE + 0.55, Z_RIDGE, "tuile", "mur")
coppi(X_NW - 0.5, X_NE + 0.5, Y_F + 0.35, Y_B, Z_EAVE + 0.55, Z_RIDGE)
dentils(X_NW - 0.62, X_NE + 0.62, Y_F + 0.4, Y_B, Z_EAVE - 0.18)
# Deux verrieres sur le rampant est, pres du pignon de facade : c'est ce que
# montre la vue aerienne, des bandes vitrees et non de simples fenetres.
_VY0, _VY1 = -19.12, Y_F + SETBACK + 0.25      # edicule -> garde-corps sud
for _k in (1, 2):
    velux(X_NW - 0.5, X_NE + 0.5, _VY0 + (_VY1 - _VY0) * _k / 3,
          Z_EAVE + 0.55, Z_RIDGE, side=1, w=0.78, h=0.95, t=0.62)

# --- 3. Abside principale + absidioles des bas-cotes
apse(APSE_CX, APSE_CY, APSE_R, APSE_A0, APSE_A1,
     0, Z_APSE_EAVE, Z_EAVE - 0.35, apex_y=Y_B, mat="enduitext")
curved_arcade(APSE_CX, APSE_CY, APSE_R, APSE_A0, APSE_A1, Z_APSE_EAVE - 0.95, 22)
RA = abs(X_NW - X_W) / 2 * 0.92
for cxa in ((X_W + X_NW) / 2, (X_NE + X_E) / 2):
    a0, a1 = math.radians(192), math.radians(-12)
    apse(cxa, Y_B, RA, a0, a1, 0, Z_AISLE_LOW - 0.6, Z_AISLE_LOW - 0.05,
         n=16, apex_y=Y_B, mat="enduitext", mat_roof="tuile")
    curved_arcade(cxa, Y_B, RA, a0, a1, Z_AISLE_LOW - 1.45, 9, hw=0.22, d=0.13)
    curved_windows(cxa, Y_B, RA,
                   [math.radians(150), math.radians(90), math.radians(30)],
                   3.0, 5.6, 0.50, mat="vitrail")

# --- 4. Baies des bas-cotes : huit hautes fenetres cintrees de chaque cote
for (plane, out) in ((X_W, -1), (X_E, +1)):
    HOLES = AISLE_W_HOLES if out < 0 else AISLE_E_HOLES
    y0, y1 = Y_NARTH + 1.6, Y_B - 1.6
    for k in range(8):
        yc = y0 + (y1 - y0) * (k + 0.5) / 8
        HOLES.append((yc, 0.58, 2.40, 5.20))
        recess("x", plane, out, yc, 2.40, 5.20, 0.58, depth=0.24, mat="vitrail")
        glazing("x", plane, out, yc, 2.55, 5.72, 0.58, 0.24, nh=3)
        archivolt("x", plane, out, yc, 2.40, 5.20, 0.58, w=0.22, d=0.24)
    blind_arcade("x", plane, out, Y_NARTH, Y_B, Z_AISLE_LOW - 0.9, 20)
    blind_arcade("x", plane, out, Y_F + SETBACK, Y_NARTH, Z_AISLE_HIGH - 0.9, 11)
    # Quatre travees par flanc et par niveau. Elles n'etaient pas placees sur
    # les pieces : reparties regulierement sur les 16,27 m du corps, l'une
    # tombait dans l'epaisseur du mur mitoyen et la cuisine restait aveugle.
    # On les cale desormais sur le releve DoveVivo :
    #   4,95 — axe de la cuisine a l'ouest, de la salle d'etude a l'est
    #   7,85 — angle nord de la chambre 7 et de la cage d'escalier
    #  11,05 — le couloir, et le second cabinet a l'ouest
    #  13,71 — axe des chambres sur rue
    for lvl in (2.10, 6.90, 11.00):
        for py_bay in (4.95, 7.85, 11.05, 13.71):
            yc = Y_NARTH - py_bay
            HOLES.append((yc, 0.58, lvl, lvl + 1.35))
            recess("x", plane, out, yc, lvl, lvl + 1.35, 0.58, depth=0.18)
            glazing("x", plane, out, yc, lvl + 0.10, lvl + 1.88, 0.58, 0.18, nh=1)
            archivolt("x", plane, out, yc, lvl, lvl + 1.35, 0.58, w=0.20, d=0.20)

# --- 5. Claire-voie de la nef : une large baie a deux jours par travee
NAVE_HOLES = {-1: [], +1: []}
for (plane, out) in ((X_NW, -1), (X_NE, +1)):
    for k in range(4):
        yc = Y_NARTH + (Y_B - Y_NARTH) * (k + 0.5) / 4
        NAVE_HOLES[out].append((yc, 1.25, 9.80, 13.10))
        recess("x", plane, out, yc, 9.80, 13.10, 1.25, depth=0.26, mat="vitrail")
        mullion("x", plane, out, yc, 10.15, 12.95, 1.25, depth=0.26)
        glazing("x", plane, out, yc, 9.95, 14.30, 1.25, 0.26, nh=4)
        archivolt("x", plane, out, yc, 9.80, 13.10, 1.25, w=0.30, d=0.30)
    blind_arcade("x", plane, out, Y_NARTH, Y_B, Z_EAVE - 1.0, 18)

# --- 5b. Faces exterieures percees (remplacent les faces pleines omises)
for pl, ou, HS in ((X_W, -1, AISLE_W_HOLES), (X_E, +1, AISLE_E_HOLES)):
    wall_panel("x", pl, ou, Y_F + SETBACK, Y_NARTH, 0, Z_AISLE_HIGH,
               [h for h in HS if h[0] < Y_NARTH])
    wall_panel("x", pl, ou, Y_NARTH, Y_B, 0, Z_AISLE_LOW,
               [h for h in HS if h[0] >= Y_NARTH])
for pl, ou in ((X_NW, -1), (X_NE, +1)):
    # Le narthex est clos, mais seulement jusqu'a son plancher haut : au-dessus
    # commencent les logements, qui tiennent toute la largeur du corps. Monte
    # jusqu'a l'egout, ce mur coupait en deux la cuisine, la chambre 6, la
    # salle d'etude et le couloir — le releve DoveVivo n'en montre aucun.
    # Le retour de l'avancee de facade, lui, reste plein de fond en comble :
    # c'est la joue de brique du recoin, entre le nu du tiers central et celui
    # des blocs lateraux, en retrait de 50 cm.
    wall_panel("x", pl, ou, Y_F, Y_F + SETBACK, 0, Z_EAVE, [])
    wall_panel("x", pl, ou, Y_F + SETBACK, Y_NARTH, 0, 5.70, [])   # = Z_NSLAB
    # Le long de la nef, en revanche, il n'y a pas de mur sous la claire-voie :
    # c'est l'arcade qui ouvre sur les bas-cotes. Le panneau part donc au-dessus
    # des arcs — ce que l'exterieur ne voit pas, les bas-cotes le masquant.
    wall_panel("x", pl, ou, Y_NARTH, Y_B, 9.30, Z_EAVE, NAVE_HOLES[ou])

# --- 6. Facade sur Via Boncompagni : trois niveaux + pignon
FP, FO = Y_F, -1
FACADE, BLOCKS = [], {}

# 6a. portail a trois voussures sous un portique avance
FACADE.append((XC, 1.55, 0.0, 3.30))
portal("y", FP, FO, XC, 0.0, 3.30, 1.55, depth=0.55)
for w, d in ((0.34, 0.30), (0.30, 0.62), (0.26, 0.94)):
    archivolt("y", FP, FO, XC, 0.0, 3.30, 1.55 + (d - 0.30) * 0.9, w=w, d=d)
for sgn in (-1, 1):                                            # jouees et colonnes
    box(XC + sgn * 2.55, XC + sgn * 2.95, FP - 2.2, FP - 0.02, 0, 4.55, "pierre")
    _cx = XC + sgn * 2.10
    box(_cx - 0.30, _cx + 0.30, FP - 2.30, FP - 1.70, 0, 0.55, "pierre")   # socle
    cylinder(_cx, FP - 2.00, 0.22, 0.55, 3.20)                             # fut
    frustum(_cx, FP - 2.00, 0.22, 0.22, 0.32, 0.32, 3.20, 3.52, "pierre")  # corbeille
    box(_cx - 0.34, _cx + 0.34, FP - 2.34, FP - 1.66, 3.52, 3.68, "pierre")
    box(_cx - 0.26, _cx + 0.26, FP - 2.26, FP - 1.74, 3.68, 4.55, "pierre")
box(XC - 2.95, XC + 2.95, FP - 2.2, FP - 0.02, 4.55, 5.10, "pierre")
gable(XC - 3.1, XC + 3.1, FP - 2.35, FP - 0.02, 5.10, 6.95, "tuile", "pierre")

# 6b. niches maconnees encadrant l'entree, et baies du premier etage
for sgn in (-1, 1):
    FACADE.append((XC + sgn * 4.3, 0.70, 1.30, 3.50))
    recess("y", FP, FO, XC + sgn * 4.3, 1.30, 3.50, 0.70, depth=0.40, mat="pierre")
    archivolt("y", FP, FO, XC + sgn * 4.3, 1.30, 3.50, 0.70, w=0.24, d=0.26)
    blason("y", FP - 0.30, FO, XC + sgn * 4.3, 2.82, r=0.36,
           mat="blason" if sgn < 0 else "blasonb")   # armoiries dans l'alcove

# 6c. frise de feuilles de vigne sur toute la largeur
box(X_W, X_E, FP - 0.34, FP - 0.02, 5.90, 6.55, "pierre")

# 6d. loggia de neuf arches, dans un bandeau de pierre claire
# Le tiers central de la facade porte, entre premier et deuxieme etage, une
# bande d'un calcaire plus clair que la brique ; la frise court sur les deux
# tiers lateraux. Les arches 1, 4-5-6 (d'un seul tenant) et 9 sont vitrees.
# Cotes relevees en rapportant les mesures en pixels a la ligne d'egout.
BAND_Z0, BAND_Z1, BP = 6.65, 10.35, FP - 0.30
_LX0, _LX1, _LN = XC - 4.65, XC + 4.65, 9
_LS = (_LX1 - _LX0) / _LN                             # 1,03 m d'entraxe
BANDH = [(_LX0 + _LS * 0.5, 0.46, 7.15, 8.95),
         (XC, 1.55, 7.15, 8.60),                      # 4-5-6 d'un seul tenant
         (_LX1 - _LS * 0.5, 0.46, 7.15, 8.95)]
# La bande de calcaire ne court pas d'un mur de nef a l'autre : elle encadre
# l'arcature d'une marge de 35 cm. Menee jusqu'a X_NW et X_NE, elle debordait
# de 2,60 m en pierre aveugle, en saillie de 80 cm sur les blocs lateraux.
BAND_X0, BAND_X1 = _LX0 - 0.35, _LX1 + 0.35
box(BAND_X0, BAND_X1, BP, FP - 0.02, BAND_Z0, BAND_Z1, "pierrecl", skip=("-y",))
wall_panel("y", BP, FO, BAND_X0, BAND_X1, BAND_Z0, BAND_Z1, BANDH, mat="pierrecl")
for _u, _hw, _zs, _zp in BANDH:
    recess("y", BP, FO, _u, _zs, _zp, _hw, depth=0.34, mat="vitrage", sill=False)
    _sub = [_u] if _hw < 1.0 else [_u - _LS, _u, _u + _LS]
    for _su in _sub:
        glazing("y", BP, FO, _su, _zs + 0.12, _zp + 0.42, _LS * 0.42, 0.34, nh=3)
blind_arcade("y", BP, FO, _LX0, _LX1, 8.95, _LN, d=0.22)
box(XC - 2.75, XC + 2.75, FP - 0.34, FP - 0.02, BAND_Z1, 11.05, "pierrecl")
blason("y", FP - 0.34, FO, XC, 10.66, r=0.46, mat="pierrecl")   # ecu sculpte
for _k in range(int((BAND_X1 - BAND_X0) / 0.34)):     # cordon de besants
    _bx = BAND_X0 + 0.20 + _k * 0.34
    box(_bx - 0.11, _bx + 0.11, FP - 0.42, BP, BAND_Z1 - 0.28, BAND_Z1 - 0.08,
        "pierrecl")

# 6e. trifora centrale, oculus quadrilobe, deux petites baies, blason
for k in (-1, 0, 1):
    FACADE.append((XC + k * 0.98, 0.40, 11.00, 13.55))
    recess("y", FP, FO, XC + k * 0.98, 11.00, 13.55, 0.40, depth=0.34,
           mat="vitrail", sill=(k == 0))
    glazing("y", FP, FO, XC + k * 0.98, 11.15, 13.90, 0.40, 0.34, nh=3)
    archivolt("y", FP, FO, XC + k * 0.98, 11.00, 13.55, 0.40,
              w=0.16, d=0.26, jambs=False)
for k in (-1, 1):
    cylinder(XC + k * 0.49, FP - 0.30, 0.13, 11.00, 13.55, n=10)
archivolt("y", FP, FO, XC, 11.00, 13.90, 1.95, w=0.30, d=0.16, n=20, jambs=False)
_OCZ = 14.62
opening("y", FP, FO, XC, _OCZ - 0.40, _OCZ - 0.40, 0.40, mat="sombre", depth=0.10)
disc_ring(XC, FP - 0.20, _OCZ, 0.40, 0.53, 0.10, 44)
for _k in range(4):
    _a = math.pi / 2 * _k + math.pi / 4
    disc_ring(XC + 0.235 * math.cos(_a), FP - 0.16,
              _OCZ + 0.235 * math.sin(_a), 0.085, 0.135, 0.075, 20)
box_wall("y", FP, FO, XC - 0.26, XC + 0.26, 15.72, 16.16, 0.26, "pierre")
for sgn in (-1, 1):
    FACADE.append((XC + sgn * 3.5, 0.42, 11.30, 12.70))
    recess("y", FP, FO, XC + sgn * 3.5, 11.30, 12.70, 0.42, depth=0.30, mat="vitrail")
    archivolt("y", FP, FO, XC + sgn * 3.5, 11.30, 12.70, 0.42, w=0.16, d=0.2)
box_wall("y", FP, FO, XC - 0.80, XC + 0.80, 9.95, 10.75, 0.22, "pierre")

# --- 6f. tympan : le tympan EST le pignon du toit, on le derive de la
# geometrie de la toiture pour que rampant et pente de tuile soient la meme
# droite (demi-largeur = nef + debord, base = egout, sommet = faite).
PED_HW   = (X_NE + 0.5) - XC                 # 7.75 m, identique au gable()
PED_BASE = Z_EAVE + 0.55                     # 16.85 m, l'egout du toit
PED_APEX = Z_RIDGE                           # 21.00 m, le faite
box(XC - PED_HW, XC + PED_HW, FP - 0.57, FP - 0.02, 16.35, 16.85, "pierre")
# Decalage parallele de +0.30 m : meme pente, mais la corniche rampante coiffe
# la tuile au lieu de la laisser deborder.
pediment_face(XC, PED_HW, PED_BASE + 0.30, PED_APEX + 0.30, FP, FO, 0.08)


def z_rake(u):
    return PED_APEX - abs(u - XC) / PED_HW * (PED_APEX - PED_BASE)


# corniche rampante, en deux volees depuis le faite
for sgn in (-1, 1):
    ue = XC + sgn * PED_HW
    rake_band(XC, PED_APEX + 0.30, ue, z_rake(ue) + 0.30, FP, FO, 0.42, 0.42)
    rake_dentils(XC, PED_APEX - 0.20, ue, z_rake(ue) - 0.20, FP, FO)

# arcade rampante : sept arches pendantes par rampant, suspendues a la corniche
for sgn in (-1, 1):
    for k in range(7):
        t = (k + 0.5) / 7.0
        uc = XC + sgn * (0.95 + t * (PED_HW * 0.86 - 0.95))
        hw = 0.42
        ztop = z_rake(uc) - 0.30
        zsp = ztop - hw
        archivolt("y", FP, FO, uc, zsp, zsp, hw, w=0.15, d=0.26, n=10, jambs=False)
        for sc in (-1, 1):                       # colonnettes sur consoles
            box_wall("y", FP, FO, uc + sc * hw - 0.07, uc + sc * hw + 0.07,
                     zsp - 1.00, zsp, 0.24, "pierre")

# arche centrale (la quinzieme) : niche a mosaique de Saint Patrick
NB_HW, NB_TOP = 0.55, PED_APEX - 0.95
NB_H = 2.305         # 1.10 / 0.4771 : rapport exact de la mosaique
archivolt("y", FP, FO, XC, NB_TOP - NB_H, NB_TOP - NB_HW, NB_HW, w=0.18, d=0.30, n=12)
opening("y", FP, FO, XC, NB_TOP - NB_H, NB_TOP - NB_HW, NB_HW,
        mat="mosfront", depth=0.16)
# (pas de statue : c'est un panneau de mosaique, cf. photo de facade)

celtic_cross(XC, FP - 0.20, PED_APEX + 0.30, 3.15)
# 6g. blocs conventuels : legerement en retrait, corniche propre
for (xa, xb) in ((X_W, X_NW), (X_NE, X_E)):
    box(xa, xb, FP + SETBACK - 0.45, FP + SETBACK + 0.01,
        Z_AISLE_HIGH - 0.55, Z_AISLE_HIGH, "pierre")
    for lvl in (2.10, 6.90, 11.00):
        for k in range(2):
            uc = xa + (xb - xa) * (k + 0.5) / 2
            BLOCKS.setdefault((xa, xb), []).append((uc, 0.58, lvl, lvl + 1.35))
            recess("y", FP + SETBACK, FO, uc, lvl, lvl + 1.35, 0.58, depth=0.30)
            glazing("y", FP + SETBACK, FO, uc, lvl + 0.10, lvl + 1.88, 0.58, 0.30, nh=1)
            archivolt("y", FP + SETBACK, FO, uc, lvl, lvl + 1.35, 0.58, w=0.20, d=0.20)

# --- 6h. socle de pierre et bandeaux : le batiment ne pose plus a nu
box(X_W - 0.17, X_E + 0.17, Y_F - 0.17, Y_B + 0.17, 0, 1.05, "pierre", top=False)
for _a, _b, _c, _d in ((X_W - 0.17, X_W, Y_F - 0.17, Y_B + 0.17),
                       (X_E, X_E + 0.17, Y_F - 0.17, Y_B + 0.17),
                       (X_W, X_E, Y_F - 0.17, Y_F), (X_W, X_E, Y_B, Y_B + 0.17)):
    box(_a, _b, _c, _d, 0.99, 1.05, "pierre")      # larmier seul, pas de dalle
apse(APSE_CX, APSE_CY, APSE_R + 0.17, APSE_A0, APSE_A1, 0, 1.05, 1.05, n=28, plain=True)
for cxa in ((X_W + X_NW) / 2, (X_NE + X_E) / 2):
    apse(cxa, Y_B, RA + 0.17, math.radians(192), math.radians(-12), 0, 1.05, 1.05, n=16, plain=True)
for (plane, out) in ((X_W, -1), (X_E, +1)):
    box_wall("x", plane, out, Y_NARTH, Y_B, 2.22, 2.40, 0.13, "pierre")
    box_wall("x", plane, out, Y_F + SETBACK, Y_NARTH, 6.72, 6.90, 0.13, "pierre")

# --- 6i. emmarchement du portique
for k in range(2):
    box(XC - 3.5 + k * 0.16, XC + 3.5 - k * 0.16,
        FP - 3.10 + k * 0.34, FP, k * 0.15, 0.15 + k * 0.15, "pierre")
box(XC - 1.30, XC + 1.30, FP, FP + 0.95, 0.15, 0.30, "pierre")   # seuil traversant

# --- 6j. Faces de facade percees (remplacent les faces pleines omises)
wall_panel("y", FP, FO, X_NW, X_NE, 0, Z_EAVE, FACADE, mat="brique")
for (xa, xb), hs in BLOCKS.items():
    wall_panel("y", FP + SETBACK, FO, xa, xb, 0, Z_AISLE_HIGH, hs)


# ================================================================ INTERIEUR
# Trois nefs, six arcades par cote (compte confirme sur place), plafond a
# caissons, abside a conque mosaiquee. Les cotes decoulent du volume exterieur
# deja etabli : la nef interieure tient entre les murs de claire-voie, les
# bas-cotes entre ceux-ci et les murs gouttereaux.

I_FLOOR = 0.30                       # niveau du dallage
AX_W, AX_E = X_NW + 0.40, X_NE - 0.40    # axes des colonnades
I_Y0, I_Y1 = Y_NARTH, Y_B            # du mur de narthex a l'arc triomphal
NBAY = 6
BAY = (I_Y1 - I_Y0) / NBAY           # 5.10 m
Z_BASE, Z_SHAFT, Z_CAP = I_FLOOR + 0.45, I_FLOOR + 5.85, I_FLOOR + 6.60
Z_SPRING = Z_CAP                     # naissance des arcades
Z_AISLE_CEIL = 8.60
Z_CEIL = 15.90                       # sous-face des caissons
APS_R = APSE_R - 0.62                # rayon interieur de l'abside
Z_REVET, Z_INSCR = 7.20, 7.90        # marbre vert, puis bandeau d'inscription


def col_axis(side):
    return AX_W if side < 0 else AX_E


def colonne(cx, cy, mat="marbrecol"):
    """Colonne de marbre a chapiteau corinthien, simplifie mais correct de
    silhouette : base moulurée, fut monolithe, corbeille evasee, tailloir."""
    frustum(cx, cy, 0.44, 0.44, 0.40, 0.40, I_FLOOR, I_FLOOR + 0.14, "pierre")
    frustum(cx, cy, 0.40, 0.40, 0.33, 0.33, I_FLOOR + 0.14, Z_BASE, "pierre")
    cylinder(cx, cy, 0.30, Z_BASE, Z_SHAFT, n=16, mat=mat)
    # corbeille : deux troncs de cone superposes
    frustum(cx, cy, 0.30, 0.30, 0.40, 0.40, Z_SHAFT, Z_SHAFT + 0.42, "pierre")
    frustum(cx, cy, 0.40, 0.40, 0.50, 0.50, Z_SHAFT + 0.42, Z_CAP - 0.12, "pierre")
    box(cx - 0.54, cx + 0.54, cy - 0.54, cy + 0.54, Z_CAP - 0.12, Z_CAP, "pierre")


def pile(cx, cy, mat="marbrecol"):
    """Pile rectangulaire habillee de panneaux de marbre : elle alterne avec
    les colonnes dans l'arcade, comme sur les photos."""
    box(cx - 0.55, cx + 0.55, cy - 0.62, cy + 0.62, I_FLOOR, Z_CAP - 0.12, mat)
    _pz0, _pz1 = I_FLOOR + 0.78, Z_CAP - 1.05          # hauteur des panneaux
    box(cx - 0.40, cx + 0.40, cy - 0.65, cy - 0.62, _pz0, _pz1, "breche",
        skip=("+y",))
    box(cx - 0.40, cx + 0.40, cy + 0.62, cy + 0.65, _pz0, _pz1, "breche",
        skip=("-y",))
    box(cx - 0.58, cx - 0.55, cy - 0.46, cy + 0.46, _pz0, _pz1, "breche",
        skip=("+x",))
    box(cx + 0.55, cx + 0.58, cy - 0.46, cy + 0.46, _pz0, _pz1, "breche",
        skip=("-x",))
    box(cx - 0.63, cx + 0.63, cy - 0.70, cy + 0.70, Z_CAP - 0.12, Z_CAP, "pierre")
    box(cx - 0.60, cx + 0.60, cy - 0.67, cy + 0.67, I_FLOOR, I_FLOOR + 0.30, "pierre")


def arcade_arch(cx, y0, y1, z_spring, mat="enduitint", n=14, depth=1.05):
    """Arc en plein cintre de l'arcade, avec son intrados."""
    r = (y1 - y0) / 2
    yc = (y0 + y1) / 2
    for i in range(n):
        a0 = math.pi * i / n
        a1 = math.pi * (i + 1) / n
        p0 = (yc - r * math.cos(a0), z_spring + r * math.sin(a0))
        p1 = (yc - r * math.cos(a1), z_spring + r * math.sin(a1))
        for dx in (-depth / 2, depth / 2):       # deux joues
            quad(mat, V(cx + dx, p0[0], p0[1]), V(cx + dx, p1[0], p1[1]),
                      V(cx + dx, p1[0], p1[1] + 0.55), V(cx + dx, p0[0], p0[1] + 0.55))
        quad("pierre", V(cx - depth / 2, p0[0], p0[1]), V(cx + depth / 2, p0[0], p0[1]),
                       V(cx + depth / 2, p1[0], p1[1]), V(cx - depth / 2, p1[0], p1[1]))


# --- dallage -------------------------------------------------------------
box(X_W + 0.60, X_E - 0.60, I_Y0, I_Y1, 0.0, I_FLOOR, "solint", bottom=True)
def _flat(mat, pts, dz):
    """Incrustation de dallage. Les couches sont decalees de 2 mm : coplanaires
    elles se disputeraient le meme pixel."""
    idx = [V(px, py, I_FLOOR + dz) for px, py in pts]
    for i in range(1, len(idx) - 1):
        F(mat, idx[0], idx[i], idx[i + 1])


AIS_HW, _AY0, _AY1 = 1.20, I_Y0 + 0.6, I_Y1 - 4.6
for _s in (-1, 1):                                   # bandes de rive
    _u = XC + _s * AIS_HW
    _flat("solmotif", [(_u - 0.11, _AY0), (_u + 0.11, _AY0),
                       (_u + 0.11, _AY1), (_u - 0.11, _AY1)], 0.012)
_pas = 2 * AIS_HW - 0.28
for _k in range(int((_AY1 - _AY0) / _pas)):
    _cy = _AY0 + _pas * (_k + 0.5)
    _r = AIS_HW - 0.30
    _flat("solmotif", [(XC, _cy - _r), (XC + _r, _cy),
                       (XC, _cy + _r), (XC - _r, _cy)], 0.014)   # carre a 45 deg
    _q = _r * 0.52
    _flat("marbrevert", [(XC - _q, _cy - _q), (XC + _q, _cy - _q),
                         (XC + _q, _cy + _q), (XC - _q, _cy + _q)], 0.016)
    _c = _r * 0.20
    _flat("solmotif", [(XC, _cy - _c * 1.6), (XC + _c, _cy),
                       (XC, _cy + _c * 1.6), (XC - _c, _cy)], 0.018)

# --- doublage interieur : sans lui on voit la brique des murs porteurs ----
for xa, xb, _pl, _ou, _hs in ((X_W + 0.58, X_W + 0.63, X_W + 0.63, +1, AISLE_W_HOLES),
                              (X_E - 0.63, X_E - 0.58, X_E - 0.63, -1, AISLE_E_HOLES)):
    box(xa, xb, I_Y0, I_Y1 - 0.02, I_FLOOR, Z_AISLE_CEIL, "enduitint",
        skip=("+x" if _ou > 0 else "-x",))
    _h = [h for h in _hs if I_Y0 < h[0] < I_Y1]
    wall_panel("x", _pl, _ou, I_Y0, I_Y1, I_FLOOR, Z_AISLE_CEIL, _h, mat="enduitint")
    for _yc, _hw, _zs, _zp in _h:
        recess("x", _pl, _ou, _yc, _zs, _zp, _hw, depth=0.26, mat="vitrail", sill=False)
box(XC - 5.60, XC + 5.60, I_Y1 - 0.10, I_Y1 - 0.06, 13.98, 15.88, "arcpeint")
# Bas-cotes : enduit clair jusqu'au plafond des collateraux.
for _xa, _xb, _c in ((X_W + 0.60, X_NW, (X_W + 0.60 + X_NW) / 2),
                     (X_NE, X_E - 0.60, (X_NE + X_E - 0.60) / 2)):
    wall_panel("y", I_Y1 - 0.05, -1, _xa, _xb, I_FLOOR, Z_AISLE_CEIL,
               [(_c, 2.03, I_FLOOR, 5.00)], mat="enduitint", nz=16)
# Nef : tout le pourtour de l'arc triomphal est PEINT, non appareille. Le
# doublage s'arretait a 8,60 m et laissait voir la brique du mur porteur.
wall_panel("y", I_Y1 - 0.05, -1, X_NW, X_NE, I_FLOOR, Z_CEIL,
           [(APSE_CX, APS_R, I_FLOOR, Z_INSCR)], mat="arcsurr", nz=54)
for xa, xb in ((X_W + 0.60, X_NW), (X_NE, X_E - 0.60)):      # bouts de bas-cote
    box(xa, xb, I_Y0 + 0.02, I_Y0 + 0.07, I_FLOOR, Z_AISLE_CEIL, "enduitint")
# Mur de claire-voie vu de la nef : il repose sur l'arcade, donc il commence
# juste au-dessus de la clef des arcs (naissance + rayon) et monte au plafond.
# Sans lui on voit la brique du mur porteur par l'interieur.
Z_ARCTOP = Z_SPRING + (BAY - 1.10) / 2 + 0.55
for side in (-1, 1):
    ax = AX_W if side < 0 else AX_E
    _inn = ax + (0.32 if side < 0 else -0.32)
    # 2 cm sous le dessus des caissons et en retrait des deux pignons : arase
    # a leur nu, ce doublage leur opposait une face coplanaire.
    box(ax - 0.32, ax + 0.32, I_Y0 + 0.02, I_Y1 - 0.02, Z_ARCTOP, Z_CEIL + 0.40,
        "enduitint", skip=("+x" if side < 0 else "-x",))
    wall_panel("x", _inn, -side, I_Y0, I_Y1, Z_ARCTOP, Z_CEIL + 0.42,
               NAVE_HOLES[side], mat="enduitint")
    for _yc, _hw, _zs, _zp in NAVE_HOLES[side]:       # ebrasement vu de la nef
        recess("x", _inn, -side, _yc, _zs, _zp, _hw, depth=0.30,
               mat="vitrail", sill=False)
    # ecoincons entre les arcs, sous ce mur
    for k in range(NBAY + 1):
        cy = I_Y0 + BAY * k
        box(ax - 0.32, ax + 0.32, cy - 0.58, cy + 0.58, Z_SPRING, Z_ARCTOP, "enduitint")

# --- colonnades : cinq supports libres par cote, alternant pile et colonne
for side in (-1, 1):
    cx = col_axis(side)
    for k in range(NBAY + 1):
        cy = I_Y0 + BAY * k
        if k in (0, NBAY):
            # Les dosserets d'extremite doivent mourir DANS le mur : centres
            # sur lui, ils ressortaient de 55 cm et faisaient deux grands
            # rectangles blancs entre l'abside et les absidioles.
            _dy0 = cy + 0.02 if k == 0 else cy - 1.10
            _dy1 = cy + 1.10 if k == 0 else cy - 0.02
            box(cx - 0.62, cx + 0.62, _dy0, _dy1, I_FLOOR, Z_CAP, "enduitint")
        elif k % 2 == 1:
            colonne(cx, cy)
        else:
            pile(cx, cy)
    for k in range(NBAY):                     # six arcades
        arcade_arch(cx, I_Y0 + BAY * k + 0.55, I_Y0 + BAY * (k + 1) - 0.55, Z_SPRING)

# --- lampes suspendues aux piles, comme sur les photographies -------------
def lampe(cx, cy, z_haut, h=1.55):
    """Globe d'opaline au bout d'une tige, accroche a hauteur de chapiteau."""
    cylinder(cx, cy, 0.022, z_haut - h, z_haut, n=6, mat="metal")
    zb = z_haut - h
    frustum(cx, cy, 0.05, 0.05, 0.15, 0.15, zb, zb + 0.09, "opaline")
    frustum(cx, cy, 0.15, 0.15, 0.15, 0.15, zb + 0.09, zb + 0.20, "opaline")
    frustum(cx, cy, 0.15, 0.15, 0.05, 0.05, zb + 0.20, zb + 0.29, "opaline")


def rosette(cx, cy, z, r, mat="dorure", n=8):
    """Rosace sculptee au fond d'un caisson."""
    pts = [V(cx + r * math.cos(2 * math.pi * i / n + 0.39),
             cy + r * math.sin(2 * math.pi * i / n + 0.39), z) for i in range(n)]
    for i in range(1, n - 1):
        F(mat, pts[0], pts[i], pts[i + 1])


for side in (-1, 1):
    _lx = col_axis(side) + (0.95 if side < 0 else -0.95)
    for k in range(1, NBAY):
        lampe(_lx, I_Y0 + BAY * k, Z_CAP - 0.25)

# --- plafond a caissons ---------------------------------------------------
NCX, NCY = 5, int((I_Y1 - I_Y0) / 1.70)
for i in range(NCX):
    for j in range(NCY):
        x0 = AX_W + (AX_E - AX_W) * i / NCX
        x1 = AX_W + (AX_E - AX_W) * (i + 1) / NCX
        y0 = I_Y0 + (I_Y1 - I_Y0) * j / NCY
        y1 = I_Y0 + (I_Y1 - I_Y0) * (j + 1) / NCY
        box(x0 + 0.13, x1 - 0.13, y0 + 0.13, y1 - 0.13,
            Z_CEIL + 0.02, Z_CEIL + 0.30, "caisson")          # fond du caisson
        box(x0, x1, y0, y1, Z_CEIL, Z_CEIL + 0.02, "caisson", top=False)
        rosette((x0 + x1) / 2, (y0 + y1) / 2, Z_CEIL + 0.288,
                min(x1 - x0, y1 - y0) * 0.21)
box(AX_W - 0.1, AX_E + 0.1, I_Y0, I_Y1, Z_CEIL + 0.30, Z_CEIL + 0.42, "caisson")

# --- plafonds des bas-cotes ----------------------------------------------
for (xa, xb) in ((X_W + 0.60, AX_W - 0.62), (AX_E + 0.62, X_E - 0.60)):
    box(xa, xb, I_Y0, I_Y1 - 0.02, Z_AISLE_CEIL, Z_AISLE_CEIL + 0.10, "enduitint",
        top=False)

# --- abside : revetement de marbre vert, bandeau, conque mosaiquee --------
_a0, _a1 = math.radians(180), math.radians(0)
_lo = [V(*p) for p in arc_pts(APSE_CX, Y_B, APS_R, _a0, _a1, 26, I_FLOOR + 0.55)]
_hi = [V(*p) for p in arc_pts(APSE_CX, Y_B, APS_R, _a0, _a1, 26, Z_REVET)]
for i in range(26):
    quad("marbrevert", _lo[i], _lo[i + 1], _hi[i + 1], _hi[i])
_i0 = [V(*p) for p in arc_pts(APSE_CX, Y_B, APS_R, _a0, _a1, 26, Z_REVET)]
_i1 = [V(*p) for p in arc_pts(APSE_CX, Y_B, APS_R, _a0, _a1, 26, Z_INSCR)]
for i in range(26):
    quad("inscript", _i0[i], _i0[i + 1], _i1[i + 1], _i1[i])
# conque : demi-coupole, portee par le materiau texture
NR, NH = 26, 9
for j in range(NH):
    t0, t1 = j / NH, (j + 1) / NH
    r0, z0 = APS_R * math.cos(t0 * math.pi / 2), Z_INSCR + (APS_R) * math.sin(t0 * math.pi / 2)
    r1, z1 = APS_R * math.cos(t1 * math.pi / 2), Z_INSCR + (APS_R) * math.sin(t1 * math.pi / 2)
    A = arc_pts(APSE_CX, Y_B, r0, _a0, _a1, NR, z0)
    B = arc_pts(APSE_CX, Y_B, r1, _a0, _a1, NR, z1)
    for i in range(NR):
        quad("mosabside", V(*A[i]), V(*A[i + 1]), V(*B[i + 1]), V(*B[i]))

# arc triomphal
for sgn in (-1, 1):
    box(APSE_CX + sgn * APS_R, APSE_CX + sgn * (APS_R + 0.95),
        Y_B - 0.55, Y_B + 0.55, I_FLOOR, Z_INSCR + APS_R, "marbrecol")
archivolt("y", Y_B + 0.55, +1, APSE_CX, I_FLOOR, Z_INSCR, APS_R,
          w=0.55, d=0.35, n=22, mat="pierre", jambs=False)

# --- presbytere : emmarchement, autel, retable ---------------------------
for k in range(3):
    box(APSE_CX - 5.6 + k * 0.35, APSE_CX + 5.6 - k * 0.35,
        Y_B - 4.2 + k * 0.45, Y_B + 5.0, I_FLOOR + k * 0.16, I_FLOOR + 0.16 + k * 0.16, "solint")
box(APSE_CX - 1.5, APSE_CX + 1.5, Y_B - 1.4, Y_B - 0.5,
    I_FLOOR + 0.48, I_FLOOR + 1.42, "pierre")                # autel

# --- absidioles : chapelle de la Madone et chapelle du Sacre-Coeur --------
# Relevees sur les deux cliches Wikimedia : conque peinte en bleu de nuit seme
# d'or sous un arc moulure, retable de marbre blanc a arcature, autel a devant
# de marbre rouge, le tout sur un emmarchement de deux degres.
def chapelle(cxa, y0, r, z_spring, z_top):
    a0, a1 = math.radians(180), math.radians(0)
    _lo = [V(*q) for q in arc_pts(cxa, y0, r, a0, a1, 18, I_FLOOR)]
    _hi = [V(*q) for q in arc_pts(cxa, y0, r, a0, a1, 18, z_spring)]
    for i in range(18):
        quad("pierrecl", _lo[i], _lo[i + 1], _hi[i + 1], _hi[i])
    NR, NH = 18, 7
    for j in range(NH):
        t0, t1 = j / NH, (j + 1) / NH
        r0 = r * math.cos(t0 * math.pi / 2)
        r1 = r * math.cos(t1 * math.pi / 2)
        z0 = z_spring + (z_top - z_spring) * math.sin(t0 * math.pi / 2)
        z1 = z_spring + (z_top - z_spring) * math.sin(t1 * math.pi / 2)
        A = arc_pts(cxa, y0, r0, a0, a1, NR, z0)
        B = arc_pts(cxa, y0, r1, a0, a1, NR, z1)
        for i in range(NR):
            quad("nuit", V(*A[i]), V(*A[i + 1]), V(*B[i + 1]), V(*B[i]))
    archivolt("y", y0 - 0.08, -1, cxa, I_FLOOR, z_spring, r,
              w=0.36, d=0.22, n=20, mat="caisson")
    for k in range(2):                                  # emmarchement
        box(cxa - 1.95 + k * 0.26, cxa + 1.95 - k * 0.26, y0 - 0.9 + k * 0.34,
            y0 + r * 0.9, I_FLOOR + k * 0.15, I_FLOOR + 0.15 + k * 0.15, "marbrevert")
    _b = I_FLOOR + 0.30
    box(cxa - 1.55, cxa + 1.55, y0 + 0.95, y0 + 1.30, _b, _b + 3.30, "pierrecl")
    box(cxa - 0.52, cxa + 0.52, y0 + 0.91, y0 + 0.95, _b + 1.35, _b + 2.55, "dorure")
    box(cxa - 1.30, cxa + 1.30, y0 + 0.40, y0 + 0.95, _b, _b + 0.98, "pierrecl")
    box(cxa - 1.34, cxa + 1.34, y0 + 0.36, y0 + 0.99, _b + 0.98, _b + 1.10, "pierrecl")
    box(cxa - 1.10, cxa + 1.10, y0 + 0.36, y0 + 0.40, _b + 0.12, _b + 0.90, "marbrevert")


for _cx in ((X_W + 0.60 + X_NW) / 2, (X_NE + X_E - 0.60) / 2):
    chapelle(_cx, I_Y1, 2.03, 5.00, 7.10)
    lampe(_cx, I_Y1 - 2.2, Z_AISLE_CEIL - 0.35, h=1.7)
for _sg in (-1, 1):                                   # deux lampes au choeur
    lampe(APSE_CX + _sg * 3.4, I_Y1 - 1.4, Z_INSCR + 2.4, h=2.3)

# --- chemin de croix et confessionnaux, entre les baies des bas-cotes -----
for _pl, _ou in ((X_W + 0.63, +1), (X_E - 0.63, -1)):
    _y0, _y1 = Y_NARTH + 1.6, Y_B - 1.6
    for k in range(7):                                  # sept stations par cote
        _yc = _y0 + (_y1 - _y0) * (k + 1) / 8
        box_wall("x", _pl, _ou, _yc - 0.30, _yc + 0.30, 1.60, 2.28, 0.06, "caisson")
        box_wall("x", _pl, _ou, _yc - 0.23, _yc + 0.23, 1.67, 2.21, 0.09, "pierrecl")
    for k in (1, 5):                                    # deux confessionnaux
        _yc = _y0 + (_y1 - _y0) * (k + 0.5) / 8
        _d = 0.78
        box_wall("x", _pl, _ou, _yc - 0.62, _yc + 0.62, I_FLOOR, I_FLOOR + 2.25,
                 _d, "caisson")
        box_wall("x", _pl, _ou, _yc - 0.70, _yc + 0.70, I_FLOOR + 2.25,
                 I_FLOOR + 2.45, _d + 0.10, "bois")

# --- bancs ----------------------------------------------------------------
for side in (-1, 1):
    x0 = AX_W + 1.0 if side < 0 else XC + 0.9
    x1 = XC - 0.9 if side < 0 else AX_E - 1.0
    nrow = int((I_Y1 - 5.0 - (I_Y0 + 1.5)) / 0.95)
    for k in range(nrow):
        yy = I_Y0 + 1.5 + k * 0.95
        box(x0, x1, yy, yy + 0.07, I_FLOOR + 0.44, I_FLOOR + 1.04, "bois")    # dossier
        box(x0, x1, yy + 0.07, yy + 0.50, I_FLOOR + 0.42, I_FLOOR + 0.50, "bois")  # assise
        for xe in (x0 + 0.04, x1 - 0.12):                                     # joues
            box(xe, xe + 0.08, yy, yy + 0.50, I_FLOOR, I_FLOOR + 0.50, "bois")

# ================================================ NARTHEX ET CONTRE-FACADE
# Le corps sur rue abrite des appartements a l'etage ; son rez-de-chaussee
# forme l'atrium de l'eglise. Deux cliches Wikimedia le documentent (Atrio ;
# vestibolo P1230022) : salle voutee d'aretes sur piles rectangulaires ocre a
# socle et imposte de marbre sombre, dallage de marbre blanc raye de bandes
# vert-gris avec, par travee, un cadre a angles coupes. Le vestibule compte
# trois travees de front, la porte au milieu : la trame est donc 3 x 3, ce qui
# donne les quatre piles libres qu'on voit sur les photographies.

N_X0, N_X1 = X_NW + 0.05, X_NE - 0.05        # 14.40 m dans oeuvre
N_Y0, N_Y1 = Y_F + 0.90, Y_NARTH - 0.45      # 15.42 m
NBX = NBY = 3
NPX, NPY = (N_X1 - N_X0) / NBX, (N_Y1 - N_Y0) / NBY      # 4.80 x 5.14 m
Z_NSPR, Z_NRISE = 3.55, 1.85                 # naissance, puis fleche
Z_NSLAB = 5.70            # plancher du premier : allege a 6,90, soit 1,20 m
P_HW, P_PROJ, SOC_H, IMP_H = 0.46, 0.13, 1.12, 0.26


def groin_vault(x0, x1, y0, y1, zs, rise, mat="enduitint", n=8):
    """Voute d'aretes. Deux berceaux se croisent : en tout point la voute suit
    le PLUS HAUT des deux profils, et les aretes tombent sur les diagonales.
    (Prendre le plus bas donnerait l'intersection des deux cylindres, qui
    s'ecrase a la naissance et n'a plus ni arc doubleau ni arete.)"""
    def P(i, j):
        x, y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n
        u, v = 2 * i / n - 1, 2 * j / n - 1
        z = zs + rise * max(math.sqrt(max(0.0, 1 - u * u)),
                            math.sqrt(max(0.0, 1 - v * v)))
        return V(x, y, z)
    G = [[P(i, j) for j in range(n + 1)] for i in range(n + 1)]
    for i in range(n):
        for j in range(n):
            quad(mat, G[i][j], G[i + 1][j], G[i + 1][j + 1], G[i][j + 1])


def vault_rib(axis, line, a0, a1, zs, rise, hw=0.33, drop=0.26, n=14,
              mat="ocre"):
    """Arc doubleau : bande cintree en saillie sous la voute. Le decrochement
    'drop' evite que la bande et la voute soient coplanaires."""
    S = ((lambda s, w, z: V(line + s, w, z)) if axis == "x"
         else (lambda s, w, z: V(w, line + s, z)))
    prof = []
    for i in range(n + 1):
        u = 2 * i / n - 1
        prof.append((a0 + (a1 - a0) * i / n,
                     zs + rise * math.sqrt(max(0.0, 1 - u * u)) - drop))
    for i in range(n):
        (wa, za), (wb, zb) = prof[i], prof[i + 1]
        quad(mat, S(-hw, wa, za), S(hw, wa, za), S(hw, wb, zb), S(-hw, wb, zb))
        for s in (-hw, hw):
            quad(mat, S(s, wa, za), S(s, wb, zb),
                      S(s, wb, zb + drop), S(s, wa, za + drop))


def narthex_pier(cx, cy, zt):
    """Pile a socle de marbre sombre, fut ocre a pilastres engages, imposte."""
    box(cx - P_HW - 0.07, cx + P_HW + 0.07, cy - P_HW - 0.07, cy + P_HW + 0.07,
        I_FLOOR, I_FLOOR + SOC_H, "ardoise")
    box(cx - P_HW, cx + P_HW, cy - P_HW, cy + P_HW,
        I_FLOOR + SOC_H, zt - IMP_H, "ocre")
    for dx, dy, skip in ((-1, 0, "+x"), (1, 0, "-x"), (0, -1, "+y"), (0, 1, "-y")):
        ax, ay = cx + dx * (P_HW + P_PROJ / 2), cy + dy * (P_HW + P_PROJ / 2)
        hx = P_PROJ / 2 if dx else 0.30
        hy = P_PROJ / 2 if dy else 0.30
        box(ax - hx, ax + hx, ay - hy, ay + hy, I_FLOOR + SOC_H, zt - IMP_H,
            "ocre", skip=(skip,))
    box(cx - P_HW - 0.11, cx + P_HW + 0.11, cy - P_HW - 0.11, cy + P_HW + 0.11,
        zt - IMP_H, zt, "ardoise")


def narthex_respond(cx, cy, zt, nx, ny):
    """Dosseret engage dans un mur, de normale (nx, ny) dirigee vers la salle."""
    hx = 0.17 if nx else 0.42
    hy = 0.17 if ny else 0.42
    ax, ay = cx + nx * 0.17, cy + ny * 0.17
    skip = ("-x" if nx > 0 else "+x") if nx else ("-y" if ny > 0 else "+y")
    box(ax - hx, ax + hx, ay - hy, ay + hy, I_FLOOR, I_FLOOR + SOC_H,
        "ardoise", skip=(skip,))
    box(ax - hx, ax + hx, ay - hy, ay + hy, I_FLOOR + SOC_H, zt - IMP_H,
        "ocre", skip=(skip,))
    box(ax - hx - 0.09, ax + hx + 0.09, ay - hy - 0.09, ay + hy + 0.09,
        zt - IMP_H, zt, "ardoise", skip=(skip,))


def inlay(x0, x1, y0, y1, mat):
    """Incrustation de dallage : une seule face, posee sur le marbre."""
    z = I_FLOOR + 0.012
    quad(mat, V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z))


def tunnel_y(y0, y1, u, z_sill, z_spring, hw, mat="enduitint", n=12):
    """Ebrasement d'une baie traversante dans un mur de normale y."""
    prof = [(u - hw, z_sill)]
    for i in range(n + 1):
        a = math.pi - math.pi * i / n
        prof.append((u + hw * math.cos(a), z_spring + hw * math.sin(a)))
    prof.append((u + hw, z_sill))
    A = [V(p[0], y0, p[1]) for p in prof]
    B = [V(p[0], y1, p[1]) for p in prof]
    for k in range(len(prof) - 1):
        quad(mat, A[k], A[k + 1], B[k + 1], B[k])


# --- dallage du narthex : marbre blanc, bandes et cadres a angles coupes ---
box(N_X0, N_X1, N_Y0, N_Y1, 0.0, I_FLOOR, "solint", bottom=True)
apse(APSE_CX, APSE_CY, APSE_R - 0.5, APSE_A0, APSE_A1, 0.0, I_FLOOR,
     I_FLOOR, n=24, plain=True)                 # dallage du choeur
for i in range(NBX + 1):                     # bandes sur les lignes de trame
    xg = N_X0 + NPX * i
    inlay(max(N_X0, xg - 0.31), min(N_X1, xg + 0.31), N_Y0, N_Y1, "solbande")
for j in range(NBY + 1):
    yg = N_Y0 + NPY * j
    inlay(N_X0, N_X1, max(N_Y0, yg - 0.31), min(N_Y1, yg + 0.31), "solbande")
for i in range(NBX):                         # un cadre par travee
    for j in range(NBY):
        xa, xb = N_X0 + NPX * i + 1.15, N_X0 + NPX * (i + 1) - 1.15
        ya, yb = N_Y0 + NPY * j + 1.25, N_Y0 + NPY * (j + 1) - 1.25
        inlay(xa, xb, ya, ya + 0.30, "solbande")
        inlay(xa, xb, yb - 0.30, yb, "solbande")
        inlay(xa, xa + 0.30, ya + 0.30, yb - 0.30, "solbande")
        inlay(xb - 0.30, xb, ya + 0.30, yb - 0.30, "solbande")

# --- piles, dosserets, voutes et doubleaux --------------------------------
for i in range(NBX + 1):
    for j in range(NBY + 1):
        cx, cy = N_X0 + NPX * i, N_Y0 + NPY * j
        ex, ey = (i == 0) - (i == NBX), (j == 0) - (j == NBY)
        if ex == 0 and ey == 0:
            narthex_pier(cx, cy, Z_NSPR)
        elif ex and ey:
            narthex_respond(cx, cy, Z_NSPR, ex, 0)
        else:
            narthex_respond(cx, cy, Z_NSPR, ex, ey)
for i in range(NBX):
    for j in range(NBY):
        groin_vault(N_X0 + NPX * i, N_X0 + NPX * (i + 1),
                    N_Y0 + NPY * j, N_Y0 + NPY * (j + 1), Z_NSPR, Z_NRISE)
for i in range(NBX + 1):                     # doubleaux transversaux
    for j in range(NBY):
        vault_rib("x", N_X0 + NPX * i, N_Y0 + NPY * j, N_Y0 + NPY * (j + 1),
                  Z_NSPR, Z_NRISE)
for j in range(NBY + 1):                     # doubleaux longitudinaux
    for i in range(NBX):
        vault_rib("y", N_Y0 + NPY * j, N_X0 + NPX * i, N_X0 + NPX * (i + 1),
                  Z_NSPR, Z_NRISE)

for i in range(NBX):                                  # une lampe par travee
    for j in range(NBY):
        lampe(N_X0 + NPX * (i + 0.5), N_Y0 + NPY * (j + 0.5),
              Z_NSPR + 0.35, h=1.15)

# --- parois du narthex : enduit, socle de marbre, niches a portes ---------
for pl, ou in ((N_X0, +1), (N_X1, -1)):
    box_wall("x", pl, ou, N_Y0, N_Y1, I_FLOOR, Z_NSLAB, 0.05, "enduitint")
    box_wall("x", pl, ou, N_Y0, N_Y1, I_FLOOR, I_FLOOR + SOC_H, 0.09, "ardoise")
    for j in range(NBY):                     # une niche par travee
        cy = N_Y0 + NPY * (j + 0.5)
        recess("x", pl, ou, cy, I_FLOOR, I_FLOOR + 1.85, 0.92,
               depth=0.30, mat="bois", sill=False)
        archivolt("x", pl, ou, cy, I_FLOOR, I_FLOOR + 1.85, 0.92,
                  w=0.20, d=0.09, mat="ocre")
wall_panel("y", N_Y0, +1, N_X0, N_X1, I_FLOOR, Z_NSLAB,
           [(XC, 1.05, I_FLOOR, 3.20)], mat="enduitint")
box_wall("y", N_Y0, +1, N_X0, N_X1, I_FLOOR, I_FLOOR + SOC_H, 0.09, "ardoise")
# Plancher haut de l'atrium. Il ne court plus que jusqu'au mur mitoyen : au
# dela, c'est la dalle du premier etage du logement qui le porte, et cette
# chape debordante recouvrait les revetements de sol du plan.
box(N_X0, N_X1, Y_NARTH - 2.08, N_Y1, Z_NSLAB, Z_NSLAB + 0.12, "enduitint")

# --- contre-facade : trois baies au sol, tribune a trois arcades au-dessus
# Releve photographique (vue depuis le choeur, cliche controfacciata) : en
# rapportant les hauteurs au plafond a caissons, les arcs du bas culminent a
# 4.60 m, la corniche est a 6.7 m, le garde-corps de la tribune monte a 9.25 m
# et les arcades de la tribune naissent a 11.75 m.
CF_Y, NF_Y = N_Y1, Y_NARTH
Z_GAL, Z_PAR, Z_GSPR = 7.40, 9.25, 11.75
CF_LOW = [(XC, 1.45, I_FLOOR, I_FLOOR + 2.85),
          (XC - 4.40, 1.80, I_FLOOR, I_FLOOR + 2.50),
          (XC + 4.40, 1.80, I_FLOOR, I_FLOOR + 2.50)]
CF_GAL = [(XC + dx, 1.42, Z_GAL, Z_GSPR) for dx in (-3.35, 0.0, 3.35)]
CF_HOLES = CF_LOW + CF_GAL
for pl, ou in ((NF_Y, +1), (CF_Y, -1)):
    wall_panel("y", pl, ou, X_NW, X_NE, I_FLOOR, Z_CEIL, CF_HOLES,
               mat="enduitint")
for uc, hw, zs, zp in CF_HOLES:
    tunnel_y(CF_Y, NF_Y, uc, zs, zp, hw)
    for pl, ou in ((NF_Y, +1), (CF_Y, -1)):
        archivolt("y", pl, ou, uc, zs, zp, hw, w=0.24, d=0.10, mat="pierre",
                  jambs=False)
box_wall("y", NF_Y, +1, X_NW + 0.1, X_NE - 0.1, 6.62, 6.98, 0.30, "pierre")

# tribune : plancher, garde-corps, la Cene peinte devant, colonnettes
box(XC - 5.45, XC + 5.45, Y_NARTH - 2.08, NF_Y + 1.65, Z_GAL - 0.12, Z_GAL, "solint")
box(XC - 5.45, XC + 5.45, NF_Y + 1.43, NF_Y + 1.65, Z_GAL, Z_PAR, "enduitint")

for dx in (-1.675, 1.675):
    box(XC + dx - 0.20, XC + dx + 0.20, NF_Y + 0.06, NF_Y + 0.46,
        Z_PAR, Z_PAR + 0.14, "pierre")                       # base
    cylinder(XC + dx, NF_Y + 0.26, 0.145, Z_PAR + 0.14, Z_GSPR - 0.38,
             n=14, mat="pierrecl")                           # fut elance
    frustum(XC + dx, NF_Y + 0.26, 0.145, 0.145, 0.215, 0.215,
            Z_GSPR - 0.38, Z_GSPR - 0.14, "pierre")          # corbeille
    box(XC + dx - 0.24, XC + dx + 0.24, NF_Y + 0.02, NF_Y + 0.50,
        Z_GSPR - 0.14, Z_GSPR, "pierre")                     # tailloir
# Fond de tribune : les baies ouvrent sur le premier etage du corps sur rue.
# Sans ce panneau on voit la brique du parement exterieur au travers.
# La Cene est peinte sur le mur du FOND de la tribune, derriere les colonnes.
# Le fond etait un panneau sombre : c'est un vrai mur d'enduit clair, montant
# du dallage au plafond.
# Ce fond ne descend qu'au plancher du premier etage : sous lui il y a
# l'atrium, et un mur pleine hauteur coupait le narthex en deux.
# Le releve DoveVivo donne la position exacte de ce fond : c'est le mur
# mitoyen entre l'eglise et le corps de logis, a y = -11,08. La tribune y
# gagne d'etre moins profonde de 1,47 m — elle etait dessinee trop creuse.
CF_FOND = Y_NARTH - 2.08
box(X_NW + 0.03, X_NE - 0.03, CF_FOND - 0.91, CF_FOND, Z_NSLAB, Z_CEIL,
    "enduitint")
# 7,20 m de large : la toile occupe presque toute la largeur de la tribune
box(XC - 3.60, XC + 3.60, CF_FOND + 0.01, CF_FOND + 0.05, 9.28, 11.53, "tableau")


# ======================================== ETAGES DU CORPS SUR RUE
# Releve DoveVivo : PIANO PRIMO / SECONDO / TERZO, Via Boncompagni 31.
# Les trois planches sont vectorielles et a l'echelle ; on les cale sur
# l'emprise OSM en posant 25,44 m sur les 562,3 points de la facade, soit
# 22,104 pt/m. La profondeur qui en decoule, 14,69 m, place le mur mitoyen
# avec l'eglise a y = -11,08 : le corps de logis est donc plus court que le
# narthex de 2,08 m, et c'est cette bande qui porte la tribune de la Cene.
# Controle : 23,52 x 12,52 = 294 m2 de surface interieure, l'annonce en
# declare 290. Une chambre relevee (4A, 3,72 x 3,60 + bow-window) fait 15 m2,
# exactement la surface annoncee.
#
# Repere du plan : px vers l'est depuis le mur ouest, py vers la rue depuis
# le nu exterieur du mitoyen.  Toutes les cotes ci-dessous sont relevees.
PX0, PX1 = 0.94, 24.46            # nus interieurs ouest / est
PY0, PY1 = 2.99, 15.51            # nus interieurs mitoyen / facade
PY_MIT   = 2.53                   # axe du mur mitoyen (e = 0.91)
PY_NORD  = 3.34                   # nu interieur de la bande nord
PY_SPINE = 10.18                  # axe du refend longitudinal (e = 0.40)
PY_COUL  = 11.84                  # axe du mur de couloir (e = 0.14)

Z_ET1, Z_ET2, Z_TOITURE = Z_NSLAB, 9.80, Z_AISLE_HIGH
Z_ET3 = Z_AISLE_HIGH + 0.30       # sol des terrasses et du dernier logement
DALLE = 0.22
# 4 cm de plus : arasees au nu de la dalle, les cloisons papillotaient avec.
PH1 = Z_ET2 - Z_ET1 - DALLE + 0.04
PH2 = Z_TOITURE - Z_ET2 - DALLE
# Le logement du troisieme est loge SOUS le rampant de la nef. Le rampant
# descend a 18,10 m au droit de ses murs pignons (21,00 au faite, 16,85 a
# l'egout, demi-portee 7,75) : au-dela, les cloisons perçaient la couverture.
PH3 = 17.95 - Z_ET3


def _mx(px):
    return X_W + px


def _my(py):
    return Y_NARTH - py


def pbox(px0, py0, px1, py1, z0, z1, mat, **kw):
    """Boite donnee dans le repere du plan d'agence."""
    box(_mx(px0), _mx(px1), _my(py1), _my(py0), z0, z1, mat, **kw)


# Vue en plan : un mur coupe doit se lire plein et sombre. Le maillage n'a pas
# de capot de coupe, et une face verticale vue de dessus ne couvre aucun pixel.
# On noie donc dans l'epaisseur de chaque mur une plaque horizontale, a 1,10 m
# du sol : invisible de partout, elle apparait des que la coupe passe au-dessus.
POCHE0, POCHE1 = 1.10, 1.16


def poche(px0, py0, px1, py1, z):
    pbox(px0, py0, px1, py1, z + POCHE0, z + POCHE1, "poche")


def poche_xy(x0, y0, x1, y1, z):
    box(x0, x1, y0, y1, z + POCHE0, z + POCHE1, "poche")


# ------------------------------------------------------- nomenclature du plan
PIECES = []


def piece(niv, nom, px0, py0, px1, py1, z, sol=None, hp=None):
    """Enregistre une piece : elle sert au plan 2D du visualiseur, et pose
    son revetement de sol."""
    PIECES.append({"l": niv, "n": nom,
                   "x0": _mx(px0), "x1": _mx(px1),
                   "y0": _my(py1), "y1": _my(py0), "z": z,
                   "a": round((px1 - px0) * (py1 - py0), 1)})
    if sol:
        pbox(px0, py0, px1, py1, z, z + 0.015, sol)
    if hp:
        lustre(px0, py0, px1, py1, z, hp,
               n=max(1, int((px1 - px0) / 4.2)))


def piece_xy(niv, nom, x0, y0, x1, y1, z):
    PIECES.append({"l": niv, "n": nom, "x0": x0, "x1": x1,
                   "y0": y0, "y1": y1, "z": z,
                   "a": round((x1 - x0) * (y1 - y0), 1)})


# ---------------------------------------------------------------- plancher
def plancher_troue(z, trous, mat="solint"):
    """Dalle sur l'emprise, evidee des tremies."""
    # 2 cm en retrait des nus : la tranche de dalle tombait sinon dans le plan
    # du mur mitoyen et dans celui de la facade.
    bornes = sorted({PY0 - 0.89, PY1 + 1.24}
                    | {v for t in trous for v in (t[1], t[3])})
    for ya, yb in zip(bornes, bornes[1:]):
        if yb - ya < 1e-6:
            continue
        ym = (ya + yb) / 2
        spans = sorted((t[0], t[2]) for t in trous if t[1] <= ym <= t[3])
        # La dalle penetre de 6 cm dans les gouttereaux : arasee a leur nu,
        # sa tranche etait coplanaire avec eux et l'ecran papillotait.
        cur = 0.06
        for a, b in spans:
            if a > cur:
                pbox(cur, ya, a, yb, z - DALLE, z, mat, bottom=True)
            cur = max(cur, b)
        if cur < 25.38:
            pbox(cur, ya, 25.38, yb, z - DALLE, z, mat, bottom=True)


# ------------------------------------------------------------------ refends
def refend(a0, a1, fixe, e, z0, z1, axe, portes=(), mat="enduitint", ht=2.15,
           vantail=True):
    """Un refend unique, partage par les deux pieces qu'il separe.

    axe='x' : mur normal a x, a la cote px=fixe, courant de py=a0 a py=a1.
    axe='y' : mur normal a y, a la cote py=fixe, courant de px=a0 a px=a1.
    portes  : suite de (centre, largeur) le long du mur ; un vantail de bois
              clair les ferme, comme sur les photographies de l'annonce.
    """
    t = e / 2
    coupes = [a0]
    for c, w in sorted(portes):
        coupes += [c - w / 2, c + w / 2]
    coupes.append(a1)

    def seg(u, v, zz0, zz1, m, e2=None):
        tt = t if e2 is None else e2
        if v - u < 1e-4:
            return
        if axe == "x":
            pbox(fixe - tt, u, fixe + tt, v, zz0, zz1, m)
        else:
            pbox(u, fixe - tt, v, fixe + tt, zz0, zz1, m)

    for k in range(0, len(coupes) - 1, 2):            # les pleins
        seg(coupes[k], coupes[k + 1], z0, z1, mat)
        # Rentree de 12 mm : posee au nu du mur, elle etait coplanaire avec
        # lui et l'ecran se mettait a papilloter.
        seg(coupes[k] + 0.012, coupes[k + 1] - 0.012,
            z0 + POCHE0, z0 + POCHE1, "poche", max(0.01, t - 0.012))
    for k in range(1, len(coupes) - 1, 2):            # les linteaux
        seg(coupes[k], coupes[k + 1], z0 + ht, z1, mat)
        if vantail and e > 0:
            u, v = coupes[k] + 0.02, coupes[k + 1] - 0.02
            if axe == "x":
                pbox(fixe - 0.02, u, fixe + 0.02, v, z0 + 0.015,
                     z0 + min(ht - 0.05, 2.10), "portebois")
            else:
                pbox(u, fixe - 0.02, v, fixe + 0.02, z0 + 0.015,
                     z0 + min(ht - 0.05, 2.10), "portebois")


def escalier(px0, py0, px1, py1, z0, z1, mat="pierrecl"):
    """Deux volees d'ouest en est, palier de retour a l'extremite est."""
    pw, ph = px1 - px0, py1 - py0
    n = max(4, int(round((z1 - z0) / 0.175)))
    n += n % 2
    h = (z1 - z0) / n
    hh, pal = ph / 2, 1.05
    g = (pw - pal) / (n / 2)
    for k in range(n // 2):
        z = z0 + h * (k + 1)
        pbox(px0 + g * k, py0 + hh, px0 + g * (k + 1), py1, z - h, z, mat)
    zm = z0 + (z1 - z0) / 2
    pbox(px1 - pal, py0, px1, py1, zm - h, zm, mat)
    for k in range(n // 2):
        z = zm + h * (k + 1)
        pbox(px0 + g * (n // 2 - k - 1), py0, px0 + g * (n // 2 - k), py0 + hh,
             z - h, z, mat)


# --------------------------------------------------------------- revetements
def damier(px0, py0, px1, py1, z, cote=0.55):
    """Damier noir et blanc a 45 degres, decoupe sur l'emprise de la piece.
    Le fond est blanc ; on ne pose que les losanges noirs, rognes au bord."""
    pbox(px0, py0, px1, py1, z, z + 0.012, "damierb")
    # 2 cm d'ecart et non 2 mm : le tampon de profondeur ne separe pas deux
    # plans plus proches que son pas, et le losange disparaissait sous le fond.
    d = cote * math.sqrt(2) / 2                       # demi-diagonale
    nu = int((px1 - px0) / d) + 2
    nv = int((py1 - py0) / d) + 2
    # Les centres de parite paire pavent deja tout le plan : pour obtenir un
    # damier il faut en retirer une case sur deux, d'ou la seconde condition.
    for iu in range(-1, nu + 1):
        for iv in range(-1, nv + 1):
            if (iu + iv) % 2 or iu % 2:
                continue
            cu = px0 + iu * d
            cv = py0 + iv * d
            poly = [(cu, cv - d), (cu + d, cv), (cu, cv + d), (cu - d, cv)]
            for ins, itr in (
                (lambda p: p[0] >= px0, lambda a, b: _lerp(a, b, 0, px0)),
                (lambda p: p[0] <= px1, lambda a, b: _lerp(a, b, 0, px1)),
                (lambda p: p[1] >= py0, lambda a, b: _lerp(a, b, 1, py0)),
                (lambda p: p[1] <= py1, lambda a, b: _lerp(a, b, 1, py1))):
                out = []
                for i in range(len(poly)):
                    a, b = poly[i - 1], poly[i]
                    ia, ib = ins(a), ins(b)
                    if ib:
                        if not ia:
                            out.append(itr(a, b))
                        out.append(b)
                    elif ia:
                        out.append(itr(a, b))
                poly = out
                if not poly:
                    break
            if len(poly) >= 3:
                F("damiern", *[V(_mx(p[0]), _my(p[1]), z + 0.032)
                               for p in reversed(poly)])


def _lerp(a, b, k, val):
    t = (val - a[k]) / (b[k] - a[k])
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


# ---------------------------------------------------------------- mobilier
def cuisine(px0, py0, px1, py1, z, ori=0):
    """Cuisine relevee sur les photographies de l'annonce : lineaire blanc
    laque, plan de travail anthracite, hotte inox, refrigerateur en bout,
    table blanche et chaises noires au milieu.

    ori=0 : le lineaire s'adosse au mur nord ; ori=1 : au mur sud. Au troisieme
    etage la porte s'ouvre au nord — le piano lui barrait le passage."""
    def cy_(v):                       # v : distance au mur d'adossement
        return py0 + v if ori == 0 else py1 - v

    def cb(a0, v0, a1, v1, z0, z1, mat):
        b0, b1 = sorted((cy_(v0), cy_(v1)))
        pbox(a0, b0, a1, b1, z0, z1, mat)

    ln0, ln1 = px0 + 0.15, px1 - 1.05
    cb(ln0, 0.02, ln1, 0.62, z, z + 0.86, "laque")            # caissons
    cb(ln0, 0.00, ln1, 0.64, z + 0.86, z + 0.90, "plantrav")
    cb(ln0, 0.02, ln1 - 1.30, 0.38, z + 1.45, z + 2.10, "laque")
    xh = ln1 - 1.55                                           # hotte
    cb(xh - 0.45, 0.02, xh + 0.45, 0.58, z + 1.55, z + 1.62, "inox")
    cb(xh - 0.28, 0.02, xh + 0.28, 0.40, z + 1.62, z + 2.20, "inox")
    cb(xh - 0.42, 0.05, xh + 0.42, 0.60, z + 0.89, z + 0.91, "sombre")
    cb(px1 - 0.95, 0.02, px1 - 0.25, 0.70, z, z + 1.85, "laque")
    cb(px1 - 0.93, 0.68, px1 - 0.27, 0.70, z + 0.90, z + 0.94, "sombre")
    tx = (px0 + px1) / 2                                      # table
    ty = cy_((py1 - py0) / 2 + 0.35 if ori == 0 else (py1 - py0) / 2 + 0.35)
    pbox(tx - 0.80, ty - 0.45, tx + 0.80, ty + 0.45, z + 0.72, z + 0.76, "laque")
    for sx in (tx - 0.74, tx + 0.70):
        for sy in (ty - 0.39, ty + 0.35):
            pbox(sx, sy, sx + 0.04, sy + 0.04, z, z + 0.72, "laque")
    for cx, cyy, o in ((tx - 0.45, ty - 0.78, 0), (tx + 0.45, ty - 0.78, 0),
                       (tx - 0.45, ty + 0.78, 1), (tx + 0.45, ty + 0.78, 1)):
        chaise(cx, cyy, z, o)


def lustre(px0, py0, px1, py1, z, hp, n=1):
    """Plafonnier d'opaline : c'est la seule source de lumiere interieure que
    connaisse le rendu Cycles, et elle allume aussi les vues du visualiseur."""
    for k in range(n):
        cx = px0 + (px1 - px0) * (k + 0.5) / n
        cy = (py0 + py1) / 2
        # 60 cm de cote : une source large se resout en bien moins
        # d'echantillons qu'un plafonnier de 34, et le grain des rendus
        # d'interieur venait de la.
        pbox(cx - 0.30, cy - 0.30, cx + 0.30, cy + 0.30,
             z + hp - 0.30, z + hp - 0.16, "opaline")


def bains(px0, py0, px1, py1, z):
    """Cabinet de toilette : cuvette, lavabo, cabine de douche vitree — la
    ceramique blanche et le verre des photographies de l'annonce."""
    w, d = px1 - px0, py1 - py0
    if w < 1.2 or d < 1.2:
        return
    pbox(px0 + 0.10, py0 + 0.12, px0 + 0.46, py0 + 0.72, z, z + 0.40, "laque")
    pbox(px0 + 0.08, py0 + 0.10, px0 + 0.48, py0 + 0.74, z + 0.40, z + 0.44, "laque")
    pbox(px0 + 0.62, py0 + 0.10, px0 + 1.20, py0 + 0.56, z + 0.82, z + 0.90, "laque")
    pbox(px0 + 0.86, py0 + 0.12, px0 + 0.96, py0 + 0.22, z + 0.90, z + 1.16, "inox")
    cx, cy = px1 - 0.95, py1 - 0.95
    pbox(cx - 0.45, cy - 0.45, cx + 0.45, cy + 0.45, z, z + 0.06, "solbain")
    pbox(cx - 0.45, cy - 0.45, cx - 0.41, cy + 0.45, z + 0.06, z + 1.95, "vitrage")
    pbox(cx - 0.45, cy - 0.45, cx + 0.45, cy - 0.41, z + 0.06, z + 1.95, "vitrage")


def battant(hx, hy, lg, ep, z0, z1, ang, mat="portebois"):
    """Vantail pivote autour de son gond, dans le plan du sol."""
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(hx + a * ca - b * sa, hy + a * sa + b * ca)
           for a, b in ((0, 0), (lg, 0), (lg, ep), (0, ep))]
    lo = [V(_mx(x), _my(y), z0) for x, y in pts]
    hi = [V(_mx(x), _my(y), z1) for x, y in pts]
    for k in range(4):
        j = (k + 1) % 4
        quad(mat, lo[k], lo[j], hi[j], hi[k])
    quad(mat, hi[0], hi[1], hi[2], hi[3])


def chaise(cx, cy, z, ori=0):
    pbox(cx - 0.22, cy - 0.22, cx + 0.22, cy + 0.22, z + 0.42, z + 0.46, "assise")
    for sx in (cx - 0.20, cx + 0.16):
        for sy in (cy - 0.20, cy + 0.16):
            pbox(sx, sy, sx + 0.04, sy + 0.04, z, z + 0.42, "assise")
    dy = cy + (0.20 if ori else -0.24)
    pbox(cx - 0.22, dy, cx + 0.22, dy + 0.04, z + 0.46, z + 0.92, "assise")


def chambre_meubles(px0, py0, px1, py1, z, cote_fen="sud"):
    """Lit simple, armoire et bureau, comme sur les photographies : structure
    blanche, couette claire, coussin turquoise, plateau de bureau en bambou."""
    if px1 - px0 < 1.9 or py1 - py0 < 2.2:
        return
    lx = px0 + 0.18
    ly = py0 + 0.30 if cote_fen == "sud" else py1 - 2.30
    pbox(lx, ly, lx + 0.95, ly + 2.00, z, z + 0.32, "laque")           # sommier
    pbox(lx, ly, lx + 0.95, ly + 2.00, z + 0.32, z + 0.55, "enduitint")  # couette
    pbox(lx + 0.10, ly + 0.10, lx + 0.85, ly + 0.45, z + 0.55, z + 0.66, "marbrecol")
    pbox(lx, ly + 1.96, lx + 0.95, ly + 2.04, z + 0.32, z + 1.05, "laque")
    ax = px1 - 1.30                                                     # armoire
    pbox(ax, py0 + 0.10, ax + 1.20, py0 + 0.68, z, z + 2.20, "laque")
    bx = px1 - 1.45                                                     # bureau
    by = py1 - 0.72
    pbox(bx, by, bx + 1.30, by + 0.60, z + 0.71, z + 0.75, "boisclair")
    for sx in (bx + 0.03, bx + 1.23):
        pbox(sx, by + 0.04, sx + 0.04, by + 0.08, z, z + 0.71, "laque")
    chaise(bx + 0.65, by - 0.45, z, 1)


def salon_meubles(px0, py0, px1, py2, z):
    """Deux canapes en vis-a-vis autour d'une table basse, et le long du mur
    est deux grandes tables blanches accolees par leur petit cote, entourees
    de chaises sur leurs trois cotes libres."""
    cx = (px0 + px1) / 2 - 1.6
    for dy, ori in ((py0 + 2.10, 0), (py0 + 4.30, 1)):
        pbox(cx - 1.15, dy, cx + 1.15, dy + 0.85, z, z + 0.40, "tissu")
        pbox(cx - 1.15, dy + (0.70 if ori else 0.0), cx + 1.15,
             dy + (0.85 if ori else 0.15), z + 0.40, z + 0.82, "tissu")
    pbox(cx - 0.60, py0 + 3.20, cx + 0.60, py0 + 3.90, z, z + 0.36, "boisclair")

    P, L, H = 0.95, 1.80, 0.75              # profondeur, longueur, hauteur
    x1 = px1 - 0.12                          # plateaux colles au mur est
    x0 = x1 - P
    ymid = (py0 + py2) / 2
    for k in (0, 1):
        a = ymid - L + k * L
        pbox(x0, a, x1, a + L, z + H - 0.04, z + H, "laque")
        for sx, sy in ((x0 + 0.05, a + 0.05), (x1 - 0.11, a + 0.05),
                       (x0 + 0.05, a + L - 0.11), (x1 - 0.11, a + L - 0.11)):
            pbox(sx, sy, sx + 0.06, sy + 0.06, z, z + H - 0.04, "laque")
    for k in range(5):                       # cote libre, face au mur
        chaise(x0 - 0.36, ymid - L + 0.45 + k * 0.72, z, 1)
    chaise(x0 + P / 2, ymid - L - 0.42, z, 0)      # bout nord
    chaise(x0 + P / 2, ymid + L + 0.42, z, 1)      # bout sud



def tunnel_x(x0, x1, v, z_sill, z_spring, hw, mat="enduitint", n=12):
    """Ebrasement d'une baie traversante dans un mur de normale x."""
    prof = [(v - hw, z_sill)]
    for i in range(n + 1):
        a = math.pi - math.pi * i / n
        prof.append((v + hw * math.cos(a), z_spring + hw * math.sin(a)))
    prof.append((v + hw, z_sill))
    A = [V(x0, p[0], p[1]) for p in prof]
    B = [V(x1, p[0], p[1]) for p in prof]
    for k in range(len(prof) - 1):
        quad(mat, A[k], A[k + 1], B[k + 1], B[k])


def doublage(z, hp):
    """Doublage plâtré des murs de pourtour, perce des memes baies que le
    parement, avec ses ebrasements. Sans lui les chambres regardent la brique
    du parement exterieur, et les fenetres ne s'ouvrent sur rien."""
    z1 = z + hp

    def dans(h):
        # On exige seulement que l'allege soit dans l'etage : les arcades de
        # la loggia montent a 10,15 m, plus haut que le plafond du premier, et
        # se trouvaient donc rejetees — les chambres du tiers central
        # restaient aveugles. wall_panel recoupe l'arc a la hauteur utile.
        return z + 0.10 < h[2] < z1 - 0.60

    # --- facade sur Via Boncompagni : baies du tiers central (loggia et
    #     trifora) et des deux blocs lateraux
    YD = _my(PY1)
    # Les deux tiers de facade ne sont pas dans le meme plan : le tiers central
    # est au nu de Y_F, les blocs lateraux en retrait de 50 cm. Un ebrasement
    # unique, parti de Y_F + 0,42, ressortait donc de 8 cm en avant de leur
    # brique, autour de chacune de leurs fenetres.
    fh_c = [h for h in FACADE + BANDH if dans(h)]              # tiers central
    fh_b = [h for v in BLOCKS.values() for h in v if dans(h)]  # blocs lateraux
    wall_panel("y", YD, +1, X_W + 0.94, X_E - 0.98, z, z1, fh_c + fh_b,
               mat="enduitint")
    # Chaque ebrasement commence APRES celui du parement (0,18 a 0,34 m selon
    # les baies), sinon les deux se superposent et l'ecran papillote.
    for uc, hw, zs, zp in fh_c:
        tunnel_y(Y_F + 0.42, YD, uc, zs, zp, hw)
    for uc, hw, zs, zp in fh_b:
        tunnel_y(Y_F + SETBACK + 0.22, YD, uc, zs, zp, hw)

    # --- gouttereaux ouest et est
    for pl, ins, HS in ((X_W, X_W + 0.94, AISLE_W_HOLES),
                        (X_E, X_E - 0.98, AISLE_E_HOLES)):
        ou = +1 if pl == X_W else -1
        # Le doublage s'arrete au nu interieur de la facade, pas a Y_F : le
        # tiers central est 50 cm en avant des blocs, et cette demi-longueur
        # de trop ressortait de la facade a l'extremite de chaque flanc.
        hs = [h for h in HS if _my(PY1) < h[0] < _my(PY0) and dans(h)]
        wall_panel("x", ins, ou, _my(PY1), _my(PY0), z, z1, hs, mat="enduitint")
        for vc, hw, zs, zp in hs:
            a = pl + (0.26 if pl < 0 else -0.26)
            tunnel_x(min(a, ins), max(a, ins), vc, zs, zp, hw)


def poche_enveloppe(z):
    """Les murs de pourtour appartiennent a la nef : on leur pose leur plaque,
    rentree de 6 cm pour ne pas venir au nu des parements."""
    poche(0.06, PY0 - 0.85, PX0 - 0.06, PY1 + 1.20, z)   # gouttereau ouest
    poche(PX1 + 0.06, PY0 - 0.85, 25.38, PY1 + 1.20, z)  # gouttereau est
    poche(PX0, PY1 + 0.06, PX1, PY1 + 1.20, z)           # facade sur rue


# =========================================== ETAGES, PILOTES PAR LE PLAN
# Le plan est la source. On ne trace plus les refends a la main : on rasterise
# les pieces, et tout ce qui reste a l'interieur du gros oeuvre EST du mur.
# Les portes s'ouvrent la ou une piece touche une circulation. Corriger le
# plan dans plan/plan.html et recoller l'export ici suffit a tout regenerer.
import json as _json
PLAN = _json.load(open(os.path.dirname(os.path.abspath(__file__))
                       + "/../plan/plan_corrige.json"))["niveaux"]
STEP = 0.05
CIRC = ("couloir", "palier", "sas", "balcon", "degagement", "escalier")


def _circ(p):
    n = p["n"].lower()
    return p["k"] in ("couloir", "escalier") or any(c in n for c in CIRC)


def _rects(p):
    return [(q["x"], q["y"] + 2.08, q["w"], q["h"]) for q in p["parts"]]


def _boite(p):
    r = _rects(p)
    return (min(x for x, y, w, h in r), min(y for x, y, w, h in r),
            max(x + w for x, y, w, h in r), max(y + h for x, y, w, h in r))


def _grille(pieces):
    nx = int(round((PX1 - PX0) / STEP)); ny = int(round((PY1 - PY0) / STEP))
    g = [[-1] * nx for _ in range(ny)]
    for k, p in enumerate(pieces):
        for x, y, w, h in _rects(p):
            i0 = max(0, int(round((x - PX0) / STEP)))
            i1 = min(nx, int(round((x + w - PX0) / STEP)))
            j0 = max(0, int(round((y - PY0) / STEP)))
            j1 = min(ny, int(round((y + h - PY0) / STEP)))
            for j in range(j0, j1):
                row = g[j]
                for i in range(i0, i1):
                    row[i] = k
    return g, nx, ny


def _pave(mask, nx, ny):
    """Decoupe un masque en rectangles maximaux : un mur mince donne quelques
    boites, pas une par cellule."""
    m = [row[:] for row in mask]; out = []
    for j in range(ny):
        i = 0
        while i < nx:
            if not m[j][i]:
                i += 1; continue
            i2 = i
            while i2 < nx and m[j][i2]:
                i2 += 1
            j2 = j + 1
            while j2 < ny and all(m[j2][k] for k in range(i, i2)):
                j2 += 1
            for jj in range(j, j2):
                for kk in range(i, i2):
                    m[jj][kk] = False
            out.append((i, j, i2, j2)); i = i2
    return out


def _portes(g, nx, ny, pieces):
    """Traversees possibles : une piece, un peu de mur, une autre piece. On
    n'en garde qu'une par couple, et seulement vers une circulation."""
    cross = {}
    def note(a, b, pos, lo, hi, axe):
        if a == b or a < 0 or b < 0: return
        if not (_circ(pieces[a]) or _circ(pieces[b])): return
        cross.setdefault((min(a, b), max(a, b), axe, lo, hi), []).append(pos)
    for j in range(ny):
        i = 0
        while i < nx:
            if g[j][i] >= 0: i += 1; continue
            i2 = i
            while i2 < nx and g[j][i2] < 0: i2 += 1
            if i > 0 and i2 < nx and (i2 - i) * STEP <= 1.10:
                note(g[j][i - 1], g[j][i2], j, i, i2, "v")
            i = i2
    for i in range(nx):
        j = 0
        while j < ny:
            if g[j][i] >= 0: j += 1; continue
            j2 = j
            while j2 < ny and g[j2][i] < 0: j2 += 1
            if j > 0 and j2 < ny and (j2 - j) * STEP <= 1.10:
                note(g[j - 1][i], g[j2][i], i, j, j2, "h")
            j = j2
    best = {}
    LARGE = {}
    for (a, b, axe, lo, hi), pos in cross.items():
        if pieces[a]["n"].startswith("Salon") or pieces[b]["n"].startswith("Salon"):
            LARGE[(min(a, b), max(a, b))] = True
        pos.sort(); runs = [[pos[0]]]
        for p in pos[1:]:
            (runs[-1] if p == runs[-1][-1] + 1 else runs.append([p]) or runs[-1]).append(p)
        run = max(runs, key=len)
        if len(run) * STEP < 1.00: continue
        k = (a, b)
        if k in best and len(best[k][0]) >= len(run): continue
        best[k] = (run, axe, lo, hi)
    dr = [[False] * nx for _ in range(ny)]
    for kk, (run, axe, lo, hi) in best.items():
        c = (run[0] + run[-1]) // 2
        d = int((0.82 if kk in LARGE else 0.45) / STEP)
        for p in range(c - d, c + d + 1):
            for q in range(lo, hi):
                if axe == "v" and 0 <= p < ny: dr[p][q] = True
                if axe == "h" and 0 <= p < nx: dr[q][p] = True
    return dr


def etage_plan(niv, z, hp, zone=None):
    """zone limite l'emprise batie : au troisieme, le logement n'occupe qu'un
    ilot sous le rampant, et sans cette borne tout le reste du plancher — les
    deux terrasses comprises — se remplissait de cloison pleine."""
    pieces = PLAN[str(niv)]
    g, nx, ny = _grille(pieces)
    dr = _portes(g, nx, ny, pieces)
    X = lambda i: PX0 + i * STEP
    Y = lambda j: PY0 + j * STEP
    def dedans(i, j):
        if zone is None:
            return True
        return (zone[0] - 0.02 <= X(i) < zone[2] + 0.02
                and zone[1] - 0.02 <= Y(j) < zone[3] + 0.02)
    plein = [[g[j][i] < 0 and not dr[j][i] and dedans(i, j) for i in range(nx)]
             for j in range(ny)]
    baie = [[g[j][i] < 0 and dr[j][i] and dedans(i, j) for i in range(nx)]
            for j in range(ny)]
    for i, j, i2, j2 in _pave(plein, nx, ny):
        pbox(X(i), Y(j), X(i2), Y(j2), z, z + hp, "enduitint")
        pbox(X(i) + 0.012, Y(j) + 0.012, X(i2) - 0.012, Y(j2) - 0.012,
             z + POCHE0, z + POCHE1, "poche")
    for i, j, i2, j2 in _pave(baie, nx, ny):
        pbox(X(i), Y(j), X(i2), Y(j2), z + 2.10, z + hp, "enduitint")   # linteau
        zb, zh = z + 0.015, z + 2.05
        if (i2 - i) < (j2 - j):                 # mur normal a x, baie selon py
            xm = (X(i) + X(i2)) / 2
            a, b = Y(j) + 0.02, Y(j2) - 0.02
            if b - a > 1.20:                     # deux vantaux : celui du nord
                m = (a + b) / 2                  # s'entrouvre
                battant(xm - 0.02, m, m - a, 0.04, zb, zh, math.radians(-38))
                pbox(xm - 0.02, m, xm + 0.02, b, zb, zh, "portebois")
            else:
                pbox(xm - 0.02, a, xm + 0.02, b, zb, zh, "portebois")
        else:                                    # mur normal a y, baie selon px
            ym = (Y(j) + Y(j2)) / 2
            a, b = X(i) + 0.02, X(i2) - 0.02
            if b - a > 1.20:
                m = (a + b) / 2
                battant(m, ym - 0.02, m - a, 0.04, zb, zh, math.radians(142))
                pbox(m, ym - 0.02, b, ym + 0.02, zb, zh, "portebois")
            else:
                pbox(a, ym - 0.02, b, ym + 0.02, zb, zh, "portebois")
    return pieces


SOLS = {"chambre": "solcham", "sanitaire": "solbain", "cuisine": "solcuis",
        "couloir": "solcham", "living": "solcham", "autre": "solcham"}


def meubler(niv, z, hp):
    for p in PLAN[str(niv)]:
        a, b, c, d = _boite(p)
        aire = sum(w * h for _x, _y, w, h in _rects(p))
        PIECES.append({"l": niv, "n": p["n"], "x0": _mx(a), "x1": _mx(c),
                       "y0": _my(d), "y1": _my(b), "z": z, "a": round(aire, 1)})
        if p["k"] in ("escalier", "vide"):
            continue
        for x, y, w, h in _rects(p):
            pbox(x, y, x + w, y + h, z, z + 0.015, SOLS.get(p["k"], "solcham"))
        lustre(a, b, c, d, z, hp, n=max(1, int((c - a) / 4.6)))
        if p["k"] == "chambre":
            chambre_meubles(a, b, c, d, z)
        elif p["k"] == "cuisine":
            cuisine(a, b, c, d, z, ori=1 if niv == 3 else 0)
        elif p["k"] == "sanitaire":
            bains(a, b, c, d, z)
        elif p["n"].startswith("Salon"):
            damier(a, b, c, d, z)
            salon_meubles(a, b, c, d, z)


def _piece_de(niv, nom):
    for p in PLAN[str(niv)]:
        if p["n"] == nom:
            return _boite(p)
    raise KeyError(nom)


CAGE = _piece_de(1, "Escalier")
SALON = _piece_de(1, "Salon commun")
VIDE = _piece_de(2, "Vide sur salon")

plancher_troue(Z_ET1, [CAGE], "solint")
poche_enveloppe(Z_ET1)
doublage(Z_ET1, PH1)
etage_plan(1, Z_ET1, PH1)
meubler(1, Z_ET1, PH1)

plancher_troue(Z_ET2, [VIDE, CAGE], "solint")
poche_enveloppe(Z_ET2)
doublage(Z_ET2, PH2)
etage_plan(2, Z_ET2, PH2)
meubler(2, Z_ET2, PH2)
for _a, _b, _c, _d in ((VIDE[0], VIDE[1], VIDE[2], VIDE[1] + 0.07),
                       (VIDE[0], VIDE[3] - 0.07, VIDE[2], VIDE[3]),
                       (VIDE[0], VIDE[1], VIDE[0] + 0.07, VIDE[3]),
                       (VIDE[2] - 0.07, VIDE[1], VIDE[2], VIDE[3])):
    pbox(_a, _b, _c, _d, Z_ET2, Z_ET2 + 1.02, "pierrecl")   # garde-corps du vide
# ===================================================== TROISIEME ETAGE
# Sous le rampant de la nef, derriere le pignon de facade : deux chambres,
# une cuisine, deux cabinets et deux degagements. De part et d'autre, les
# terrasses ; au nord, le comble de l'eglise (SOTTOTETTO CHIESA).
# 4 cm plus bas : posee au nu de l'arase des blocs, elle papillotait avec.
plancher_troue(Z_TOITURE - 0.04, [SALON, CAGE], "solint")
P3 = (7.60, 10.90, 17.85, 16.10)
pbox(P3[0], P3[1], P3[2], P3[3], Z_ET3 - 0.22, Z_ET3, "solint", bottom=True)
etage_plan(3, Z_ET3, PH3, zone=P3)
meubler(3, Z_ET3, PH3)
piece_xy(3, "Comble de l'eglise", X_NW, _my(P3[1]), X_NE, Y_NARTH, Z_ET3)
piece_xy(3, "Terrasse ouest", X_W, Y_F + SETBACK, X_NW, Y_NARTH, Z_ET3)
piece_xy(3, "Terrasse est", X_NE, Y_F + SETBACK, X_E, Y_NARTH, Z_ET3)

# --------------------------------------- lanterneau au sommet du vide
for _a, _b, _c, _d in ((SALON[0], SALON[1], SALON[2], SALON[1] + 0.24),
                       (SALON[0], SALON[3] - 0.24, SALON[2], SALON[3]),
                       (SALON[0], SALON[1], SALON[0] + 0.24, SALON[3]),
                       (SALON[2] - 0.24, SALON[1], SALON[2], SALON[3])):
    pbox(_a, _b, _c, _d, Z_TOITURE, Z_TOITURE + 0.60, "pierrecl")
pbox(SALON[0] + 0.24, SALON[1] + 0.24, SALON[2] - 0.24, SALON[3] - 0.24,
     Z_TOITURE + 0.56, Z_TOITURE + 0.60, "vitrage")

# --------------------------------------- la cage monte du dallage a la terrasse
for _z0, _z1 in ((I_FLOOR, Z_ET1), (Z_ET1, Z_ET2), (Z_ET2, Z_TOITURE),
                 (Z_TOITURE, Z_ET3 + 0.30)):
    escalier(CAGE[0], CAGE[1], CAGE[2], CAGE[3], _z0, _z1)

# --------------------------------------- poche du rez : pourtour de l'eglise
poche_xy(X_W + 0.06, Y_F + 0.06, X_W + 0.94, Y_B - 0.06, I_FLOOR)
poche_xy(X_E - 0.94, Y_F + 0.06, X_E - 0.06, Y_B - 0.06, I_FLOOR)
poche_xy(X_W + 0.06, Y_F + 0.06, X_E - 0.06, Y_F + 1.20, I_FLOOR)
poche_xy(X_W + 0.06, Y_B - 0.90, X_E - 0.06, Y_B - 0.06, I_FLOOR)
for _xw in (X_NW, X_NE):                       # murs de nef
    poche_xy(_xw - 0.45, Y_NARTH, _xw + 0.45, Y_B, I_FLOOR)

# --------------------------------------- nomenclature du rez (eglise + atrium)
piece_xy(0, "Atrium", X_W, Y_F, X_E, Y_NARTH, I_FLOOR)
piece_xy(0, "Nef", X_NW, Y_NARTH, X_NE, Y_B - 2.0, I_FLOOR)
piece_xy(0, "Bas-cote ouest", X_W, Y_NARTH, X_NW, Y_B, I_FLOOR)
piece_xy(0, "Bas-cote est", X_NE, Y_NARTH, X_E, Y_B, I_FLOOR)
piece_xy(0, "Choeur", X_NW + 2.0, Y_B - 2.0, X_NE - 2.0, Y_B + 3.0, I_FLOOR)
piece_xy(0, "Abside", APSE_CX - 3.0, Y_B + 3.0, APSE_CX + 3.0, Y_B + 7.0, I_FLOOR)

with open(os.path.dirname(os.path.abspath(__file__)) + "/../reconstruction/pieces.json", "w") as _f:
    json.dump(PIECES, _f)
# --- 7. sol de reference (dalle mince, aide a la lecture du volume)
box(X_W - 1.2, X_E + 1.2, Y_F - 3.2, Y_B + 11.0, -0.35, -0.01, "sol")

# =================================================================== ECRITURE
MTL = {
    "mur":      (0.76, 0.46, 0.31),
    "enduitext":(0.80, 0.42, 0.28),
    "brique":   (0.78, 0.50, 0.36),
    "pierre":   (0.89, 0.86, 0.78),
    "opaline":  (0.97, 0.95, 0.90),
    "tuile":    (0.44, 0.40, 0.33),
    "vitrage":  (0.74, 0.73, 0.66),
    "vitrail":  (0.80, 0.72, 0.50),
    "bois":     (0.35, 0.22, 0.13),
    "porte":    (0.35, 0.21, 0.11),
    "portemet": (0.30, 0.20, 0.14),
    "metal":    (0.17, 0.11, 0.08),
    "pierrecl": (0.86, 0.82, 0.72),
    "breche":   (0.78, 0.64, 0.45),
    "marbrecol":(0.55, 0.59, 0.63),
    "enduitint":(0.93, 0.90, 0.82),
    "caisson":  (0.30, 0.16, 0.09),
    "solint":   (0.85, 0.82, 0.76),
    "solmotif": (0.37, 0.42, 0.40),
    "marbrevert":(0.24, 0.28, 0.24),
    "nuit":     (0.11, 0.13, 0.24),
    "inscript": (0.32, 0.26, 0.12),
    "dorure":   (0.42, 0.33, 0.15),
    "arcpeint": (0.62, 0.50, 0.34),
    "arcsurr":  (0.66, 0.55, 0.41),
    "blason":   (0.78, 0.74, 0.65),
    "blasonb":  (0.78, 0.74, 0.65),
    "ocre":     (0.84, 0.72, 0.50),
    "ardoise":  (0.44, 0.46, 0.45),
    "solbande": (0.36, 0.42, 0.40),
    "tableau":  (0.50, 0.36, 0.26),
    "mosabside":(0.62, 0.48, 0.20),
    "mosfront": (0.55, 0.42, 0.20),
    "mostymp":  (0.55, 0.42, 0.20),
    "sombre":   (0.07, 0.07, 0.08),
    "mosaique": (0.76, 0.62, 0.27),
    "toitplat": (0.42, 0.43, 0.46),
    "sol":      (0.55, 0.55, 0.55),
    # --- interieurs du corps de logis, releves sur les photographies
    "solcham":  (0.86, 0.85, 0.81),   # cementine claires des chambres
    "solcuis":  (0.82, 0.54, 0.45),   # cementine rouges des cuisines
    "solbain":  (0.80, 0.78, 0.76),   # carrelage gris des cabinets
    "damiern":  (0.11, 0.11, 0.13),   # damier du salon commun, losange noir
    "damierb":  (0.93, 0.92, 0.89),   #                          losange blanc
    "portebois":(0.79, 0.54, 0.31),   # vantail de bois clair
    "laque":    (0.95, 0.94, 0.93),   # mobilier blanc laque
    "plantrav": (0.23, 0.23, 0.24),   # plan de travail anthracite
    "inox":     (0.73, 0.74, 0.76),   # hotte et electromenager
    "assise":   (0.14, 0.14, 0.16),   # chaises noires
    "tissu":    (0.43, 0.50, 0.51),   # canapes du salon commun
    "boisclair":(0.85, 0.72, 0.49),   # plateaux de bambou
    "terrasse": (0.75, 0.44, 0.35),   # stabilise granuleux des terrasses
    "poche":    (0.34, 0.36, 0.37),   # murs coupes, lus en plan
}
out_dir = os.path.dirname(os.path.abspath(__file__)) + "/../reconstruction"
os.makedirs(out_dir, exist_ok=True)
with open(out_dir + "/san_patrizio.mtl", "w") as f:
    for k, (r, g, b) in MTL.items():
        f.write(f"newmtl {k}\nKd {r:.3f} {g:.3f} {b:.3f}\nKa 0 0 0\nKs 0.04 0.04 0.04\nNs 12\nd 1\nillum 2\n\n")
with open(out_dir + "/san_patrizio.obj", "w") as f:
    f.write("# San Patrizio a Villa Ludovisi - reconstruction volumetrique\n")
    f.write("# emprise OSM way 203996025 + hauteurs Apple Flyover + monographie 2026\n")
    f.write("mtllib san_patrizio.mtl\no san_patrizio\n")
    for x, y, z in verts:
        f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
    faces.sort(key=lambda t: t[0])
    cur = None
    for mat, idx in faces:
        if mat != cur:
            f.write(f"usemtl {mat}\n"); cur = mat
        f.write("f " + " ".join(str(i) for i in idx) + "\n")
print(f"OK  {len(verts)} sommets, {len(faces)} faces -> {out_dir}/san_patrizio.obj")
