"""Векторизация растровых масок: маска -> полигоны -> GeoJSON (EPSG:4326) / Shapefile.

Площадь каждого полигона считается в исходной проекции (метровой, EPSG:32652),
а геометрия отдаётся клиенту уже в WGS84, как того требует Leaflet.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
from rasterio.features import shapes as rio_shapes
from rasterio.profiles import Profile
from shapely.geometry import shape as shapely_shape

from .raster_io import pixel_area_ha


def mask_to_geodataframe(
    mask: np.ndarray,
    profile: Profile,
    feature_type: str,
    fallback_pixel_area_ha: float,
    min_area_ha: float = 0.0,
) -> gpd.GeoDataFrame:
    """Строит GeoDataFrame полигонов из бинарной маски в её нативном CRS."""
    transform = profile["transform"]
    crs = profile["crs"]
    px_area_ha = pixel_area_ha(profile, fallback_pixel_area_ha)  # используется как safety-фолбэк ниже

    geoms: list[dict[str, Any]] = []
    areas: list[float] = []
    for geom, value in rio_shapes(mask.astype("uint8"), mask=mask, transform=transform):
        if value != 1:
            continue
        poly = shapely_shape(geom)
        if crs and crs.is_projected:
            # Все растры кейса в метровом EPSG:32652 — poly.area уже в м^2.
            area_ha = round(poly.area / 10_000.0, 4)
        else:
            # Подстраховка на случай нестандартного (не метрового) CRS во входных данных.
            n_px_equiv = poly.area / max(abs(transform.a * transform.e), 1e-12)
            area_ha = round(n_px_equiv * px_area_ha, 4)
        if area_ha < min_area_ha:
            continue
        geoms.append(geom)
        areas.append(area_ha)

    gdf = gpd.GeoDataFrame(
        {"type": feature_type, "area_ha": areas},
        geometry=[shapely_shape(g) for g in geoms],
        crs=crs,
    )
    return gdf


def mask_to_geojson(
    mask: np.ndarray,
    profile: Profile,
    feature_type: str,
    fallback_pixel_area_ha: float,
    min_area_ha: float = 0.0,
) -> dict[str, Any]:
    """Маска -> GeoJSON FeatureCollection в EPSG:4326 (для отдачи в Leaflet)."""
    gdf = mask_to_geodataframe(mask, profile, feature_type, fallback_pixel_area_ha, min_area_ha)
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    gdf_wgs84 = gdf.to_crs(epsg=4326)
    return gdf_wgs84.__geo_interface__


def geodataframe_to_zipped_shapefile(gdf: gpd.GeoDataFrame, out_path: Path) -> Path:
    """Сохраняет GeoDataFrame как .shp (+.shx/.dbf/.prj) и упаковывает в один .zip."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shp_path = Path(tmp) / (out_path.stem + ".shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for sidecar in Path(tmp).glob(shp_path.stem + ".*"):
                zf.write(sidecar, arcname=sidecar.name)
    return out_path
