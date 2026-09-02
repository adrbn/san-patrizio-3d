#!/bin/bash
# Les quatre vues interieures, lampes allumees et ciel releve.
set -u
B=/Applications/Blender.app/Contents/MacOS/Blender
cd "$(dirname "$0")/.."
OBJ=reconstruction/san_patrizio.obj
run(){
  echo "── $1"
  SUNSET=1 SUNAZ=214 SUNEL=6 LAMPES=48 LENS="$2" EYE="$3" LOOK="$4" WORLD="$5" \
  RESX=1600 RESY=1050 \
  "$B" -b -P scripts/render_real.py -- "$OBJ" "rendus/$1.png" 146 12 "$6" \
    >"rendus/$1.log" 2>&1
  [ -f "rendus/$1.png" ] && echo "   ok" || { echo "   ECHEC"; tail -3 "rendus/$1.log"; }
}
run 09_nef        22 "-1,-7.5,1.95"  "-1,20,6"      9.0 300
run 10_choeur     22 "-1,18,1.95"    "-1,-9.5,9.5"  9.0 300
run 11_abside_int 34 "-1,11,3.4"     "-1,23,10"     9.0 300
run 12_narthex    20 "-1,-12.8,1.85" "-1,-24,3.4"   9.5 300
echo "TERMINE"
