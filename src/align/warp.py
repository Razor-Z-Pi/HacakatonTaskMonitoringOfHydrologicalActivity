from __future__ import annotations

import numpy as np
from rasterio.enums import Resampling
from rasterio.profiles import Profile
from rasterio.warp import reproject

from ..geoutils.raster_io import RasterStack


def warp_to_reference(
    src_stack: RasterStack,
    ref_profile: Profile,
    resampling: Resampling = Resampling.bilinear,
) -> np.ndarray:
    ref_h, ref_w = ref_profile["height"], ref_profile["width"]
    n_bands = src_stack.data.shape[0]
    out = np.empty((n_bands, ref_h, ref_w), dtype=np.float32)

    for b in range(n_bands):
        reproject(
            source=src_stack.data[b],
            destination=out[b],
            src_transform=src_stack.transform,
            src_crs=src_stack.crs,
            dst_transform=ref_profile["transform"],
            dst_crs=ref_profile["crs"],
            dst_resolution=(ref_profile["transform"].a, -ref_profile["transform"].e),
            resampling=resampling,
        )
    return out


def categorical_warp_to_reference(src_stack: RasterStack, ref_profile: Profile) -> np.ndarray:
    return warp_to_reference(src_stack, ref_profile, resampling=Resampling.nearest)
