#!/usr/bin/env python3
"""Confronte le modele volumetrique aux surfaces declarees dans les annonces.

Le modele est cale sur l'emprise cadastrale et le maillage Apple Flyover ; les
annonces DoveVivo declarent, elles, des surfaces mesurees a l'interieur. Ce sont
deux mesures independantes du meme batiment : les faire se repondre dit ou le
modele tient et ou il derive.

Attention a ce qu'on additionne. Le niveau 2 du modele compte un vide sur le
salon et un balcon, qui ne sont pas de la surface habitable : une annonce ne les
compte pas.
"""
import argparse
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
NIVEAUX = {"rm-0094": 1, "rm-0095": 2, "rm-0096": 3}
HORS_HABITABLE = {"Vide sur salon", "Balcon 2e", "Terrasse ouest", "Terrasse est",
                  "Comble de l'eglise"}


def chambres(pieces, niveau):
    return {p["n"]: p["a"] for p in pieces
            if p["l"] == niveau and p["n"][:1].isdigit() and p["n"].endswith("A")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--annonces", type=Path, default=RACINE / "annonces_boncompagni.json")
    ap.add_argument("--pieces", type=Path, default=RACINE / "reconstruction" / "pieces.json")
    args = ap.parse_args()

    pieces = json.loads(args.pieces.read_text())
    fiches = json.loads(args.annonces.read_text())

    for app, niveau in NIVEAUX.items():
        lot = [f for f in fiches if f["appartement"] == app and "erreur" not in f]
        declare = [f for f in lot if "surface_appartement_m2" in f]
        print(f"\n{'='*68}\n{app}  ->  niveau {niveau} du modele")
        print(f"{len(lot)} fiches lues, {len(declare)} declarent le bati")
        if not declare:
            print("  rien a confronter")
            continue
        d = declare[-1]

        au_niveau = [p for p in pieces if p["l"] == niveau]
        total = sum(p["a"] for p in au_niveau)
        habitable = sum(p["a"] for p in au_niveau if p["n"] not in HORS_HABITABLE)
        exclu = total - habitable

        print(f"\n  {'':22s} {'annonce':>10s} {'modele':>10s}")
        print(f"  {'etage':22s} {d.get('etage','?'):>10} {niveau:>10}")
        print(f"  {'chambres':22s} {d.get('chambres','?'):>10} "
              f"{len(chambres(pieces, niveau)):>10}")
        print(f"  {'salles d eau':22s} {d.get('bains','?'):>10} "
              f"{sum(1 for p in au_niveau if p['n'].startswith('WC')):>10}")
        print(f"  {'surface totale (m2)':22s} {d['surface_appartement_m2']:>10.0f} {total:>10.0f}")
        if exclu:
            print(f"  {'dont hors habitable':22s} {'':>10s} {exclu:>10.0f}"
                  f"   ({', '.join(p['n'] for p in au_niveau if p['n'] in HORS_HABITABLE)})")
            print(f"  {'surface habitable':22s} {d['surface_appartement_m2']:>10.0f} "
                  f"{habitable:>10.0f}")

        # surfaces de chambre : l'annonce numerote 01A..07A, le modele 1A..7A
        annoncees = {}
        for f in lot:
            if "surface_chambre_m2" in f:
                annoncees[f["chambre"].lstrip("0")] = f["surface_chambre_m2"]
            for c, v in f.get("autres_chambres", {}).items():
                annoncees.setdefault(c.lstrip("0"), v["surface_m2"])
        mod = chambres(pieces, niveau)
        communes = sorted(set(annoncees) & {n[:-1] for n in mod})
        if communes:
            print(f"\n  chambre   annonce   modele    ecart")
            ecarts = []
            for c in communes:
                a, m = annoncees[c], mod[f"{c}A"]
                ecarts.append(m - a)
                print(f"    {c}A {a:9.0f} {m:8.0f} {m-a:8.1f}")
            moy = sum(ecarts) / len(ecarts)
            print(f"    ecart moyen {moy:+.1f} m2 "
                  f"({100*moy/(sum(annoncees[c] for c in communes)/len(communes)):+.0f} %)")

        loyers = sorted((f["date"], f["chambre"], f["loyer"])
                        for f in lot if "loyer" in f)
        if loyers:
            print(f"\n  loyers releves : " +
                  ", ".join(f"{c}A {p} EUR ({d[:7]})" for d, c, p in loyers[:8]))


if __name__ == "__main__":
    main()
