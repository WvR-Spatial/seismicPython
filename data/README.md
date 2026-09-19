# Vendored data

## `ne_10m_populated_places.geojson`

7,342 populated places, derived from Natural Earth **1:10m** Populated Places
(simple), tag `v5.1.2` of
[`nvkelso/natural-earth-vector`](https://github.com/nvkelso/natural-earth-vector).

Natural Earth is in the **public domain**; no attribution is required, though
it is offered on the dashboard as a courtesy.

### Why this layer, and why vendored

The original pipeline used the **1:110m** layer, which contains only **243**
cities worldwide — a world-overview cartographic layer, not a settlement
database. With 243 candidates, a week of global seismicity typically produced
zero or one "impacted city", which made the analysis look like it was working
while telling you almost nothing. The 1:10m layer has 30x the coverage and picks
up the mid-size towns that actually sit near active faults.

It is committed to the repository rather than downloaded at run time because a
scheduled build should not fail because a third-party CDN had a bad morning.
The previous code pulled cities from `d2ad6b4ur7yvpq.cloudfront.net`, a
Mapzen-era mirror that is no longer maintained.

### Processing applied

`tools/vendor_cities.py` reduces the upstream file from 4.9 MB to ~1.6 MB by:

* keeping only `name`, `adm0name`, `adm1name`, `iso_a2`, `pop_max`, `adm0cap`
  and `ne_id`;
* coercing `pop_max` to an integer;
* rounding coordinates to 5 decimal places (about 1 m at the equator).

Re-run that script to refresh the snapshot or move to a newer Natural Earth tag.

### If you need more coverage

For town-level screening, swap in GeoNames `cities15000` (~25,000 places,
CC BY 4.0 — attribution required) or `cities5000`. Point `--cities` at any
GeoJSON with `name` and `pop_max` columns and the pipeline will use it.
