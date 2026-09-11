#!/usr/bin/env python3
"""Confronte le releve instrumente de Matterport au modele volumetrique.

Matterport ne publie pas que des panoramas : chaque modele porte la surface
mesuree de l'etage, et pour chaque piece ses dimensions et des etiquettes
semantiques — chambre, salle d'eau, cuisine, couloir. C'est la seule des trois
sources qui soit une mesure d'instrument : le modele vient du cadastre et d'un
maillage aerien, les annonces d'une declaration commerciale.

Chaque piece est situee par les sweeps qui s'y trouvent, ramenes dans le repere
du modele par le recalage. On sait alors a quelle piece de pieces.json elle
repond.
"""
import argparse
import json
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
NIVEAU = {"1P": 1, "2P": 2, "3P": 3}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("etages", nargs="*", default=["1P", "2P", "3P"])
    ap.add_argument("--data", type=Path, default=RACINE / "splat" / "data")
    ap.add_argument("--pieces", type=Path, default=RACINE / "reconstruction" / "pieces.json")
    ap.add_argument("--json", type=Path, help="ecrire la confrontation dans ce fichier")
    args = ap.parse_args()

    modele = json.loads(args.pieces.read_text())
    sortie = {}

    for etage in args.etages:
        src = args.data / etage
        releve = json.loads((src / "releve.json").read_text())
        sweeps = json.loads((src / "sweeps.json").read_text())["sweeps"]
        reg = json.loads((src / "recalage.json").read_text()) \
            if (src / "recalage.json").exists() else None
        niveau = NIVEAU[etage]
        au_niveau = [p for p in modele if p["l"] == niveau]

        aire_etage = sum(f["dimensions"]["areaFloor"] for f in releve["etages"])
        print(f"\n{'='*78}\n{etage} — {releve['adresse']}, releve du "
              f"{(releve['publie'] or 'date inconnue')[:10]}")
        print(f"  etage mesure {aire_etage:.1f} m2, {len(releve['pieces'])} pieces, "
              f"{len(sweeps)} sweeps")

        # centroide de chaque piece, d'apres les sweeps qui s'y trouvent
        par_piece = {}
        for s in sweeps:
            par_piece.setdefault(s["room"], []).append(
                [s["position"]["x"], s["position"]["y"]])

        R = t = c0 = None
        if reg:
            a = np.radians(reg["rotation_deg"])
            R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            t = np.array(reg["translation_xy"])
            c0 = np.array(reg["centre_matterport"])

        lignes = []
        for p in sorted(releve["pieces"],
                        key=lambda x: -x["dimensions"]["areaFloor"]):
            d = p["dimensions"]
            etiquettes = ", ".join(p.get("tags", [])) or "—"
            nom = "—"
            pts = par_piece.get(p["id"])
            if pts and R is not None:
                xy = (np.array(pts).mean(0) - c0) @ R.T + t
                dedans = [q for q in au_niveau
                          if q["x0"] <= xy[0] <= q["x1"] and q["y0"] <= xy[1] <= q["y1"]]
                if dedans:
                    nom = min(dedans, key=lambda q: q["a"])["n"]
            lignes.append((etiquettes, d.get("areaFloor", 0.0), d.get("width"),
                           d.get("depth"), len(pts or []), nom))

        print(f"\n  {'etiquettes Matterport':30s} {'m2':>7s} {'l x p (m)':>13s} "
              f"{'sweeps':>7s}  piece du modele")
        for e, a_, w, dp, n, nom in lignes:
            dim = f"{w:6.1f} x{dp:5.1f}" if w and dp else " " * 13
            print(f"  {e:30.30s} {a_:7.1f} {dim} {n:7d}  {nom}")
        total = sum(l[1] for l in lignes)
        print(f"  {'total des pieces':30s} {total:7.1f}")
        sortie[etage] = {"aire_etage_mesuree": round(aire_etage, 1),
                         "pieces": [{"etiquettes": e, "m2": round(a_, 1),
                                     "largeur": round(w, 2) if w else None,
                                     "profondeur": round(dp, 2) if dp else None,
                                     "sweeps": n, "piece_modele": nom}
                                    for e, a_, w, dp, n, nom in lignes]}

    if args.json:
        args.json.write_text(json.dumps(sortie, indent=1, ensure_ascii=False))
        print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
