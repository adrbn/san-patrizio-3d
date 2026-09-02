#!/usr/bin/env python3
"""Assemble le visualiseur : geometrie + images des notices dans le gabarit."""
import base64, json, mimetypes, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__)) + "/.."
geom = json.load(open(f"{ROOT}/reconstruction/geom.json"))
pics = {}
ndir = f"{ROOT}/assets/notices"
for f in sorted(os.listdir(ndir)):
    name, ext = os.path.splitext(f)
    mime = mimetypes.guess_type(f)[0]
    if not mime or not mime.startswith("image/"):
        continue
    with open(f"{ndir}/{f}", "rb") as fh:
        pics[name] = f"data:{mime};base64," + base64.b64encode(fh.read()).decode()

html = open(f"{ROOT}/scripts/viewer.tpl.html").read()
assert "__GEOM__" in html and "__PICS__" in html, "gabarit sans marqueur"
html = html.replace("__GEOM__", json.dumps(geom, separators=(",", ":")))
html = html.replace("__PICS__", json.dumps(pics, separators=(",", ":")))
for dest in (f"{ROOT}/reconstruction/viewer.html", f"{ROOT}/../.preview/index.html"):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "w").write(html)
print(f"viewer.html {len(html)/1024/1024:.2f} Mo  — {len(pics)} images de notice")
