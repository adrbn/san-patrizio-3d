#!/usr/bin/env python3
"""Relit les annonces archivees des trois appartements de Via Boncompagni 31.

DoveVivo louait l'immeuble a la chambre : RM-0094 au premier etage, RM-0095 au
deuxieme, RM-0096 au troisieme. Chaque fiche declare la surface de l'appartement
et de la chambre, le nombre de pieces, d'occupants et de bains, l'etage, la
classe energetique, le loyer et la date de disponibilite. Ces valeurs sont une
mesure independante du releve : elles servent a controler le modele.

Les fiches sont mortes sur le site actuel ; on passe donc par les instantanes de
la Wayback Machine, de 2021 a 2026.
"""
import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
DOMAINES = ["www.dovevivo.it", "www.dovevivo.com", "coliving.joivy.com"]
APPARTEMENTS = {"rm-0094": "1P", "rm-0095": "2P", "rm-0096": "3P"}


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        b = Path("/etc/ssl/cert.pem")
        return ssl.create_default_context(cafile=str(b)) if b.exists() \
            else ssl.create_default_context()


SSL_CTX = _ctx()


def get(url, timeout=90, essais=5):
    """La Wayback Machine limite le debit : on recule et on reessaie."""
    attente = 3.0
    for n in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.read()
        except Exception:
            if n == essais - 1:
                raise
            time.sleep(attente)
            attente *= 2
    raise RuntimeError("inatteignable")


def instantanes():
    """Tous les instantanes archives des fiches Boncompagni, par date."""
    vus = []
    for d in DOMAINES:
        q = urllib.parse.urlencode({"url": f"{d}/*", "fl": "timestamp,original",
                                    "collapse": "digest"})
        try:
            txt = get(f"http://web.archive.org/cdx/search/cdx?{q}", 180).decode()
        except Exception as exc:
            print(f"  ! {d}: {exc}", file=sys.stderr)
            continue
        for line in txt.splitlines():
            ts, _, url = line.partition(" ")
            if re.search(r"rm-009[456]-\d\d-a/?$", url, re.I):
                vus.append((ts, url))
    return sorted(set(vus))


def texte(page):
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


CHAMPS = {
    "surface_appartement_m2": r"Appartamento mq:\s*([\d.,]+)",
    "occupants": r"Numero di occupanti:\s*(\d+)",
    "chambres": r"Numero di stanze:\s*(\d+)",
    "etage": r"Piano:\s*(\d+)",
    "bains": r"Numero di bagni:\s*(\d+)",
    "classe_energetique": r"Classe energetica:\s*([A-G]\d?)",
    "ipe": r"IPE kw/mq:\s*([\d.,]+)",
}


CACHE = Path(__file__).resolve().parents[1] / "cache_annonces"


def page_archivee(ts, url):
    """Le HTML d'un instantane, conserve en local : archive.org limite le debit,
    on ne redemande jamais deux fois la meme capture."""
    CACHE.mkdir(exist_ok=True)
    nom = re.sub(r"[^a-z0-9]+", "_", f"{ts}_{url.split('//')[-1]}", flags=re.I)[:120]
    f = CACHE / f"{nom}.html"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    page = get(f"http://web.archive.org/web/{ts}id_/{url}").decode("utf-8", "replace")
    f.write_text(page, encoding="utf-8")
    return page


