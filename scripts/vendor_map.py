"""Vendor MapLibre GL JS and the OpenFreeMap Positron style into src/fn/web/static.

Run: python3 scripts/vendor_map.py [VERSION]. It downloads the npm tarball, checks it against the
registry's dist.integrity, copies the dist files and writes vendor.json with the sha256 of every file.
"""
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "fn" / "web" / "static"
VERSION = sys.argv[1] if len(sys.argv) > 1 else "5.24.0"
FILES = {"package/dist/maplibre-gl.js": "maplibre-gl.js", "package/dist/maplibre-gl.css": "maplibre-gl.css",
         "package/LICENSE.txt": "maplibre-gl.LICENSE.txt"}
STYLE_URL = "https://tiles.openfreemap.org/styles/positron"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "fn-vendor-map"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> None:
    dist = json.loads(get(f"https://registry.npmjs.org/maplibre-gl/{VERSION}"))["dist"]
    tarball = get(dist["tarball"])
    algorithm, expected = dist["integrity"].split("-", 1)
    actual = base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode()
    if actual != expected:
        sys.exit(f"tarball integrity mismatch: registry {dist['integrity']}, downloaded {algorithm}-{actual}")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(tarball)) as archive:
        for member, name in FILES.items():
            files[name] = archive.extractfile(member).read()
    files["positron.json"] = json.dumps(json.loads(get(STYLE_URL)), indent=2).encode() + b"\n"
    for name, data in files.items():
        (STATIC / name).write_bytes(data)
    manifest = {"package": "maplibre-gl", "version": VERSION, "integrity": dist["integrity"],
                "style": STYLE_URL, "sha256": {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}}
    (STATIC / "vendor.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


main()
