#!/bin/bash
# Serie au couchant : soleil rasant du sud-ouest, cadrages larges.
set -u
B=/Applications/Blender.app/Contents/MacOS/Blender
cd "$(dirname "$0")/.."
OBJ=reconstruction/san_patrizio.obj
run(){ # nom lens eye look world samples
  echo "── $1"
  SUNSET=1 SUNAZ=214 SUNEL=6 LENS="$2" EYE="$3" LOOK="$4" WORLD="$5" \
  RESX=1600 RESY=1050 \
  "$B" -b -P scripts/render_real.py -- "$OBJ" "rendus/$1.png" 146 12 "$6" \
    >"rendus/$1.log" 2>&1
  [ -f "rendus/$1.png" ] && echo "   ok" || { echo "   ECHEC"; tail -3 "rendus/$1.log"; }
}
run 01_facade_troisquarts 32 "26,-48,9"       "-2,-20,10"     0.85 100
run 02_facade_face        30 "-1,-52,3"       "-1,-25.8,11"   0.85 100
run 03_portail            30 "-1,-34,3.0"     "-1,-25.6,3.8"  1.10 100
run 04_abside             35 "30,42,12"       "-1,24,7"       0.85 100
run 05_aerienne           35 "44,-44,42"      "-1,-2,9"       0.85 100
run 06_flanc_ouest        32 "-42,-6,10"      "-9,-4,10"      0.85 100
run 07_rooftop            22 "11.6,-27.2,18.4" "7.8,-17,16.8" 0.95 100
run 08_rooftop_croix      26 "10.8,-22,17.4"  "-1.5,-13,20.4" 0.95 100
run 09_nef                22 "-1,-7.5,1.95"   "-1,20,6"       3.20 110
run 10_choeur             22 "-1,18,1.95"     "-1,-9.5,9.5"   3.20 110
run 11_abside_int         34 "-1,11,3.4"      "-1,23,10"      3.20 110
run 12_narthex            20 "-1,-12.8,1.85"  "-1,-24,3.4"    3.40 110
echo "TERMINE"
