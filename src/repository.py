"""Оркестрация данных: от реестра пар до готовых масок/площадей/GeoJSON.

Здесь и только здесь backend знает про файловую структуру набора данных
(rasters/<event_id>/<aoi_name>/...), про кэш в predictions/ и про формат
submission.csv. API-роуты работают только с этим классом.
"""
from __future__ import annotations

import csv
import logging
import threading
from pathlib import Path

import numpy as np
import rasterio

from .align.warp import categorical_warp_to_reference, warp_to_reference
from .analysis.change import compute_areas_ha, compute_change, compute_landcover_breakdown
from .config import AppConfig
from .geoutils.raster_io import RasterStack, read_mask_geotiff, read_raster, write_mask_geotiff
from .geoutils.vectorize import mask_to_geojson
from .schemas import AreasResponse, LandcoverBreakdown, PairGroup, PairSummary, ReportResponse
from .segmentation.base import PairFeatureStack, Segmenter

logger = logging.getLogger("hydromonitor.repository")


class PairNotFoundError(KeyError):
    pass


class DataRepository:
    def __init__(self, cfg: AppConfig, segmenter: Segmenter):
        self.cfg = cfg
        self.segmenter = segmenter
        self._pairs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load_pairs_table()

    # ------------------------------------------------------------------
    # Реестр пар
    # ------------------------------------------------------------------
    def _load_pairs_table(self) -> None:
        path = self.cfg.pairs_table
        if not path.exists():
            logger.warning(
                "Реестр пар не найден: %s. API /api/pairs будет отдавать пустой список, "
                "пока файл не появится (см. tables/pairs.csv в наборе данных соревнования).",
                path,
            )
            return
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pair_id = row["pair_id"].strip()
                self._pairs[pair_id] = {
                    "pair_id": pair_id,
                    "event_id": row["event_id"].strip(),
                    "aoi_name": row["aoi_name"].strip(),
                    "date_pre": row["date_pre"].strip(),
                    "date_peak": row["date_peak"].strip(),
                    "group": row.get("group", "event").strip() or "event",
                    "has_optical": (row.get("has_optical", "true").strip().lower() != "false"),
                }
        logger.info("Загружено %d пар из %s", len(self._pairs), path)

    def list_pairs(self) -> list[PairSummary]:
        return [
            PairSummary(
                pair_id=p["pair_id"],
                event_id=p["event_id"],
                aoi_name=p["aoi_name"],
                date_pre=p["date_pre"],
                date_peak=p["date_peak"],
                group=PairGroup(p["group"]),
                has_optical=p["has_optical"],
            )
            for p in self._pairs.values()
        ]

    def get_pair_row(self, pair_id: str) -> dict:
        try:
            return self._pairs[pair_id]
        except KeyError as exc:
            raise PairNotFoundError(pair_id) from exc

    # ------------------------------------------------------------------
    # Пути к сырым растрам пары
    # ------------------------------------------------------------------
    def _pair_dir(self, pair_row: dict) -> Path:
        return self.cfg.rasters_dir / pair_row["event_id"] / pair_row["aoi_name"]

    def _raster_path(self, pair_row: dict, key: str) -> Path:
        return self._pair_dir(pair_row) / self.cfg.raster_files[key]

    # ------------------------------------------------------------------
    # Построение признаков (выравнивание AUX на эталонную сетку S1)
    # ------------------------------------------------------------------
    def _build_feature_stack(self, pair_row: dict) -> PairFeatureStack:
        bi = self.cfg.band_indices
        s1_pre = read_raster(self._raster_path(pair_row, "s1_pre"))
        s1_peak = read_raster(self._raster_path(pair_row, "s1_peak"))
        ref_profile = s1_pre.profile  # каноническая сетка 10 м пары

        aux_path = self._raster_path(pair_row, "aux")
        aux_stack = read_raster(aux_path)
        if aux_stack.shape != s1_pre.shape or aux_stack.crs != ref_profile["crs"]:
            aux_data = categorical_warp_to_reference(aux_stack, ref_profile)
        else:
            aux_data = aux_stack.data

        aux_idx = bi["aux"]
        slope = aux_data[aux_idx["slope"]]
        hand = aux_data[aux_idx["hand"]]
        occurrence = aux_data[aux_idx["occurrence"]]
        seasonality = aux_data[aux_idx["seasonality"]]
        max_extent = aux_data[aux_idx["max_extent"]]
        builtup = aux_data[aux_idx["builtup"]] > 0.5

        s1_idx = bi["s1"]
        vv_pre, vh_pre = s1_pre.band(s1_idx["vv"]), s1_pre.band(s1_idx["vh"])
        vv_peak, vh_peak = s1_peak.band(s1_idx["vv"]), s1_peak.band(s1_idx["vh"])

        s2_pre_path = self._raster_path(pair_row, "s2_pre")
        s2_peak_path = self._raster_path(pair_row, "s2_peak")
        has_optical = s2_pre_path.exists() and s2_peak_path.exists() and pair_row["has_optical"]

        ndwi_pre = mndwi_pre = ndvi_pre = aweish_pre = None
        ndwi_peak = mndwi_peak = ndvi_peak = aweish_peak = None
        if has_optical:
            s2i = bi["s2"]
            s2_pre = read_raster(s2_pre_path)
            s2_peak = read_raster(s2_peak_path)
            if s2_pre.shape != s1_pre.shape:
                s2_pre_data = warp_to_reference(s2_pre, ref_profile)
                s2_peak_data = warp_to_reference(s2_peak, ref_profile)
            else:
                s2_pre_data, s2_peak_data = s2_pre.data, s2_peak.data
            ndwi_pre, mndwi_pre = s2_pre_data[s2i["ndwi"]], s2_pre_data[s2i["mndwi"]]
            ndvi_pre, aweish_pre = s2_pre_data[s2i["ndvi"]], s2_pre_data[s2i["aweish"]]
            ndwi_peak, mndwi_peak = s2_peak_data[s2i["ndwi"]], s2_peak_data[s2i["mndwi"]]
            ndvi_peak, aweish_peak = s2_peak_data[s2i["ndvi"]], s2_peak_data[s2i["aweish"]]

        return PairFeatureStack(
            vv_pre=vv_pre, vh_pre=vh_pre, vv_peak=vv_peak, vh_peak=vh_peak,
            ndwi_pre=ndwi_pre, mndwi_pre=mndwi_pre, ndvi_pre=ndvi_pre, aweish_pre=aweish_pre,
            ndwi_peak=ndwi_peak, mndwi_peak=mndwi_peak, ndvi_peak=ndvi_peak, aweish_peak=aweish_peak,
            slope=slope, hand=hand, occurrence=occurrence, seasonality=seasonality,
            max_extent=max_extent, builtup=builtup, profile=ref_profile,
        )

    # ------------------------------------------------------------------
    # Кэш предсказанных масок
    # ------------------------------------------------------------------
    def _cache_paths(self, pair_id: str) -> dict[str, Path]:
        d = self.cfg.predictions_dir
        return {
            "pre": d / f"{pair_id}_water_pre.tif",
            "peak": d / f"{pair_id}_water_peak.tif",
            "flood": d / f"{pair_id}_flood.tif",
            "receded": d / f"{pair_id}_receded.tif",
        }

    def _masks_cached(self, pair_id: str) -> bool:
        paths = self._cache_paths(pair_id)
        return all(p.exists() for p in paths.values()) and not self.cfg.cache.get(
            "force_recompute", False
        )

    def get_or_compute_masks(self, pair_id: str) -> dict[str, tuple[np.ndarray, dict]]:
        """Возвращает {'pre':(mask,profile), 'peak':..., 'flood':..., 'receded':...}."""
        pair_row = self.get_pair_row(pair_id)
        cache = self._cache_paths(pair_id)

        with self._lock:
            if self._masks_cached(pair_id):
                return {k: read_mask_geotiff(p) for k, p in cache.items()}

            features = self._build_feature_stack(pair_row)
            seg_result = self.segmenter.segment_pair(features)

            filters_cfg = self.cfg.segmentation["filters"]
            change = compute_change(
                water_pre=seg_result.water_pre,
                water_peak=seg_result.water_peak,
                occurrence_pct=features.occurrence,
                occurrence_min_pct=filters_cfg["permanent_occurrence_min"],
                apply_mmu=self.cfg.analysis.get("apply_mmu_to_change", True),
                min_mapping_unit_px=filters_cfg["min_mapping_unit_px"],
            )

            profile = features.profile
            write_mask_geotiff(cache["pre"], seg_result.water_pre, profile)
            write_mask_geotiff(cache["peak"], seg_result.water_peak, profile)
            write_mask_geotiff(cache["flood"], change.flood, profile)
            write_mask_geotiff(cache["receded"], change.receded, profile)

            # Кэшируем builtup (нужен для отчёта), не пересчитывая признаки заново.
            np.save(self.cfg.predictions_dir / f"{pair_id}_builtup.npy", features.builtup)

            return {k: read_mask_geotiff(p) for k, p in cache.items()}

    def _builtup_for_pair(self, pair_id: str) -> np.ndarray | None:
        p = self.cfg.predictions_dir / f"{pair_id}_builtup.npy"
        return np.load(p) if p.exists() else None

    # ------------------------------------------------------------------
    # API-уровневые агрегаты
    # ------------------------------------------------------------------
    def get_areas(self, pair_id: str) -> AreasResponse:
        masks = self.get_or_compute_masks(pair_id)
        (water_pre, profile), (water_peak, _), (flood, _), (receded, _) = (
            masks["pre"], masks["peak"], masks["flood"], masks["receded"],
        )
        areas = compute_areas_ha(
            water_pre, water_peak, flood, receded, profile, self.cfg.pixel_area_ha_fallback
        )
        return AreasResponse(
            pair_id=pair_id,
            flood_ha=areas["flood_ha"],
            water_pre_ha=areas["water_pre_ha"],
            water_peak_ha=areas["water_peak_ha"],
            aoi_ha=areas["aoi_ha"],
        )

    def get_contours_geojson(self, pair_id: str, layer: str) -> dict:
        masks = self.get_or_compute_masks(pair_id)
        mask, profile = masks[layer]
        return mask_to_geojson(mask, profile, feature_type=layer, fallback_pixel_area_ha=self.cfg.pixel_area_ha_fallback)

    def get_mask_path(self, pair_id: str, layer: str) -> Path:
        self.get_or_compute_masks(pair_id)  # гарантирует, что кэш посчитан
        return self._cache_paths(pair_id)[layer]

    def get_report(self, pair_id: str) -> ReportResponse:
        pair_row = self.get_pair_row(pair_id)
        masks = self.get_or_compute_masks(pair_id)
        (water_pre, profile), (water_peak, _), (flood, _), (receded, _) = (
            masks["pre"], masks["peak"], masks["flood"], masks["receded"],
        )
        areas = compute_areas_ha(
            water_pre, water_peak, flood, receded, profile, self.cfg.pixel_area_ha_fallback
        )

        builtup = self._builtup_for_pair(pair_id)
        warnings: list[str] = []
        if builtup is None:
            builtup = np.zeros_like(flood, dtype=bool)
            warnings.append("Слой застройки недоступен для разбивки по земному покрову.")
        breakdown = compute_landcover_breakdown(
            flood, builtup, profile, self.cfg.pixel_area_ha_fallback
        )

        if not pair_row["has_optical"]:
            warnings.append(
                "Для этой пары оптика Sentinel-2 отсутствует — маски построены только по SAR."
            )

        aoi_ha = areas["aoi_ha"]
        flood_ha = areas["flood_ha"]
        flood_share_pct = round((flood_ha / aoi_ha * 100.0), 4) if aoi_ha > 0 else 0.0

        return ReportResponse(
            pair_id=pair_id,
            event_id=pair_row["event_id"],
            aoi_name=pair_row["aoi_name"],
            date_pre=pair_row["date_pre"],
            date_peak=pair_row["date_peak"],
            aoi_ha=aoi_ha,
            aoi_km2=round(aoi_ha / 100.0, 4),
            water_pre_ha=areas["water_pre_ha"],
            water_peak_ha=areas["water_peak_ha"],
            flood_ha=flood_ha,
            flood_km2=round(flood_ha / 100.0, 4),
            receded_ha=areas["receded_ha"],
            receded_km2=round(areas["receded_ha"] / 100.0, 4),
            flood_share_pct=flood_share_pct,
            landcover_breakdown=LandcoverBreakdown(**breakdown),
            has_optical=pair_row["has_optical"],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # submission.csv (для проверяющей системы соревнования)
    # ------------------------------------------------------------------
    def write_submission_row(self, pair_id: str) -> None:
        areas = self.get_areas(pair_id)
        path = self.cfg.submission_csv
        rows: dict[str, dict] = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    rows[row["pair_id"]] = row
        rows[pair_id] = {
            "pair_id": pair_id,
            "flood_ha": f"{areas.flood_ha:.2f}",
            "water_pre_ha": f"{areas.water_pre_ha:.2f}",
            "water_peak_ha": f"{areas.water_peak_ha:.2f}",
        }
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["pair_id", "flood_ha", "water_pre_ha", "water_peak_ha"])
            writer.writeheader()
            for r in rows.values():
                writer.writerow(r)

    def build_full_submission(self) -> Path:
        """Прогоняет все пары реестра и формирует полный submission.csv."""
        for pair_id in self._pairs:
            self.write_submission_row(pair_id)
        return self.cfg.submission_csv
