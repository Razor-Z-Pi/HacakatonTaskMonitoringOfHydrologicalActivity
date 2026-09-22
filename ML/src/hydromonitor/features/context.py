"""Гидрологический контекст: расстояние до ближайшего водотока.

Признак из вектора ``vectors/hydrography_osm.geojson``: зона затопления, как
правило, примыкает к руслу, изолированное «озеро» посреди водораздела — ложное
срабатывание. Расстояние (м) считается как евклидова дистанция до ближайшего
растрового пикселя реки на канонической сетке; результат кэшируется на диск.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from rasterio.transform import array_bounds
from scipy.ndimage import distance_transform_edt

from ..config import Config, resolve_data_path
from ..pairs import Pair


def _river_cache_path(cfg: Config, pair: Pair) -> Path:
    return Path(cfg.paths.project_root) / "cache" / f"dist_river_{pair.pair_id}.npy"


def _hydrography_raster(cfg: Config, ref_profile: dict) -> np.ndarray:
    """Бинарная маска гидросети (1 = река) на канонической сетке эталона."""
    path = resolve_data_path(cfg, "vectors", "hydrography_osm.geojson")
    gdf = gpd.read_file(path)
    ref_crs = ref_profile["crs"]
    if gdf.crs is None:
        gdf = gdf.set_crs(ref_crs)
    elif gdf.crs != ref_crs:
        gdf = gdf.to_crs(ref_crs)

    transform = ref_profile["transform"]
    height, width = ref_profile["height"], ref_profile["width"]
    left, bottom, right, top = array_bounds(height, width, transform)
    gdf = gdf.cx[left:right, bottom:top]

    shapes = ((g, 1) for g in gdf.geometry if g is not None and not g.is_empty)
    return rasterize(shapes, out_shape=(height, width), transform=transform,
                     fill=0, dtype="uint8")


def distance_to_river(cfg: Config, pair: Pair, ref_profile: dict) -> np.ndarray:
    """Евклидово расстояние до ближайшего пикселя гидросети (м), на сетке эталона.

    Кэшируется в ``cache/dist_river_<pair_id>.npy``; при изменении сетки/вектора
    кэш нужно удалить вручную.
    """
    cache = _river_cache_path(cfg, pair)
    if cache.exists():
        return np.load(cache)

    river = _hydrography_raster(cfg, ref_profile).astype(bool)
    # scipy.edt считает расстояние до фоновых (False) элементов → инвертируем
    dist_px = distance_transform_edt(~river)
    t = ref_profile["transform"]
    pixel_m = float(np.sqrt(abs(t.a * t.e - t.b * t.d)))
    dist_m = (dist_px * pixel_m).astype("float32")

    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, dist_m)
    return dist_m
