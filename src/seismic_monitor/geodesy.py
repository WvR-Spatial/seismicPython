"""Geodesic geometry helpers.

The original version of this project buffered points in Web Mercator
(EPSG:3857) and treated the result as a distance in metres. Web Mercator is
conformal but *not* equidistant: a metre on the projected plane corresponds to
``cos(latitude)`` metres on the ground. A nominal 50 km buffer therefore covered
only ~25 km at 60 degrees of latitude and ~13 km at 75 degrees -- exactly the
latitudes where a lot of seismicity happens (Alaska, the Aleutians, Kamchatka,
Iceland).

Everything here works on the WGS84 ellipsoid via ``pyproj.Geod``, so a 50 km
radius is 50 km everywhere.
"""

from __future__ import annotations

from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

GEOD = Geod(ellps="WGS84")

WORLD = box(-180.0, -90.0, 180.0, 90.0)
_MAX_LAT = 89.999999


def geodesic_circle(
    lon: float,
    lat: float,
    radius_m: float,
    segments: int = 180,
) -> Polygon:
    """A true geodesic circle of ``radius_m`` around ``(lon, lat)``.

    Longitudes are returned *unwrapped*: a circle centred at 179.5E extends past
    180, and one centred at 179.5W extends below -180. Splitting that into two
    map-safe halves is :func:`split_antimeridian`'s job, which keeps the geometry
    correct while it is still being reasoned about numerically.
    """
    if segments < 8:
        raise ValueError("segments must be >= 8 for a usable circle")
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")

    azimuths = [360.0 * i / segments for i in range(segments)]
    lons, lats, _ = GEOD.fwd(
        [lon] * segments,
        [lat] * segments,
        azimuths,
        [radius_m] * segments,
    )

    # Unwrap longitudes so the ring stays continuous across the date line.
    unwrapped = []
    for x in lons:
        while x - lon > 180.0:
            x -= 360.0
        while x - lon < -180.0:
            x += 360.0
        unwrapped.append(x)

    clamped = [max(-_MAX_LAT, min(_MAX_LAT, y)) for y in lats]
    ring = list(zip(unwrapped, clamped, strict=True))

    if _contains_pole(lat, radius_m):
        return _polar_cap(ring, north=lat > 0)

    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _contains_pole(lat: float, radius_m: float) -> bool:
    """True when a circle of this radius swallows the nearest pole."""
    # Distance from the centre to the pole along a meridian.
    pole_lat = 90.0 if lat >= 0 else -90.0
    _, _, distance = GEOD.inv(0.0, lat, 0.0, pole_lat)
    return distance <= radius_m


def _polar_cap(ring: list[tuple[float, float]], north: bool) -> Polygon:
    """Close a pole-enclosing circle into a valid cap spanning all longitudes.

    A ring that encircles a pole has no consistent winding in lon/lat space, so
    it is replaced by the rectangle from its extreme latitude to the pole. This
    is slightly generous, but it only triggers within ``radius`` of a pole where
    there are no populated places to mis-classify.
    """
    lats = [y for _, y in ring]
    edge = min(lats) if north else max(lats)
    top, bottom = (_MAX_LAT, edge) if north else (edge, -_MAX_LAT)
    return box(-180.0, bottom, 180.0, top)


def split_antimeridian(geom: BaseGeometry) -> BaseGeometry:
    """Wrap a geometry with out-of-range longitudes back into [-180, 180].

    Anything east of 180 is translated 360 degrees west and anything west of
    -180 is translated 360 degrees east, producing a MultiPolygon with a piece
    on each side of the map instead of a band smeared across the whole world.
    """
    if geom.is_empty:
        return geom

    minx, _, maxx, _ = geom.bounds
    if minx >= -180.0 and maxx <= 180.0:
        return geom

    parts: list[BaseGeometry] = []

    inside = geom.intersection(WORLD)
    if not inside.is_empty:
        parts.append(inside)

    if maxx > 180.0:
        overflow = geom.intersection(box(180.0, -90.0, maxx + 1.0, 90.0))
        if not overflow.is_empty:
            parts.append(_translate_x(overflow, -360.0))

    if minx < -180.0:
        overflow = geom.intersection(box(minx - 1.0, -90.0, -180.0, 90.0))
        if not overflow.is_empty:
            parts.append(_translate_x(overflow, 360.0))

    if not parts:
        return geom

    merged = unary_union(parts)
    if isinstance(merged, Polygon):
        merged = MultiPolygon([merged])
    return merged


def _translate_x(geom: BaseGeometry, xoff: float) -> BaseGeometry:
    from shapely.affinity import translate

    return translate(geom, xoff=xoff)
