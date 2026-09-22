"""Реестр пар «район интереса × событие».

Загружает ``pairs.csv`` и предоставляет единый источник правды о парах:
какие из них событийные (8 шт.), какие контрольные/межень (3 шт.), какие AOI,
какие пары имеют оптику, даты съёмок и пути к растрам и эталонным маскам.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import Config, resolve_data_path

# Ключевые колонки pairs.csv (порядок строк файла не гарантирован, читаем по именам)
COLS = [
    "pair_id", "aoi_id", "aoi_name", "event_id", "event_name", "event_kind",
    "year", "sensor_sar", "sensor_optical",
    "date_pre_sar", "date_peak_sar", "date_pre_opt", "date_peak_opt",
    "orbit_pass", "relative_orbit", "aoi_km2", "rasters_dir", "reference_mask",
]


@dataclass(frozen=True)
class Pair:
    pair_id: str
    aoi_id: str
    aoi_name: str
    event_id: str
    event_name: str
    event_kind: str  # "baseline" | "rain_flood"
    year: int
    has_optical: bool
    date_pre_sar: str
    date_peak_sar: str
    date_pre_opt: str
    date_peak_opt: str
    orbit_pass: str
    relative_orbit: float
    aoi_km2: float
    aoi_ha: float
    rasters_dir: str
    reference_mask: str

    @property
    def is_baseline(self) -> bool:
        return self.event_kind == "baseline"

    @property
    def is_event(self) -> bool:
        return not self.is_baseline


def load_pairs(cfg: Config) -> list[Pair]:
    path = resolve_data_path(cfg, "pairs.csv")
    df = pd.read_csv(path, dtype={"pair_id": str})
    pairs: list[Pair] = []
    for _, r in df.iterrows():
        opt_val = r.get("sensor_optical")
        has_opt = opt_val is not None and bool(pd.notna(opt_val)) and str(opt_val).strip() != ""
        aoi_km2 = float(r["aoi_km2"])
        pairs.append(
            Pair(
                pair_id=str(r["pair_id"]),
                aoi_id=str(r["aoi_id"]),
                aoi_name=str(r.get("aoi_name", "")),
                event_id=str(r["event_id"]),
                event_name=str(r.get("event_name", "")),
                event_kind=str(r.get("event_kind", "")),
                year=int(r["year"]),
                has_optical=has_opt,
                date_pre_sar=_fmt(r.get("date_pre_sar")),
                date_peak_sar=_fmt(r.get("date_peak_sar")),
                date_pre_opt=_fmt(r.get("date_pre_opt")) if has_opt else "",
                date_peak_opt=_fmt(r.get("date_peak_opt")) if has_opt else "",
                orbit_pass=str(r.get("orbit_pass", "")),
                relative_orbit=float(r["relative_orbit"]) if pd.notna(r.get("relative_orbit")) else float("nan"),
                aoi_km2=aoi_km2,
                aoi_ha=aoi_km2 * 100.0,
                rasters_dir=str(r["rasters_dir"]),
                reference_mask=str(r["reference_mask"]),
            )
        )
    return pairs


def event_pairs(pairs: list[Pair]) -> list[Pair]:
    return [p for p in pairs if p.is_event]


def baseline_pairs(pairs: list[Pair]) -> list[Pair]:
    return [p for p in pairs if p.is_baseline]


def aoi_ids(pairs: list[Pair]) -> list[str]:
    seen: list[str] = []
    for p in pairs:
        if p.aoi_id not in seen:
            seen.append(p.aoi_id)
    return seen


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def rasters_dir_path(cfg: Config, pair: Pair) -> Path:
    """Абсолютный путь к каталогу растров пары (где лежат AUX, паспорта и будущие S1/S2)."""
    return resolve_data_path(cfg, pair.rasters_dir)


def reference_mask_path(cfg: Config, pair: Pair) -> Path:
    return resolve_data_path(cfg, pair.reference_mask)
