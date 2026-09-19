"""Output rendering: the interactive map, the ranked chart and the landing page."""

from __future__ import annotations

import html
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import folium
import geopandas as gpd
import plotly.graph_objects as go
from folium import plugins

from . import theme
from .config import Config

log = logging.getLogger(__name__)

MAP_FILENAME = "seismic_risk_map.html"
CHART_FILENAME = "risk_chart.html"
CHART_PNG = "risk_chart.png"
SUMMARY_FILENAME = "summary.json"
CITIES_CSV = "impacted_cities.csv"
EVENTS_GEOJSON = "impact_zones.geojson"
INDEX_FILENAME = "index.html"

# Columns folium is allowed to serialise (no datetimes, no numpy time types).
_ZONE_FIELDS = ["title", "mag", "place", "depth_km", "url"]


def render_all(
    zones: gpd.GeoDataFrame,
    pairs: gpd.GeoDataFrame,
    summary: gpd.GeoDataFrame,
    digest: dict,
    config: Config,
) -> dict[str, Path]:
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if "generated_at_utc" not in digest:
        digest["generated_at_utc"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    paths: dict[str, Path] = {}
    paths["map"] = _render_map(zones, summary, digest, out, config)
    paths["chart"] = _render_chart(summary, out, config)
    if config.chart_png:
        png = _render_chart_png(summary, out, config)
        if png is not None:
            paths["chart_png"] = png
    paths["summary"] = _write_json(out / SUMMARY_FILENAME, digest)
    paths["cities_csv"] = _write_cities_csv(summary, out)
    paths["zones_geojson"] = _write_zones(zones, out)
    paths["index"] = _render_index(digest, summary, out, config)
    paths["legacy_redirect"] = _write_legacy_redirect(out)
    return paths


# --------------------------------------------------------------------------- map


def _render_map(
    zones: gpd.GeoDataFrame,
    summary: gpd.GeoDataFrame,
    digest: dict,
    out: Path,
    config: Config,
) -> Path:
    log.info("Rendering interactive map")
    fmap = folium.Map(
        location=[10, 0],
        zoom_start=2,
        tiles=None,
        world_copy_jump=True,
        control_scale=True,
    )
    _add_basemaps(fmap, config)

    if not zones.empty:
        heat = [
            [float(row.epicentre_lat), float(row.epicentre_lon), float(row.mag)]
            for row in zones.itertuples()
        ]
        plugins.HeatMap(
            heat,
            name="Epicentre density",
            min_opacity=0.35,
            radius=22,
            blur=18,
            gradient=theme.HEAT_GRADIENT,
        ).add_to(fmap)

        zone_view = zones[[c for c in _ZONE_FIELDS if c in zones.columns] + ["geometry"]].copy()
        for column in ("mag", "depth_km"):
            if column in zone_view:
                zone_view[column] = zone_view[column].astype(float).round(2)

        folium.GeoJson(
            zone_view.to_json(),
            name=f"Impact zones ({config.radius_km:g} km)",
            style_function=lambda _: {
                "fillColor": theme.HAZARD,
                "color": theme.HAZARD,
                "fillOpacity": 0.08,
                "weight": 1.5,
            },
            highlight_function=lambda _: {"fillOpacity": 0.25, "weight": 2.5},
            tooltip=folium.GeoJsonTooltip(
                fields=[c for c in ("title", "mag", "depth_km") if c in zone_view],
                aliases=["Event", "Magnitude", "Depth (km)"],
                sticky=True,
                style=(
                    f"background:{theme.SURFACE_1};color:{theme.TEXT_PRIMARY};"
                    f"border:1px solid {theme.SURFACE_2};border-radius:6px;"
                    f"padding:8px 10px;font-family:{theme.FONT_STACK};font-size:12px;"
                ),
            ),
        ).add_to(fmap)

    if not summary.empty:
        cities = folium.FeatureGroup(name="Affected populated places", show=True)
        for row in summary.itertuples():
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=_marker_radius(row.pop_max),
                color=theme.SURFACE_1,
                weight=1,
                fill=True,
                fill_color=theme.CITY,
                fill_opacity=0.85,
                popup=folium.Popup(_city_popup(row), max_width=280),
                tooltip=str(row.name if hasattr(row, "name") else ""),
            ).add_to(cities)
        cities.add_to(fmap)
        _fit_to_data(fmap, summary)
    elif not zones.empty:
        _fit_to_data(fmap, zones)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.get_root().html.add_child(folium.Element(_map_overlay(digest, config)))

    path = out / MAP_FILENAME
    fmap.save(str(path))
    return path


