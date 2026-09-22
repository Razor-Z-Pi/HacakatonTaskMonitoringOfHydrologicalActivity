"""Ввод-вывод растров.

Читает эталонные маски (10 м, каноническая сетка), вспомогательный растр
AUX_terrain_gsw (30 м, варпится на каноническую сетку) и, если они уже
выгружены, стеки SAR (S1_*.tif) и оптики (SENTINEL2_*.tif).

Снимки Sentinel-1/2 в архив не входят — они выгружаются из GEE и кладутся
в ``rasters/<event>/<aoi>/`` под именами ``S1_<window>_<date>.tif`` и
``SENTINEL2_<window>_<date>.tif``. Пока таких файлов нет, соответствующие
функции возвращают ``None``, и пайплайн автоматически переходит на
вспомогательные (AUX) признаки — это не ошибка, а штатный фолбэк.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

from .config import Config
from .pairs import Pair, rasters_dir_path, reference_mask_path

# Порядок каналов фиксирован поставкой (README + паспорта сцен).
AUX_BANDS = ["slope", "hand", "occurrence", "seasonality", "max_extent", "builtup"]
REF_BANDS = ["flood", "water_pre", "water_peak", "permanent", "receded"]
SAR_BANDS = ["VV", "VH", "VV_VH_ratio"]
S2_BANDS = ["B3", "B4", "B8", "B11", "NDWI", "MNDWI", "NDVI", "AWEISH"]

# Каналы AUX, которые категориальны (0/1) — после билинейного варпа их округляем.
_AUX_CATEGORICAL = {"max_extent", "builtup"}
_AUX_INTEGER = {"seasonality"}


class Raster:
    """Растр с геопривязкой: данные (bands,H,W) + профиль для записи."""

    def __init__(self, array: np.ndarray, profile: dict, band_names: list[str]):
        self.array = np.asarray(array)
        self.profile = profile
        self.band_names = band_names

    @property
    def height(self) -> int:
        return int(self.profile["height"])

    @property
    def width(self) -> int:
        return int(self.profile["width"])

    @property
    def transform(self):
        return self.profile["transform"]

    @property
    def crs(self):
        return self.profile["crs"]

    def band(self, name: str) -> np.ndarray:
        return self.array[self.band_names.index(name)]

    def named(self) -> dict[str, np.ndarray]:
        return {n: self.array[i] for i, n in enumerate(self.band_names)}


def _profile(src) -> dict:
    return {
        "driver": "GTiff",
        "dtype": src.dtypes[0],
        "nodata": src.nodata,
        "width": src.width,
        "height": src.height,
        "count": src.count,
        "crs": src.crs,
        "transform": src.transform,
    }


def read_reference_mask(cfg: Config, pair: Pair) -> Raster:
    """Эталонная маска пары: 5 каналов uint8 (flood, water_pre, water_peak, permanent, receded).

    Это каноническая сетка (10 м, EPSG:32652) — на неё выравнивается всё остальное.
    Используется ТОЛЬКО как разметка (обучение/валидация), никогда как признак.
    """
    path = reference_mask_path(cfg, pair)
    with rasterio.open(path) as src:
        arr = src.read().astype("uint8")
        prof = _profile(src)
    return Raster(arr, prof, REF_BANDS)


def read_reference_stats(cfg: Config, pair: Pair) -> dict:
    """Площади и флаг принятия пары из reference_*.json (для метрики и отчёта)."""
    path = reference_mask_path(cfg, pair).with_suffix(".json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _warp_aux_to_reference(aux_path: Path, ref_profile: dict) -> np.ndarray:
    """Загрузить AUX (30 м, 6 каналов float32) и заварпить на каноническую сетку эталона (10 м)."""
    with rasterio.open(aux_path) as src:
        n = src.count
        out = np.empty((n, ref_profile["height"], ref_profile["width"]), dtype="float32")
        reproject(
            source=rasterio.band(src, range(1, n + 1)),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref_profile["transform"],
            dst_crs=ref_profile["crs"],
            resampling=Resampling.bilinear,
            src_nodata=src.nodata,
            dst_nodata=np.nan,
        )
    # пиксели вне футпринта AUX заполняются NaN (а не 0) — это «нет данных» для модели
    out[~np.isfinite(out)] = np.nan
    return out


def read_aux(cfg: Config, pair: Pair, ref_profile: dict) -> Raster:
    """Вспомогательный растр AUX_terrain_gsw.tif, выровненный на сетку эталона."""
    path = rasters_dir_path(cfg, pair) / "AUX_terrain_gsw.tif"
    arr = _warp_aux_to_reference(path, ref_profile)
    # категориальные/целочисленные каналы после билинейного варпа возвращаем к исходному типу
    for i, name in enumerate(AUX_BANDS):
        if name in _AUX_CATEGORICAL:
            arr[i] = np.where(np.isnan(arr[i]), np.nan, (arr[i] > 0.5).astype("float32"))
        elif name in _AUX_INTEGER:
            arr[i] = np.where(np.isnan(arr[i]), np.nan, np.round(arr[i]).astype("float32"))
    prof = dict(ref_profile)
    prof["count"] = len(AUX_BANDS)
    prof["dtype"] = "float32"
    return Raster(arr, prof, AUX_BANDS)


def _find_scene(raster_dir: Path, prefix: str, window: str, date: str) -> Path | None:
    """Найти GeoTIFF сцены по префиксу S1_/SENTINEL2_ и окну pre/peak.

    Сначала по точному имени ``<prefix><window>_<date>.tif``, затем glob-ом на случай
    другого форматирования даты в имени файла.
    """
    if date:
        exact = raster_dir / f"{prefix}{window}_{date}.tif"
        if exact.exists():
            return exact
    matches = sorted(raster_dir.glob(f"{prefix}{window}_*.tif"))
    return matches[0] if matches else None


def read_sar(cfg: Config, pair: Pair, window: str, ref_profile: dict) -> Raster | None:
    """SAR-стек (VV, VH, VV_VH_ratio, дБ) на дату окна. None, если ещё не выгружен."""
    date = pair.date_pre_sar if window == "pre" else pair.date_peak_sar
    path = _find_scene(rasters_dir_path(cfg, pair), "S1_", window, date)
    if path is None:
        return None
    with rasterio.open(path) as src:
        arr = src.read().astype("float32")
        prof = _profile(src)
    if arr.shape != (len(SAR_BANDS), ref_profile["height"], ref_profile["width"]):
        arr = _warp_to_ref(arr, prof, ref_profile, Resampling.bilinear)
    return Raster(arr, _ref_prof(ref_profile, len(SAR_BANDS)), SAR_BANDS)


def read_optical(cfg: Config, pair: Pair, window: str, ref_profile: dict) -> Raster | None:
    """Оптический стек (B3,B4,B8,B11,NDWI,MNDWI,NDVI,AWEISH) на дату окна. None, если нет."""
    date = pair.date_pre_opt if window == "pre" else pair.date_peak_opt
    path = _find_scene(rasters_dir_path(cfg, pair), "SENTINEL2_", window, date)
    if path is None:
        return None
    with rasterio.open(path) as src:
        arr = src.read().astype("float32")
        prof = _profile(src)
    if arr.shape != (len(S2_BANDS), ref_profile["height"], ref_profile["width"]):
        arr = _warp_to_ref(arr, prof, ref_profile, Resampling.bilinear)
    return Raster(arr, _ref_prof(ref_profile, len(S2_BANDS)), S2_BANDS)


def _warp_to_ref(arr: np.ndarray, src_prof: dict, ref_profile: dict, resampling) -> np.ndarray:
    out = np.empty((arr.shape[0], ref_profile["height"], ref_profile["width"]), dtype="float32")
    reproject(
        source=arr,
        destination=out,
        src_transform=src_prof["transform"],
        src_crs=src_prof["crs"],
        dst_transform=ref_profile["transform"],
        dst_crs=ref_profile["crs"],
        resampling=resampling,
        src_nodata=src_prof.get("nodata"),
        dst_nodata=np.nan,
    )
    out[~np.isfinite(out)] = np.nan
    return out


def _ref_prof(ref_profile: dict, count: int) -> dict:
    prof = dict(ref_profile)
    prof["count"] = count
    prof["dtype"] = "float32"
    return prof


def write_mask(array: np.ndarray, path: Path, ref_profile: dict) -> None:
    """Записать одноканальную uint8 маску (0/1) в GeoTIFF на канонической сетке."""
    prof = dict(ref_profile)
    prof.update(count=1, dtype="uint8", nodata=None)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(array.astype("uint8"), 1)
