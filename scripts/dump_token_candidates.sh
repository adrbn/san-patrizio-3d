#!/bin/bash
# Enumere les candidats plausibles pour tokenP1 depuis le dyld shared cache.
#
# tokenP1 est un secret statique du binaire GeoServices. Historiquement il
# suivait immediatement l'alphabet GenRandStr (abc..XYZ0..9) ; le script
# officiel l'extrait ainsi. Mais dans le cache fusionne de macOS moderne, le
# dedoublonnage de chaines separe l'alphabet du token : "la ligne juste apres"
# ne suffit plus.
#
# Strategie : reperer le sous-cache contenant GeoServices (marqueur
# config%{DEVICE_QUERY}), puis emettre TOUTES les chaines dans une FENETRE
# autour de chaque occurrence de l'alphabet / de "xyzABC". find-token essaiera
# chaque candidat contre l'endpoint C3MM reel.
#
# Usage :  bash scripts/dump_token_candidates.sh > token_candidates.txt

set -Eeuo pipefail

CACHE_DIR=/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld
MARKER='config%{DEVICE_QUERY}'
ALPHA='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
WINDOW=40   # nb de chaines emises de part et d'autre de chaque ancre

[ -d "$CACHE_DIR" ] || { echo "dyld shared cache introuvable: $CACHE_DIR" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

: > "$tmp/cand.txt"
found=0

for f in "$CACHE_DIR"/dyld_shared_cache_*; do
  printf 'scan %s\r' "$(basename "$f")" >&2

  # un seul dump strings par fichier (evite le SIGPIPE de "strings | grep -q")
  strings -a "$f" 2>/dev/null > "$tmp/s.txt" || true
  grep -qF "$MARKER" "$tmp/s.txt" || continue

  found=1
  echo "GeoServices trouve dans : $(basename "$f")" >&2

  # fenetre autour de chaque ligne == alphabet exact, ou contenant "xyzABC"
  awk -v W="$WINDOW" -v a="$ALPHA" '
    { line[NR]=$0 }
    $0==a || index($0,"xyzABC")>0 { anchor[NR]=1 }
    END {
      for (n in anchor)
        for (i=n-W; i<=n+W; i++)
          if (i>=1 && i in line) print line[i]
    }
  ' "$tmp/s.txt" >> "$tmp/cand.txt"
done
printf '\033[2K\r' >&2

[ "$found" -eq 1 ] || { echo "marqueur GeoServices ($MARKER) introuvable dans le cache" >&2; exit 1; }

# --- filtre token-like + dedup ----------------------------------------------
# imprimable, 12..64 car, sans guillemet/backslash/espace, au moins une lettre.
grep -E '^[[:graph:]]{12,64}$' "$tmp/cand.txt" \
  | grep -v '[\"\\]' \
  | grep -E '[A-Za-z]' \
  | sort -u > "$tmp/final.txt"

wc -l < "$tmp/final.txt" | awk '{printf "candidats retenus : %s\n",$1}' >&2
cat "$tmp/final.txt"