def resolve_token(key: str, config: Config) -> str | None:
    """Find the access token for a basemap, or None if it needs none.

    Order of precedence: an explicit ``--mapbox-token``, then the environment
    variable named by the basemap's ``token_env``. Tokens are never read from,
    or written to, the repository.
    """
    spec = theme.BASEMAPS.get(key, {})
    env_name = spec.get("token_env")
    if not env_name:
        return None
    if env_name == "MAPBOX_TOKEN" and config.mapbox_token:
        return config.mapbox_token
    return os.environ.get(env_name) or None


def _resolve_basemap(key: str, config: Config) -> tuple[str, dict, str]:
    """Return ``(key, spec, url)`` for a basemap, falling back if it has no token.

    A token-bearing basemap without a token renders either nothing (Mapbox 401s)
    or an "API KEY REQUIRED" watermark (CARTO), so it is better to quietly use
    the keyless default and say so in the log than to publish a broken map.
    """
    spec = theme.BASEMAPS[key]
    env_name = spec.get("token_env")
    if not env_name:
        return key, spec, spec["url"]

    token = resolve_token(key, config)
    if not token:
        log.warning(
            "Basemap %r needs %s but none was found; using %r instead.",
            key,
            env_name,
            theme.DEFAULT_BASEMAP,
        )
        fallback = theme.DEFAULT_BASEMAP
        return fallback, theme.BASEMAPS[fallback], theme.BASEMAPS[fallback]["url"]

    return key, spec, spec["url"].replace("{token}", quote(token, safe=""))


def _add_basemaps(fmap: folium.Map, config: Config) -> None:
    """Add the chosen basemap plus one keyless alternative."""
    requested = config.basemap if config.basemap in theme.BASEMAPS else theme.DEFAULT_BASEMAP
    key, spec, url = _resolve_basemap(requested, config)

    layers = [(key, spec, url)]
    if key != theme.FALLBACK_BASEMAP:
        fallback = theme.BASEMAPS[theme.FALLBACK_BASEMAP]
        layers.append((theme.FALLBACK_BASEMAP, fallback, fallback["url"]))

    for index, (_key, layer_spec, layer_url) in enumerate(layers):
        folium.TileLayer(
            tiles=layer_url,
            attr=layer_spec["attr"],
            name=layer_spec["name"],
            max_zoom=int(layer_spec["max_zoom"]),
            control=True,
            overlay=False,
            show=index == 0,
        ).add_to(fmap)


def _marker_radius(population: int) -> float:
    population = max(int(population or 0), 1)
    return max(4.0, min(16.0, 2.2 * math.log10(population)))


