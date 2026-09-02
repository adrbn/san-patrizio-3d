# San Patrizio a Villa Ludovisi — relevé et reconstruction volumétrique

Via Boncompagni 31, Rome. Église nationale irlandaise et américaine,
Aristide Leonori, 1908-1911, et les trois étages de logement qui la
surmontent côté rue.

Le modèle n'est pas un scan nettoyé : c'est un **générateur paramétrique**.
Un script Python émet la géométrie, un autre la convertit, un troisième
fabrique le visualiseur. Rien n'est modelé à la main, tout se rejoue.

## Ce sur quoi le modèle est calé

| Source | Ce qu'elle fixe |
|---|---|
| OSM way 203996025 | l'emprise au sol (résidu du fit d'abside : 0,18 m) |
| Maillage Apple Flyover | les hauteurs, mesurées par profils dans l'emprise |
| Planches DoveVivo (piano primo / secondo / terzo) | le plan des trois étages de logement, au trait |
| Photographies sur place et annonce immobilière | matériaux, couleurs, mobilier, mosaïques |

Contrôle : 23,52 × 12,52 = 294 m² par niveau, l'annonce en déclare 290 ;
la chambre 4A mesure 15 m² bow-window compris, exactement la surface annoncée.

## Fabriquer

```bash
python3 scripts/build_church.py    # -> reconstruction/san_patrizio.obj + .mtl
python3 scripts/to_yup.py          # -> convention Y-up, posé au sol, centré
python3 scripts/make_viewer.py     # -> reconstruction/geom.json
python3 scripts/assemble.py        # -> reconstruction/viewer.html
```

`reconstruction/viewer.html` est autonome : un seul fichier, aucun serveur,
aucune dépendance. On l'ouvre dans un navigateur.

## Le visualiseur

WebGL2, ombrage plat par dérivées d'écran, positions quantifiées en Int16
(2 mm), sélection par identifiant de matériau dans un tampon hors écran.

- **Coupé en long** — coupe verticale qui ouvre la nef
- **Vu de dessus** — le toit s'enlève, une réglette choisit la hauteur
- **Plan** — projection parallèle, coupe à 1,25 m du sol, quatre niveaux,
  murs en poché, nom et surface écrits au sol de chaque pièce
- **Balade** — caméra à hauteur d'yeux, clavier et souris, les portes
  s'ouvrent à l'approche, légende discrète sur ce qu'on regarde
- **Visite** — parcours guidé, arrêts de trois secondes sur les œuvres
- **Œuvres** — index cliquable, la caméra va se placer devant

## Rendus

```bash
bash scripts/rendus_soir.sh        # extérieurs au couchant
bash scripts/rendus_interieur.sh   # nef, chœur, abside, narthex
bash scripts/rendus_appart.sh      # les étages de logement
```

Cycles, via Blender en ligne de commande. Chaque vue prend une quinzaine de
minutes ; le script est réglé pour n'en lancer qu'une à la fois.

## Provenance du code Go

`cmd/`, `pkg/`, `proto/` et `vendor/` viennent de
[retroplasma/flyover-reverse-engineering](https://github.com/retroplasma/flyover-reverse-engineering)
(remote `upstream`) : c'est l'outil qui télécharge et décode le maillage
Apple Flyover. `config.json` n'est pas versionné — il porte un jeton
personnel, à regénérer avec `cmd/find-token`.

## Limites assumées

- Le second étage suit le relevé DoveVivo ; le mobilier y est déduit du premier.
- Les armoiries sont restituées d'après photographie, le dessin héraldique
  reste schématique.
- La Cène et les mosaïques sont des restitutions haute définition, pas des
  relevés photogrammétriques.
- Les hauteurs sous plafond intérieures découlent des allèges mesurées en
  façade (2,10 / 6,90 / 11,00 m), pas d'un relevé intérieur.
