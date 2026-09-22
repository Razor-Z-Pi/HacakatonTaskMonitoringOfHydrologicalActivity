"""Метрика оценки (Score) — точная реализация формул из постановки кейса.

Score = 0.45·Q_flood + 0.25·Q_water_peak + 0.15·Q_water_pre + 0.15·Spec_base

Компоненты Q — средняя по ПАРАМ СОБЫТИЙ (не baseline) сходимость площади:
    q = max(0, 1 − |X_сабмита − X_эталона| / max(X_эталона, порог))
    порог: затопление 50 га, водное зеркало 200 га.

Spec_base — контроль ложных срабатываний на контрольных парах межени:
    доля = max(0, flood_сабмита − flood_эталона) / площадь_района
    Spec_base = среднее по контрольным парам от (1 − min(1, доля / 0.005))
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pairs import Pair, baseline_pairs, event_pairs

FLOOD_THRESHOLD_HA = 50.0
WATER_THRESHOLD_HA = 200.0
SPEC_BASE_TOLERANCE = 0.005  # 0.5 % площади района — допуск ложных срабатываний

WEIGHTS = {"flood": 0.45, "water_peak": 0.25, "water_pre": 0.15, "spec_base": 0.15}


@dataclass
class PairAreas:
    """Площади одной пары в гектарах (эталон или сабмит)."""

    flood_ha: float
    water_pre_ha: float
    water_peak_ha: float
    aoi_ha: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "PairAreas":
        return cls(
            flood_ha=float(d["flood_ha"]),
            water_pre_ha=float(d["water_pre_ha"]),
            water_peak_ha=float(d["water_peak_ha"]),
            aoi_ha=float(d.get("aoi_ha", 0.0)),
        )


def _q(sub: float, ref: float, threshold: float) -> float:
    if ref <= 0:
        # эталона нет — сходимость по порогу (затопления не должно быть)
        return max(0.0, 1.0 - sub / threshold) if sub > 0 else 1.0
    return max(0.0, 1.0 - abs(sub - ref) / max(ref, threshold))


@dataclass
class ScoreBreakdown:
    q_flood: float = 0.0
    q_water_peak: float = 0.0
    q_water_pre: float = 0.0
    spec_base: float = 0.0
    score: float = 0.0
    per_pair: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "Q_flood": round(self.q_flood, 6),
            "Q_water_peak": round(self.q_water_peak, 6),
            "Q_water_pre": round(self.q_water_pre, 6),
            "Spec_base": round(self.spec_base, 6),
            "Score": round(self.score, 6),
        }


def compute_score(submission: dict[str, PairAreas], reference: dict[str, PairAreas],
                  pairs: list[Pair]) -> ScoreBreakdown:
    """Вычислить Score и все компоненты.

    ``submission`` / ``reference`` — словари pair_id → PairAreas. В сабмите
    отсутствующая пара считается нулевой площадью (правило поставки).
    """
    ev = event_pairs(pairs)
    bl = baseline_pairs(pairs)

    q_flood = q_peak = q_pre = 0.0
    per_pair: dict[str, dict] = {}
    for p in ev:
        sub = submission.get(p.pair_id) or PairAreas(0.0, 0.0, 0.0, p.aoi_ha)
        ref = reference[p.pair_id]
        qf = _q(sub.flood_ha, ref.flood_ha, FLOOD_THRESHOLD_HA)
        qp = _q(sub.water_peak_ha, ref.water_peak_ha, WATER_THRESHOLD_HA)
        qr = _q(sub.water_pre_ha, ref.water_pre_ha, WATER_THRESHOLD_HA)
        q_flood += qf
        q_peak += qp
        q_pre += qr
        per_pair[p.pair_id] = {
            "kind": "event",
            "q_flood": qf, "q_water_peak": qp, "q_water_pre": qr,
            "flood_sub": sub.flood_ha, "flood_ref": ref.flood_ha,
            "water_peak_sub": sub.water_peak_ha, "water_peak_ref": ref.water_peak_ha,
            "water_pre_sub": sub.water_pre_ha, "water_pre_ref": ref.water_pre_ha,
        }
    n_ev = max(1, len(ev))
    q_flood /= n_ev
    q_peak /= n_ev
    q_pre /= n_ev

    spec_base = 0.0
    for p in bl:
        sub = submission.get(p.pair_id) or PairAreas(0.0, 0.0, 0.0, p.aoi_ha)
        ref = reference[p.pair_id]
        overshoot_frac = max(0.0, sub.flood_ha - ref.flood_ha) / max(ref.aoi_ha, 1.0)
        term = 1.0 - min(1.0, overshoot_frac / SPEC_BASE_TOLERANCE)
        spec_base += term
        per_pair[p.pair_id] = {
            "kind": "baseline",
            "spec_term": term,
            "flood_sub": sub.flood_ha, "flood_ref": ref.flood_ha,
            "overshoot_frac": overshoot_frac,
        }
    spec_base /= max(1, len(bl))

    score = (
        WEIGHTS["flood"] * q_flood
        + WEIGHTS["water_peak"] * q_peak
        + WEIGHTS["water_pre"] * q_pre
        + WEIGHTS["spec_base"] * spec_base
    )
    return ScoreBreakdown(q_flood, q_peak, q_pre, spec_base, score, per_pair)


def reference_areas_from_masks(masks: dict[str, "Raster"], pairs: list[Pair]) -> dict[str, PairAreas]:
    """Эталонные площади, посчитанные напрямую по каналам эталонных масок.

    Нужен для случаев, когда reference_*.json недоступен; площадь пикселя берётся
    из геотрансформации (разрешение по X и Y)."""
    from .io import Raster  # локальный импорт во избежание цикла

    out: dict[str, PairAreas] = {}
    for p in pairs:
        r: Raster = masks[p.pair_id]
        t = r.transform
        pixel_ha = abs(t.a * t.e - t.b * t.d) / 10000.0  # м² → га
        named = r.named()
        out[p.pair_id] = PairAreas(
            flood_ha=float(named["flood"].sum()) * pixel_ha,
            water_pre_ha=float(named["water_pre"].sum()) * pixel_ha,
            water_peak_ha=float(named["water_peak"].sum()) * pixel_ha,
            aoi_ha=p.aoi_ha,
        )
    return out


def reference_areas_from_json(stats: dict[str, dict], pairs: list[Pair]) -> dict[str, PairAreas]:
    """Эталонные площади из reference_*.json (поля stats.*_ha и aoi_ha)."""
    out: dict[str, PairAreas] = {}
    for p in pairs:
        s = stats[p.pair_id]["stats"]
        out[p.pair_id] = PairAreas(
            flood_ha=float(s["flood_ha"]),
            water_pre_ha=float(s["water_pre_ha"]),
            water_peak_ha=float(s["water_peak_ha"]),
            aoi_ha=float(s.get("aoi_ha", p.aoi_ha)),
        )
    return out