def _city_popup(row) -> str:
    name = html.escape(str(getattr(row, "name", "Unknown")))
    country = html.escape(str(getattr(row, "adm0name", "") or ""))
    region = html.escape(str(getattr(row, "adm1name", "") or ""))
    population = int(getattr(row, "pop_max", 0) or 0)
    max_mag = float(getattr(row, "max_magnitude", 0) or 0)
    nearest_km = float(getattr(row, "nearest_event_km", 0) or 0)
    events = int(getattr(row, "event_count", 0) or 0)
    event_title = html.escape(str(getattr(row, "title", "") or ""))
    url = getattr(row, "url", "") or ""

    place = " / ".join(p for p in (region, country) if p)
    link = (
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener" '
        f'style="color:{theme.CITY};">USGS event page</a>'
        if url
        else ""
    )
    return f"""
    <div style="font-family:{theme.FONT_STACK};width:240px;color:{theme.TEXT_PRIMARY};">
      <div style="font-size:15px;font-weight:600;">{name}</div>
      <div style="font-size:11px;color:{theme.TEXT_MUTED};margin-bottom:8px;">{place}</div>
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr><td style="color:{theme.TEXT_MUTED};">Population</td>
            <td style="text-align:right;">{population:,}</td></tr>
        <tr><td style="color:{theme.TEXT_MUTED};">Strongest event</td>
            <td style="text-align:right;">M {max_mag:.1f}</td></tr>
        <tr><td style="color:{theme.TEXT_MUTED};">Nearest epicentre</td>
            <td style="text-align:right;">{nearest_km:.0f} km</td></tr>
        <tr><td style="color:{theme.TEXT_MUTED};">Events in range</td>
            <td style="text-align:right;">{events}</td></tr>
      </table>
      <div style="font-size:11px;color:{theme.TEXT_MUTED};margin-top:8px;">{event_title}</div>
      <div style="font-size:11px;margin-top:4px;">{link}</div>
    </div>
    """


def _fit_to_data(fmap: folium.Map, gdf: gpd.GeoDataFrame) -> None:
    """Zoom to the data rather than a hard-coded corner of the Pacific."""
    minx, miny, maxx, maxy = gdf.total_bounds
    if any(map(math.isnan, (minx, miny, maxx, maxy))):
        return
    pad_x = max((maxx - minx) * 0.08, 1.0)
    pad_y = max((maxy - miny) * 0.08, 1.0)
    fmap.fit_bounds(
        [
            [max(miny - pad_y, -85), max(minx - pad_x, -180)],
            [min(maxy + pad_y, 85), min(maxx + pad_x, 180)],
        ]
    )


def _map_overlay(digest: dict, config: Config) -> str:
    """A title block and a legend, baked into the map page."""
    generated = _human_time(digest.get("generated_at_utc", ""))
    return f"""
    <style>
      html, body, .folium-map, .leaflet-container {{
        background: {theme.SURFACE_0} !important;
      }}
      .leaflet-control-attribution {{
        background: {theme.SURFACE_1}cc !important; color: {theme.TEXT_MUTED} !important;
      }}
      .leaflet-control-attribution a {{ color: {theme.TEXT_SECONDARY} !important; }}
      .leaflet-control-layers {{
        background: {theme.SURFACE_1} !important; color: {theme.TEXT_PRIMARY} !important;
        border: 1px solid {theme.SURFACE_2} !important;
      }}
      .srm-panel {{
        position: fixed; z-index: 9999;
        background: {theme.SURFACE_1}ee; color: {theme.TEXT_PRIMARY};
        border: 1px solid {theme.SURFACE_2}; border-radius: 8px;
        padding: 10px 12px; font-family: {theme.FONT_STACK}; font-size: 12px;
        box-shadow: 0 4px 16px rgba(0,0,0,.45);
      }}
      .srm-title {{ top: 12px; left: 12px; max-width: min(320px, 60vw); }}
      .srm-title h1 {{ margin: 0 0 4px; font-size: 15px; font-weight: 600; letter-spacing: .01em; }}
      .srm-legend {{ bottom: 22px; left: 12px; }}
      .srm-legend div {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
      .srm-swatch {{ width: 12px; height: 12px; border-radius: 3px; flex: 0 0 auto; }}
      .srm-meta {{ color: {theme.TEXT_MUTED}; font-size: 11px; }}
      @media (max-width: 640px) {{ .srm-legend {{ display: none; }} }}
    </style>
    <div class="srm-panel srm-title">
      <h1>{html.escape(config.site_title)}</h1>
      <div class="srm-meta">
        Populated places within {config.radius_km:g}&nbsp;km of an
        M&nbsp;{config.min_magnitude:g}+ event &middot; USGS {html.escape(config.feed)} feed
      </div>
      <div class="srm-meta" style="margin-top:4px;">Generated {html.escape(generated)}</div>
    </div>
    <div class="srm-panel srm-legend">
      <div><span class="srm-swatch" style="background:{theme.HAZARD};"></span>
           Impact zone ({config.radius_km:g} km geodesic)</div>
      <div><span class="srm-swatch" style="background:{theme.CITY};"></span>
           Affected place (size = population)</div>
      <div><span class="srm-swatch" style="background:linear-gradient(90deg,{theme.HEAT_GRADIENT[0.30]},{theme.HAZARD_BRIGHT});"></span>
           Epicentre density</div>
    </div>
    """


