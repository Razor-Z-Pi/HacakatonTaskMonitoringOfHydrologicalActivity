"""Превращение вероятностных карт в готовые продукты: маски, площади, submission.

Правило вывода (общее для baseline и LightGBM):

* ``water_pre`` / ``water_peak`` — вода в окне (порог по вероятности + мин. единица);
* ``permanent`` — постоянное зеркало: occurrence ≥ порога;
* ``flood`` — НОВОЕ затопление: water_peak и не water_pre и не permanent,
  плюс физический признак падения VV ≥ 3 дБ на пике (если SAR доступен);
* ``receded`` — вода ушла: water_pre и не water_peak.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from ..config import Config
from ..features import assemble_features
from ..features.sar import lee_filter
from ..io import Raster, write_mask
from ..metric import PairAreas
from ..pairs import Pair
from ..segmentation.dataset import load_pair_rasters
from ..segmentation.model import predict_probability_map
from ..segmentation.postprocess import remove_small_components


def pixel_area_ha(profile: dict) -> float:
    t = profile["transform"]
    return abs(t.a * t.e - t.b * t.d) / 10000.0  # м² → га


def masks_from_probabilities(cfg: Config, aux: Raster, prob_pre: np.ndarray,
                             prob_peak: np.ndarray, threshold: float,
                             sar_pre: Raster | None = None,
                             sar_peak: Raster | None = None) -> dict[str, np.ndarray]:
    """Бинарные маски пары (water_pre/water_peak/permanent/flood/receded)."""
    t = cfg.thresholds
    min_px = int(t.hydro.min_unit_px)

    water_pre = remove_small_components(prob_pre >= threshold, min_px=min_px)
    water_peak = remove_small_components(prob_peak >= threshold, min_px=min_px)
    permanent = aux.band("occurrence") >= float(t.hydro.permanent_occ)

    drop_ok = np.ones(water_peak.shape, dtype=bool)
    if sar_pre is not None and sar_peak is not None:
        w = int(t.get("speckle.window", 5))
        drop = lee_filter(sar_pre.band("VV"), w) - lee_filter(sar_peak.band("VV"), w)
        drop_ok = drop >= float(t.sar.drop_db)

    flood = water_peak & ~water_pre & ~permanent & drop_ok
    flood = remove_small_components(flood, min_px=min_px)
    receded = water_pre & ~water_peak

    return {
        "water_pre": water_pre,
        "water_peak": water_peak,
        "permanent": permanent,
        "flood": flood,
        "receded": receded,
    }


def predict_pair(cfg: Config, pair: Pair, model, meta: dict,
                 threshold: float | None = None) -> tuple[dict[str, np.ndarray], float, dict]:
    """Прогноз масок пары обученной моделью. Возвращает (маски, площадь пикселя в га, профиль)."""
    ref, aux, dist, sar_pre, sar_peak, opt_pre, opt_peak = load_pair_rasters(cfg, pair)
    thr = meta["threshold"] if threshold is None else threshold

    probs: dict[str, np.ndarray] = {}
    for window, sar, opt in (("pre", sar_pre, opt_pre), ("peak", sar_peak, opt_peak)):
        feats = assemble_features(aux, dist, sar, opt, is_peak=(window == "peak"))
        probs[window] = predict_probability_map(model, feats)

    masks = masks_from_probabilities(cfg, aux, probs["pre"], probs["peak"], thr,
                                     sar_pre, sar_peak)
    return masks, pixel_area_ha(ref.profile), ref.profile


def predict_all(cfg: Config, pairs: list[Pair], model, meta: dict,
                out_dir: Path, write: bool = True) -> dict[str, PairAreas]:
    """Прогноз всех пар + запись submission.csv и predictions/<pair_id>_flood.tif."""
    areas: dict[str, PairAreas] = {}
    for p in pairs:
        masks, pixel_ha, ref_profile = predict_pair(cfg, p, model, meta)
        areas[p.pair_id] = areas_from_masks(masks, pixel_ha)
        if write:
            write_predictions(out_dir / "predictions", p, masks, ref_profile)
    if write:
        write_submission(out_dir / "submission.csv", areas, pairs)
    return areas


def areas_from_masks(masks: dict[str, np.ndarray], pixel_ha: float) -> PairAreas:
    return PairAreas(
        flood_ha=float(masks["flood"].sum()) * pixel_ha,
        water_pre_ha=float(masks["water_pre"].sum()) * pixel_ha,
        water_peak_ha=float(masks["water_peak"].sum()) * pixel_ha,
    )


def write_submission(path: Path, areas: dict[str, PairAreas], pairs: list[Pair]) -> None:
    """Записать submission.csv (pair_id, flood_ha, water_pre_ha, water_peak_ha)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_id", "flood_ha", "water_pre_ha", "water_peak_ha"])
        for p in pairs:
            a = areas[p.pair_id]
            # «с точностью до сотых» (2 знака) по постановке; площадь пикселя 0.01 га = 1 знак
            w.writerow([p.pair_id, f"{a.flood_ha:.2f}", f"{a.water_pre_ha:.2f}",
                        f"{a.water_peak_ha:.2f}"])


def write_predictions(out_dir: Path, pair: Pair, masks: dict[str, np.ndarray],
                      ref_profile: dict) -> None:
    """Записать predictions/<pair_id>_flood.tif (uint8 0/1) на канонической сетке."""
    out_dir.mkdir(parents=True, exist_ok=True)
    write_mask(masks["flood"], out_dir / f"{pair.pair_id}_flood.tif", ref_profile)
