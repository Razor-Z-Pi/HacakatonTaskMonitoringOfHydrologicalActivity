from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PairGroup(str, Enum):
    event = "event"       # пара "в зачёте"
    control = "control"    # контрольная пара межени


class PairSummary(BaseModel):
    pair_id: str
    event_id: str
    aoi_name: str
    date_pre: str
    date_peak: str
    group: PairGroup = PairGroup.event
    has_optical: bool = True


class AreasResponse(BaseModel):
    pair_id: str
    flood_ha: float
    water_pre_ha: float
    water_peak_ha: float
    aoi_ha: float


class LandcoverBreakdown(BaseModel):
    built_up_ha: float
    other_ha: float


class ReportResponse(BaseModel):
    pair_id: str
    event_id: str
    aoi_name: str
    date_pre: str
    date_peak: str
    aoi_ha: float
    aoi_km2: float
    water_pre_ha: float
    water_peak_ha: float
    flood_ha: float
    flood_km2: float
    receded_ha: float
    receded_km2: float
    flood_share_pct: float = Field(..., description="Доля затопленной площади от площади AOI, %")
    landcover_breakdown: LandcoverBreakdown
    has_optical: bool
    warnings: list[str] = Field(default_factory=list)


class ContourLayer(str, Enum):
    pre = "pre"
    peak = "peak"
    flood = "flood"


class DownloadFormat(str, Enum):
    geojson = "geojson"
    shp = "shp"


class MaskLayer(str, Enum):
    flood = "flood"
    pre = "pre"
    peak = "peak"
    receded = "receded"
