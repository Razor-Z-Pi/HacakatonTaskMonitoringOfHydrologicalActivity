from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.profiles import Profile
from skimage.morphology import remove_small_objects

from ..geoutils.raster_io import mask_area_ha


@dataclass
class ChangeResult:
    flood: np.ndarray
    receded: np.ndarray
    permanent: np.ndarray


def permanent_water_mask(occurrence_pct: np.ndarray, occurrence_min_pct: float) -> np.ndarray:
    """Постоянная вода по архиву JRC GSW"""
    return occurrence_pct >= occurrence_min_pct


def compute_change(
    water_pre: np.ndarray,
    water_peak: np.ndarray,
    occurrence_pct: np.ndarray,
    occurrence_min_pct: float,
    apply_mmu: bool,
    min_mapping_unit_px: int,
) -> ChangeResult:
    permanent = permanent_water_mask(occurrence_pct, occurrence_min_pct)

    flood = water_peak & (~water_pre) & (~permanent)
    receded = water_pre & (~water_peak) & (~permanent)

    if apply_mmu and min_mapping_unit_px > 1:
        flood = remove_small_objects(flood, min_size=min_mapping_unit_px)
        receded = remove_small_objects(receded, min_size=min_mapping_unit_px)

    return ChangeResult(flood=flood, receded=receded, permanent=permanent)


def compute_areas_ha(
    water_pre: np.ndarray,
    water_peak: np.ndarray,
    flood: np.ndarray,
    receded: np.ndarray,
    profile: Profile,
    fallback_pixel_area_ha: float,
) -> dict[str, float]:
    aoi_ha = round(water_pre.size * _px_area(profile, fallback_pixel_area_ha), 2)
    return {
        "water_pre_ha": mask_area_ha(water_pre, profile, fallback_pixel_area_ha),
        "water_peak_ha": mask_area_ha(water_peak, profile, fallback_pixel_area_ha),
        "flood_ha": mask_area_ha(flood, profile, fallback_pixel_area_ha),
        "receded_ha": mask_area_ha(receded, profile, fallback_pixel_area_ha),
        "aoi_ha": aoi_ha,
    }


def compute_landcover_breakdown(
    flood: np.ndarray, builtup: np.ndarray, profile: Profile, fallback_pixel_area_ha: float
) -> dict[str, float]:
    """Простая разбивка зоны затопления по типу покрова."""
    built_up_ha = mask_area_ha(flood & builtup.astype(bool), profile, fallback_pixel_area_ha)
    total_ha = mask_area_ha(flood, profile, fallback_pixel_area_ha)
    other_ha = round(max(total_ha - built_up_ha, 0.0), 2)
    return {"built_up_ha": built_up_ha, "other_ha": other_ha}


def _px_area(profile: Profile, fallback_ha: float) -> float:
    from ..geoutils.raster_io import pixel_area_ha

    return pixel_area_ha(profile, fallback_ha)
