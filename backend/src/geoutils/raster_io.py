from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.profiles import Profile


@dataclass
class RasterStack:
    """Многоканальный растр + геопривязка, без интерпретации каналов."""

    data: np.ndarray  # shape (bands, H, W)
    profile: Profile
    path: Path

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape[-2], self.data.shape[-1]

    @property
    def transform(self):
        return self.profile["transform"]

    @property
    def crs(self):
        return self.profile["crs"]

    def band(self, idx: int) -> np.ndarray:
        return self.data[idx]


def read_raster(path: Path) -> RasterStack:
    if not path.exists():
        raise FileNotFoundError(f"Растр не найден: {path}")
    with rasterio.open(path) as src:
        data = src.read()  # (bands, H, W)
        profile = src.profile
    return RasterStack(data=data, profile=profile, path=path)


def pixel_area_ha(profile: Profile, fallback_ha: float) -> float:
    """Реальная площадь пикселя в гектарах из аффинной трансформации."""
    transform = profile.get("transform")
    if transform is None:
        return fallback_ha
    px_area_m2 = abs(transform.a * transform.e)
    if px_area_m2 <= 0:
        return fallback_ha
    return px_area_m2 / 10_000.0


def mask_area_ha(mask: np.ndarray, profile: Profile, fallback_ha: float) -> float:
    n_pixels = int(np.count_nonzero(mask))
    return round(n_pixels * pixel_area_ha(profile, fallback_ha), 2)


def write_mask_geotiff(path: Path, mask: np.ndarray, profile: Profile) -> Path:
    """Сохраняет булеву/uint8 маску как одноканальный GeoTIFF (0/1, uint8)."""
    out_profile = dict(profile)
    out_profile.update(count=1, dtype="uint8", compress="lzw", nodata=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(mask.astype("uint8"), 1)
    return path


def read_mask_geotiff(path: Path) -> tuple[np.ndarray, Profile]:
    with rasterio.open(path) as src:
        mask = src.read(1).astype(bool)
        profile = src.profile
    return mask, profile
