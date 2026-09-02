#!/bin/bash
# Chiesa di San Patrizio a Villa Ludovisi - Via Boncompagni 31, Roma
# OSM way 203996025 | emprise batiment 40 x 57 m
# z20 -> 1 tuile ~= 28,4 m au sol a cette latitude
#   tryXY=2 -> 5x5 tuiles ~= 142 x 142 m (eglise + parcelle)
#   tryXY=3 -> 7x7 tuiles ~= 199 x 199 m (ilot complet, marge confortable)
set -Eeuo pipefail
LAT=41.9085883
LON=12.4929342
ZOOM=${1:-20}
TRYXY=${2:-3}
TRYH=${3:-40}
go run ./cmd/export-obj "$LAT" "$LON" "$ZOOM" "$TRYXY" "$TRYH" --parallel