def lire(ts, url):
    """Extrait d'un instantane ce qu'il declare sur l'appartement et ses chambres."""
    code = re.search(r"(rm-009[456])-(\d\d)-a", url, re.I)
    fiche = {"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "url": url,
             "appartement": code.group(1).lower(), "chambre": code.group(2),
             "etage_modele": APPARTEMENTS[code.group(1).lower()]}
    try:
        page = page_archivee(ts, url)
    except Exception as exc:
        fiche["erreur"] = str(exc)
        return fiche

    t = texte(page)
    for cle, motif in CHAMPS.items():
        m = re.search(motif, t)
        if m:
            v = m.group(1).replace(",", ".")
            fiche[cle] = float(v) if "." in v else int(v) if v.isdigit() else v

    m = re.search(r"- (\d\d)A (\d+) metri quadri", t)
    if m:
        fiche["surface_chambre_m2"] = int(m.group(2))

    # le tableau des autres chambres donne surface, loyer et disponibilite
    autres = {}
    for m in re.finditer(r"- (\d\d)A Stanza disponibile dal (\d\d/\d\d/\d\d) "
                         r"(\d+)€ al mese Dimensioni (\d+) m", t):
        autres[m.group(1)] = {"disponible": m.group(2), "loyer": int(m.group(3)),
                              "surface_m2": int(m.group(4))}
    if autres:
        fiche["autres_chambres"] = autres

    m = re.search(r"Affitto mensile [^0-9]*([\d.]+) €", t)
    if m:
        fiche["loyer"] = int(float(m.group(1).replace(".", "")))
    if "Non disponibile" in t:
        fiche["statut"] = "non disponible"
    elif re.search(r"disponibile dal", t):
        fiche["statut"] = "disponible"

    # Le gabarit de 2024-2025 publie, chambre par chambre, le profil de qui
    # l'occupe : statut, age, genre. Sans nom : c'est la composition du logement
    # telle que le bailleur l'annonce a un candidat, pas un annuaire.
    m = re.search(r"(?:Who you will find|Chi troverai|Qui vous trouverez|"
                  r"A qui[eé]n encontrar[aá]s)(.{0,900}?)(?:Show all|Mostra tutto|"
                  r"Voir tout|Ver todo|from \d)", t)
    if m:
        occupants = {}
        for seg in re.finditer(r"(?:Room|Stanza|Chambre|Habitaci[oó]n)\s*(\d{1,2})\s+"
                               r"([^,]{1,24}?)\s*(?:,\s*(\d{1,2})\s*,\s*"
                               r"([A-Za-z]{4,10}))?(?=\s*(?:Room|Stanza|Chambre|"
                               r"Habitaci|$))", m.group(1)):
            num, statut, age, genre = seg.groups()
            if age is None:
                occupants[num] = {"statut": statut.strip()}     # « This room »
            else:
                occupants[num] = {"statut": statut.strip(), "age": int(age),
                                  "genre": genre.strip()}
        if occupants:
            fiche["logement"] = occupants

    m = re.search(r"Servizi dell'appartamento (.*?) Altre stanze", t)
    if m:
        fiche["services"] = [s for s in re.split(r"(?<=[a-z])(?=[A-Z])", m.group(1).strip()) if s]
    return fiche


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / "annonces_boncompagni.json")
    ap.add_argument("--workers", type=int, default=1,
                    help="la Wayback Machine tolere mal le parallelisme")
    args = ap.parse_args()

    snaps = instantanes()
    print(f"{len(snaps)} instantanes archives")
    fiches = []
    for i, (ts, url) in enumerate(snaps, 1):
        deja = CACHE.exists() and any(CACHE.glob(f"{ts}_*"))
        fiches.append(lire(ts, url))
        if i % 10 == 0:
            print(f"  {i}/{len(snaps)}")
        if not deja:
            time.sleep(1.5)

    fiches.sort(key=lambda f: (f["appartement"], f["chambre"], f["date"]))
    args.out.write_text(json.dumps(fiches, indent=1, ensure_ascii=False))
    print(f"-> {args.out}")

    # une synthese par appartement : ce que les annonces declarent du bati
    for app, etage in APPARTEMENTS.items():
        lot = [f for f in fiches if f["appartement"] == app and "surface_appartement_m2" in f]
        if not lot:
            print(f"\n{app} ({etage}) : rien d'exploitable")
            continue
        d = lot[-1]
        print(f"\n{app} ({etage}) — {len(lot)} fiches exploitables, "
              f"{lot[0]['date']} a {lot[-1]['date']}")
        print(f"  appartement {d['surface_appartement_m2']:.0f} m2, "
              f"etage {d.get('etage','?')}, {d.get('chambres','?')} chambres, "
              f"{d.get('bains','?')} bains, {d.get('occupants','?')} occupants, "
              f"classe {d.get('classe_energetique','?')}")
        surfaces = {}
        for f in lot:
            if "surface_chambre_m2" in f:
                surfaces[f["chambre"]] = f["surface_chambre_m2"]
            for c, v in f.get("autres_chambres", {}).items():
                surfaces.setdefault(c, v["surface_m2"])
        if surfaces:
            tot = sum(surfaces.values())
            print("  chambres : " + ", ".join(f"{c}A {s} m2" for c, s in sorted(surfaces.items()))
                  + f"  (total {tot} m2)")


if __name__ == "__main__":
    main()
