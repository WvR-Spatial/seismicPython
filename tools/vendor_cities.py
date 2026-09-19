#!/usr/bin/env python3
"""Rebuild the vendored populated-places layer.

The layer is vendored deliberately. The previous version pulled cities from
``d2ad6b4ur7yvpq.cloudfront.net``, a long-dead Mapzen-era mirror, at run time --
a single point of failure for every scheduled build. This script pulls from a
*pinned tag* of the canonical Natural Earth vector repository, drops the columns
the analysis never touches and rounds coordinates to 5 decimal places (~1 m),
taking the file from 4.9 MB to ~1.6 MB.

Run it only when you want to change the source or refresh the release:

    python tools/vendor_cities.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

NE_TAG = "v5.1.2"
SOURCE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{NE_TAG}/geojson/ne_10m_populated_places_simple.geojson"
)
DEST = Path(__file__).resolve().parents[1] / "data" / "ne_10m_populated_places.geojson"

KEEP = ["name", "adm0name", "adm1name", "iso_a2", "pop_max", "adm0cap", "ne_id"]


def main() -> int:
    print(f"Downloading {SOURCE}")
    with urllib.request.urlopen(SOURCE, timeout=120) as response:  # noqa: S310
        source = json.load(response)

    features = []
    for feature in source["features"]:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        slim = {key: props.get(key) for key in KEEP}
        slim["pop_max"] = int(props.get("pop_max") or 0)
        slim["adm0cap"] = int(props.get("adm0cap") or 0)
        slim["ne_id"] = int(props.get("ne_id") or 0)
        features.append(
            {
                "type": "Feature",
                "properties": slim,
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(lon), 5), round(float(lat), 5)],
                },
            }
        )

    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with DEST.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {len(features):,} places to {DEST} ({DEST.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
