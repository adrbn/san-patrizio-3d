#!/bin/bash
# Vues interieures a refaire, lampes du choeur et de l'atrium ajoutees.
set -u
B=/Applications/Blender.app/Contents/MacOS/Blender
cd "$(dirname "$0")/.."
OBJ=reconstruction/san_patrizio.obj
run(){ # nom lens eye look world samples dossier
  echo "── $1"
  SUNSET=1 SUNAZ=214 SUNEL=6 LAMPES=48 LENS="$2" EYE="$3" LOOK="$4" WORLD="$5" \
  RESX=1600 RESY=1050 \
  "$B" -b -P scripts/render_real.py -- "$OBJ" "rendus/$7/$1.png" 146 12 "$6" \
    >"rendus/$7/$1.log" 2>&1
  [ -f "rendus/$7/$1.png" ] && echo "   ok" || { echo "   ECHEC"; tail -3 "rendus/$7/$1.log"; }
}
run 12_narthex          20 "-1.00,-12.80,1.85" "-1.00,-24.00,3.40"  9.5 300 "."
run 11_abside_int       34 "-1.00,11.00,3.40"  "-1.00,23.00,10.00"  9.0 300 "."
run 09_nef              22 "-1.00,-7.50,1.95"  "-1.00,20.00,6.00"   9.0 300 "."
run 10_choeur           22 "-1.00,18.00,1.95"  "-1.00,-9.50,9.50"   9.0 300 "."
run 4_narthex           22 "-1.00,-18.69,1.95" "-1.00,-11.19,3.25"  9.5 300 "oeuvres"
run 8_conque_abside     35 "-1.08,8.02,3.85"   "-1.08,21.82,9.65"   9.0 300 "oeuvres"
run 9_chapelle_madone   30 "-10.54,9.82,2.25"  "-10.54,21.32,4.15"  9.5 300 "oeuvres"
run 5_cene              40 "-1.00,-1.39,9.65"  "-1.00,-12.29,10.40" 9.0 300 "oeuvres"
run 6_colonnade         24 "-1.00,-6.19,1.95"  "-1.00,13.82,5.15"   9.0 300 "oeuvres"
run 7_caissons          20 "-1.00,3.82,4.65"   "-1.00,13.82,15.85"  9.0 300 "oeuvres"
echo "TERMINE"
