#!/bin/bash
# Variante de get_config_macos.sh pour macOS 11+ (Big Sur .. Tahoe / macOS 27).
#
# Depuis Big Sur, GeoServices n'existe plus comme fichier autonome sur disque :
# il est fusionne dans le dyld shared cache. On y lit les 2 memes valeurs que
# le script d'origine, sans telecharger les 2 Go de SDK Simulator :
#   - base URL du resource manifest  (marqueur: config%{DEVICE_QUERY})
#   - tokenP1                        (chaine suivant l'alphabet GenRandStr)
#
# IMPORTANT : l'alphabet GenRandStr est une chaine banale presente dans des
# dizaines de binaires du cache. On localise donc d'abord le sous-fichier qui
# contient le marqueur GeoServices, puis on cherche le token DANS CE FICHIER
# uniquement. Sinon on recupere la chaine suivante d'un binaire sans rapport
# (c'est ce qui produisait un config.json invalide).
#
# Compatible bash 3.2 (celui livre avec macOS).
#
# Usage :  ./scripts/get_config_macos_modern.sh > config.json

set -Eeuo pipefail

CACHE_DIR=/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld
MARKER='config%{DEVICE_QUERY}'
ALPHA='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
DQ="?application=geod&application_version=1&country_code=US&hardware=MacBookPro11,2&os=osx&os_build=20B29&os_version=11.0.1"

[ -d "$CACHE_DIR" ] || { echo "dyld shared cache introuvable: $CACHE_DIR" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- 1. localiser le sous-fichier du cache qui contient GeoServices ----------
gsfile=""
for f in "$CACHE_DIR"/dyld_shared_cache_*; do
  printf 'scan %s\r' "$(basename "$f")" >&2
  strings -a "$f" 2>/dev/null > "$tmp/s.txt" || true
  if grep -qF "$MARKER" "$tmp/s.txt"; then
    gsfile="$f"
    break
  fi
done
printf '\033[2K\r' >&2

[ -n "$gsfile" ] || { echo "marqueur GeoServices ($MARKER) introuvable dans le cache" >&2; exit 1; }
echo "GeoServices trouve dans : $(basename "$gsfile")" >&2

# --- 2. base URL (expansion bash, pas de sed a echapper) --------------------
line="$(grep -m1 -F "$MARKER" "$tmp/s.txt")"
base_url="${line%%'%{DEVICE_QUERY}'*}"   # coupe a partir du marqueur
base_url="https://${base_url#*https://}" # jette le bruit avant l'URL

case "$base_url" in
  https://*/*) ;;
  *) echo "base URL invalide apres extraction" >&2; exit 1 ;;
esac
echo "base URL : $base_url" >&2

# --- 3. tokenP1 : la chaine qui suit immediatement l'alphabet GenRandStr -----
awk -v a="$ALPHA" 'prev==a{print; prev=""} {prev=$0}' "$tmp/s.txt" > "$tmp/cand.txt"
n="$(wc -l < "$tmp/cand.txt" | tr -d ' ')"

[ "$n" -ge 1 ] || { echo "tokenP1 introuvable (aucune chaine apres l'alphabet GenRandStr)" >&2; exit 1; }
[ "$n" -eq 1 ] || echo "attention : $n candidats tokenP1, on prend le premier" >&2

token="$(head -n1 "$tmp/cand.txt")"

# --- 4. garde-fous : un token qui casserait le JSON est un mauvais token -----
case "$token" in
  *'"'*|*'\'*) echo "tokenP1 suspect (guillemet ou backslash) -> mauvaise chaine captee" >&2; exit 1 ;;
esac
if ! printf '%s' "$token" | grep -qE '^[[:print:]]{8,128}$'; then
  echo "tokenP1 suspect (longueur ou caracteres inattendus) -> mauvaise chaine captee" >&2
  exit 1
fi
echo "tokenP1 : ${#token} caracteres" >&2

# --- 5. sortie + validation JSON --------------------------------------------
printf '{\n  "resourceManifestURL": "%s%s",\n  "tokenP1": "%s"\n}\n' \
  "$base_url" "$DQ" "$token" > "$tmp/out.json"

python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$tmp/out.json" \
  || { echo "JSON produit invalide, abandon" >&2; exit 1; }

cat "$tmp/out.json"