# ------------------------------------------------------------------------- chart


def _chart_figure(summary: gpd.GeoDataFrame, config: Config) -> go.Figure | None:
    """A dot plot of the strongest event reaching each place.

    Deliberately not a bar chart. Every value in this chart is at or above the
    magnitude threshold, so bars anchored at zero would all be within ~25% of
    each other and the ranking would be unreadable. A dot plot encodes position
    rather than length, so the axis can legitimately start at the threshold and
    the spread becomes visible. The faint leader line is a tracking aid from the
    label to the dot, not a length encoding.
    """
    if summary.empty:
        return None

    top = summary.head(config.max_chart_cities).iloc[::-1]  # strongest at the top
    countries = (
        top["adm0name"].fillna("").astype(str).map(_shorten)
        if "adm0name" in top.columns
        else [""] * len(top)
    )
    labels = [
        f"{n}<br><span style='font-size:10px;color:{theme.TEXT_MUTED}'>{c}</span>"
        for n, c in zip(top["name"].astype(str), countries, strict=True)
    ]
    magnitudes = top["max_magnitude"].astype(float).tolist()

    axis_min = min(config.min_magnitude, min(magnitudes)) - 0.15
    axis_max = max(magnitudes) + 0.45

    fig = go.Figure()

    # Leader lines, drawn under the dots.
    for index, value in enumerate(magnitudes):
        fig.add_shape(
            type="line",
            x0=axis_min, x1=value, y0=index, y1=index,
            xref="x", yref="y",
            line=dict(color=theme.SURFACE_2, width=1),
            layer="below",
        )

    fig.add_trace(
        go.Scatter(
            x=magnitudes,
            y=labels,
            mode="markers+text",
            # One series, one colour: position already encodes magnitude, so a
            # value-ramp across nominal places would double-encode it.
            marker=dict(
                color=theme.HAZARD,
                size=13,
                line=dict(color=theme.SURFACE_1, width=2),  # 2px surface ring
            ),
            text=[f"M {v:.1f}" for v in magnitudes],
            textposition="middle right",
            textfont=dict(color=theme.TEXT_SECONDARY, size=11),
            cliponaxis=False,
            customdata=list(
                zip(
                    top["pop_max"].astype(int),
                    top["nearest_event_km"].astype(float).round(0),
                    top["event_count"].astype(int),
                    strict=True,
                )
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Strongest event: M %{x:.1f}<br>"
                "Population: %{customdata[0]:,}<br>"
                "Nearest epicentre: %{customdata[1]:.0f} km<br>"
                "Events in range: %{customdata[2]}"
                "<extra></extra>"
            ),
            hoverlabel=dict(
                bgcolor=theme.SURFACE_1,
                bordercolor=theme.SURFACE_2,
                font=dict(color=theme.TEXT_PRIMARY, family=theme.FONT_STACK, size=12),
            ),
        )
    )

    fig.update_layout(
        title=dict(
            text=(
                "Affected places by strongest nearby event"
                f"<br><span style='font-size:11px;color:{theme.TEXT_MUTED}'>"
                f"Showing {len(top)} of {len(summary)} \u00b7 axis starts at the "
                f"M{config.min_magnitude:g} threshold, not zero</span>"
            ),
            font=dict(size=16, color=theme.TEXT_PRIMARY, family=theme.FONT_STACK),
            x=0,
            xanchor="left",
            xref="container",
            y=1.0,
            yanchor="top",
            yref="container",
            pad=dict(t=14, l=16),
        ),
        paper_bgcolor=theme.SURFACE_1,
        plot_bgcolor=theme.SURFACE_1,
        font=dict(family=theme.FONT_STACK, color=theme.TEXT_SECONDARY, size=12),
        margin=dict(l=8, r=48, t=80, b=44),
        height=chart_height(len(top)),
        showlegend=False,
        hovermode="closest",
        xaxis=dict(
            title="Moment magnitude",
            range=[axis_min, axis_max],
            gridcolor=theme.SURFACE_2,
            zeroline=False,
            showline=False,
            ticks="outside",
            tickcolor=theme.SURFACE_2,
            dtick=0.5,
        ),
        yaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            automargin=True,
            ticklabelstandoff=14,
        ),
    )
    return fig


