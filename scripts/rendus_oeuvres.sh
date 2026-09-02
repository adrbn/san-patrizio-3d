#!/bin/bash
# Une vue par oeuvre. Les prises de vue sont celles de l'index du visualiseur,
# converties du repere Y-up de l'affichage vers le repere Z-up du modele :
#   x = wx - 0.71   y = 1.815 - wz   z = wy - 0.35
set -u
B=/Applications/Blender.app/Contents/MacOS/Blender
cd "$(dirname "$0")/.."
OBJ=reconstruction/san_patrizio.obj
run(){ # nom lens eye look world samples
  echo "── $1"
  SUNSET=1 SUNAZ=214 SUNEL=6 LAMPES=48 LENS="$2" EYE="$3" LOOK="$4" WORLD="$5" \
  RESX=1500 RESY=1050 \
  "$B" -b -P scripts/render_real.py -- "$OBJ" "rendus/oeuvres/$1.png" 146 12 "$6" \
    >"rendus/oeuvres/$1.log" 2>&1
  [ -f "rendus/oeuvres/$1.png" ] && echo "   ok" || { echo "   ECHEC"; tail -3 "rendus/oeuvres/$1.log"; }
}
mkdir -p rendus/oeuvres
run 1_mosaique_fronton 85 "-1.00,-39.19,15.25" "-1.00,-25.49,18.95" 1.00 120
run 2_tympan_portail   50 "-1.00,-31.59,3.35"  "-1.00,-25.19,3.60"  1.15 120
run 3_armoiries        85 "3.30,-28.59,2.75"   "3.30,-25.49,2.82"   1.15 120
run 4_narthex          22 "-1.00,-18.69,1.95"  "-1.00,-11.19,3.25"  9.5  300
run 5_cene             40 "-1.00,-1.39,9.65"   "-1.00,-12.29,10.40" 9.0  300
run 6_colonnade        24 "-1.00,-6.19,1.95"   "-1.00,13.82,5.15"   9.0  300
run 7_caissons         20 "-1.00,3.82,4.65"    "-1.00,13.82,15.85"  9.0  300
run 8_conque_abside    35 "-1.08,8.02,3.85"    "-1.08,21.82,9.65"   9.0  300
run 9_chapelle_madone  30 "-10.54,9.82,2.25"   "-10.54,21.32,4.15"  9.5  300
echo "TERMINE"
