#!/usr/bin/env python3
"""Convertit l'OBJ Z-up du generateur vers la convention OBJ standard Y-up
(Cinema 4D, Maya, Unity, la plupart des viewers), pose au sol et centre."""
import sys, os

src = sys.argv[1] if len(sys.argv) > 1 else "reconstruction/san_patrizio.obj"
dst = sys.argv[2] if len(sys.argv) > 2 else "reconstruction/san_patrizio_Yup.obj"

# rotation propre (det = +1) : X'=X, Y'=Z, Z'=-Y  -> l'orientation des faces est conservee
V = []
for line in open(src):
    if line.startswith("v "):
        p = line.split()
        x, y, z = float(p[1]), float(p[2]), float(p[3])
        V.append((x, z, -y))

xs = [p[0] for p in V]; ys = [p[1] for p in V]; zs = [p[2] for p in V]
cx = (min(xs) + max(xs)) / 2          # centre en X
cz = (min(zs) + max(zs)) / 2          # centre en Z
gy = min(ys)                          # pose au sol : Y = 0

with open(dst, "w") as w:
    i = 0
    for line in open(src):
        if line.startswith("v "):
            x, y, z = V[i]; i += 1
            w.write(f"v {x-cx:.4f} {y-gy:.4f} {z-cz:.4f}\n")
        elif line.startswith("# "):
            w.write(line)
        else:
            w.write(line)

# Le recentrage depend de la bboite, donc du modele : on l'ecrit pour que le
# visualiseur puisse y placer autre chose que du maillage (les etiquettes de
# pieces, par exemple).
import json
json.dump({"cx": cx, "gy": gy, "cz": cz},
          open(os.path.dirname(dst) + "/yup.json", "w"))

print(f"{dst}")
print(f"  X (largeur)  {max(xs)-min(xs):6.2f} m")
print(f"  Y (hauteur)  {max(ys)-min(ys):6.2f} m   sol a Y=0")
print(f"  Z (longueur) {max(zs)-min(zs):6.2f} m")