def chart_height(rows: int) -> int:
    """Figure height, shared with the iframe that embeds it so nothing clips."""
    return max(320, 36 * max(rows, 1) + 130)


def _shorten(value: str, limit: int = 22) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "\u2026"




def _render_chart(summary: gpd.GeoDataFrame, out: Path, config: Config) -> Path:
    path = out / CHART_FILENAME
    fig = _chart_figure(summary, config)
    if fig is None:
        path.write_text(_empty_chart_html(), encoding="utf-8")
        return path

    log.info("Rendering ranked chart")
    # include_plotlyjs="cdn" keeps this file ~40 KB. Inlining plotly.js is what
    # made the previous risk_chart.html 4.5 MB.
    fig.write_html(
        str(path),
        include_plotlyjs="cdn",
        full_html=True,
        config={"displayModeBar": False, "responsive": True},
    )
    content = path.read_text(encoding="utf-8").replace(
        "<body>", f'<body style="margin:0;background:{theme.SURFACE_1};">', 1
    )
    path.write_text(content, encoding="utf-8")
    return path


def _render_chart_png(summary: gpd.GeoDataFrame, out: Path, config: Config) -> Path | None:
    fig = _chart_figure(summary, config)
    if fig is None:
        return None
    path = out / CHART_PNG
    try:
        fig.write_image(str(path), width=960, height=fig.layout.height or 420, scale=2)
    except Exception as exc:  # kaleido is optional; never fail the run for a PNG
        log.warning(
            "Static chart image not written. `--chart-png` needs kaleido>=1 and a local "
            "Chrome (`plotly_get_chrome`). Underlying error: %s",
            exc,
        )
        return None
    return path


