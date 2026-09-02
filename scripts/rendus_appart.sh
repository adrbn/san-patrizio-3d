#!/bin/bash
# Interieurs du corps de logis : les trois etages releves sur les planches
# DoveVivo, lampes allumees, fin de jour.
set -u
B=/Applications/Blender.app/Contents/MacOS/Blender
cd "$(dirname "$0")/.."
OBJ=reconstruction/san_patrizio.obj
run(){
  echo "── $1"
  SUNSET=1 SUNAZ=214 SUNEL=6 LAMPES="${7:-40}" LENS="$2" EYE="$3" LOOK="$4" WORLD="$5" \
  RESX=1600 RESY=1050 \
  "$B" -b -P scripts/render_real.py -- "$OBJ" "rendus/$1.png" 146 12 "$6" \
    >"rendus/$1.log" 2>&1
  [ -f "rendus/$1.png" ] && echo "   ok" || { echo "   ECHEC"; tail -4 "rendus/$1.log"; }
}
run 21_salon_damier  20 "3.6,-18.4,7.25"   "-3.4,-13.4,6.40"  6.0 300
run 22_cuisine       22 "-7.2,-15.1,7.05"  "-11.8,-12.6,6.35" 6.0 300
run 23_chambre_4A    22 "0.9,-21.3,7.25"   "-2.3,-24.3,6.45"  6.0 300
run 24_couloir       24 "-11.6,-20.2,7.15" "10.4,-20.2,6.70"  6.0 300
run 25_galerie_vide  22 "3.4,-17.6,11.3"   "-3.0,-13.6,7.20"  6.0 300
run 26_terrasse_est  26 "11.2,-24.2,17.5"  "7.6,-14.0,16.1"   0.85 220
run 27_tribune_cene  30 "-1.0,-1.5,10.55"  "-1.0,-11.2,10.45" 8.0 320
echo "TERMINE"