def _empty_chart_html() -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>No affected places</title></head>
<body style="margin:0;display:grid;place-items:center;height:100vh;
background:{theme.SURFACE_1};color:{theme.TEXT_MUTED};
font-family:{theme.FONT_STACK};font-size:14px;">
No populated places fall inside an impact zone in this run.
</body></html>"""


# ------------------------------------------------------------------- data files


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _write_cities_csv(summary: gpd.GeoDataFrame, out: Path) -> Path:
    path = out / CITIES_CSV
    columns = [
        "name", "adm1name", "adm0name", "iso_a2", "pop_max",
        "max_magnitude", "event_count", "min_distance_km",
        "nearest_event_km", "nearest_event_mag", "nearest_event_title",
        "title", "place", "depth_km", "url", "time_utc",
    ]
    if summary.empty:
        Path(path).write_text(",".join(columns) + "\n", encoding="utf-8")
        return path
    frame = summary.copy()
    for column in ("min_distance_km", "nearest_event_km", "distance_km"):
        if column in frame.columns:
            frame[column] = frame[column].astype(float).round(2)
    frame["lon"] = frame.geometry.x.round(5)
    frame["lat"] = frame.geometry.y.round(5)
    available = [c for c in columns if c in frame.columns] + ["lon", "lat"]
    frame[available].to_csv(path, index=False)
    return path


def _write_zones(zones: gpd.GeoDataFrame, out: Path) -> Path:
    path = out / EVENTS_GEOJSON
    if zones.empty:
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
        )
        return path
    frame = zones.drop(columns=["time_utc"], errors="ignore").copy()
    frame.to_file(path, driver="GeoJSON")
    return path


# ------------------------------------------------------------------ landing page


def _render_index(
    digest: dict,
    summary: gpd.GeoDataFrame,
    out: Path,
    config: Config,
) -> Path:
    log.info("Rendering landing page")
    strongest = digest.get("strongest_event") or {}
    tiles = [
        ("Affected places", f"{digest['cities_affected']:,}", "inside an impact zone"),
        ("People in range", _compact(digest["population_exposed"]), "sum of city populations"),
        ("Events mapped", f"{digest['events_above_threshold']:,}",
         f"M {config.min_magnitude:g}+ of {digest['events_in_feed']:,} in feed"),
        ("Strongest event",
         f"M {strongest['magnitude']:.1f}" if strongest.get("magnitude") else "--",
         html.escape(str(strongest.get("place") or "no qualifying events"))),
    ]
    tile_html = "\n".join(
        f"""<div class="tile">
              <div class="tile-label">{html.escape(label)}</div>
              <div class="tile-value">{value}</div>
              <div class="tile-note">{note}</div>
            </div>"""
        for label, value, note in tiles
    )

    generated = _human_time(digest.get("generated_at_utc", ""))
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config.site_title)}</title>
<meta name="description" content="Populated places within {config.radius_km:g} km of recent M{config.min_magnitude:g}+ earthquakes, rebuilt automatically from the USGS feed.">
<style>
  :root {{
    color-scheme: dark;
    --surface-0: {theme.SURFACE_0};
    --surface-1: {theme.SURFACE_1};
    --surface-2: {theme.SURFACE_2};
    --text-primary: {theme.TEXT_PRIMARY};
    --text-secondary: {theme.TEXT_SECONDARY};
    --text-muted: {theme.TEXT_MUTED};
    --hazard: {theme.HAZARD};
    --city: {theme.CITY};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--surface-0); color: var(--text-primary);
    font-family: {theme.FONT_STACK}; line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1120px; margin: 0 auto; padding: 32px 16px 64px; }}
  header {{ border-bottom: 1px solid var(--surface-2); padding-bottom: 20px; margin-bottom: 24px; }}
  h1 {{ font-size: clamp(22px, 4vw, 30px); margin: 0 0 6px; letter-spacing: -.01em; }}
  .sub {{ color: var(--text-secondary); font-size: 14px; margin: 0; }}
  .stamp {{ color: var(--text-muted); font-size: 12px; font-family: {theme.MONO_STACK}; margin-top: 10px; }}
  .tiles {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); margin-bottom: 28px; }}
  .tile {{ background: var(--surface-1); border: 1px solid var(--surface-2); border-radius: 10px; padding: 14px 16px; }}
  .tile-label {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }}
  .tile-value {{ font-size: 28px; font-weight: 600; margin: 4px 0 2px; font-variant-numeric: tabular-nums; }}
  .tile-note {{ font-size: 12px; color: var(--text-secondary); }}
  section {{ margin-bottom: 28px; }}
  h2 {{ font-size: 15px; text-transform: uppercase; letter-spacing: .07em; color: var(--text-muted); margin: 0 0 10px; font-weight: 600; }}
  .frame {{ width: 100%; border: 1px solid var(--surface-2); border-radius: 10px; background: var(--surface-1); display: block; }}
  .map-frame {{ height: min(70vh, 620px); }}
  .chart-frame {{ height: {chart_height(min(config.max_chart_cities, max(len(summary), 1))) + 8}px; }}
  .links {{ display: flex; flex-wrap: wrap; gap: 10px; font-size: 13px; }}
  .links a {{ color: var(--city); text-decoration: none; border: 1px solid var(--surface-2);
             border-radius: 999px; padding: 6px 12px; background: var(--surface-1); }}
  .links a:hover {{ border-color: var(--city); }}
  footer {{ border-top: 1px solid var(--surface-2); padding-top: 16px; color: var(--text-muted); font-size: 12px; }}
  footer a {{ color: var(--text-secondary); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{html.escape(config.site_title)}</h1>
    <p class="sub">Populated places within {config.radius_km:g}&nbsp;km of an
       M&nbsp;{config.min_magnitude:g}+ earthquake, from the USGS
       <code>{html.escape(config.feed)}</code> feed. Impact zones are true geodesic
       circles on the WGS84 ellipsoid.</p>
    <p class="stamp">Rebuilt {html.escape(generated)}</p>
  </header>

  <div class="tiles">{tile_html}</div>

  <section>
    <h2>Interactive map</h2>
    <iframe class="frame map-frame" src="{MAP_FILENAME}" title="Seismic risk map" loading="lazy"></iframe>
  </section>

  <section>
    <h2>Ranked places</h2>
    <iframe class="frame chart-frame" src="{CHART_FILENAME}" title="Affected places by magnitude" loading="lazy"></iframe>
  </section>

  <section>
    <h2>Data</h2>
    <div class="links">
      <a href="{CITIES_CSV}" download>Affected places (CSV)</a>
      <a href="{EVENTS_GEOJSON}" download>Impact zones (GeoJSON)</a>
      <a href="{SUMMARY_FILENAME}">Run summary (JSON)</a>
      <a href="{MAP_FILENAME}">Open map full screen</a>
    </div>
  </section>

  <footer>
    Earthquake data: <a href="https://earthquake.usgs.gov/earthquakes/feed/" target="_blank" rel="noopener">USGS</a>,
    public domain. Populated places: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener">Natural Earth</a> 1:10m, public domain.
    Impact zones are a fixed-radius screening heuristic, not a ground-motion or damage model.
    <a href="{html.escape(config.repo_url)}" target="_blank" rel="noopener">Source</a>.
  </footer>
</div>
</body>
</html>
"""
    path = out / INDEX_FILENAME
    path.write_text(page, encoding="utf-8")
    return path


def _human_time(iso: str) -> str:
    """'2026-09-19T05:07:17.044395Z' -> '19 Sep 2026, 05:07 UTC'."""
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return stamp.strftime("%d %b %Y, %H:%M UTC")


def _write_legacy_redirect(out: Path) -> Path:
    """Keep the pre-2.0 deep link alive.

    The old README pointed people at
    ``/risk_analysis_output/seismic_risk_map.html``. That path no longer exists,
    so anything already bookmarked or linked would 404 without this shim.
    """
    legacy = out / "risk_analysis_output"
    legacy.mkdir(parents=True, exist_ok=True)
    path = legacy / MAP_FILENAME
    path.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url=../{MAP_FILENAME}">'
        f'<link rel="canonical" href="../{MAP_FILENAME}">'
        "<title>Moved</title></head><body>"
        f'This map now lives at <a href="../{MAP_FILENAME}">../{MAP_FILENAME}</a>.'
        "</body></html>",
        encoding="utf-8",
    )
    return path


def _compact(value: int) -> str:
    value = int(value or 0)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if value >= threshold:
            return f"{value / threshold:.1f}{suffix}"
    return f"{value:,}"
