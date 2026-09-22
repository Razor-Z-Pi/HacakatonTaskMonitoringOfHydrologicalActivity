from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = os.environ.get("HYDROMONITOR_CONFIG", "configs/config.yaml")


@dataclass
class AppConfig:
    raw: dict[str, Any] = field(default_factory=dict)
    root: Path = Path(".")

    # --- helpers ---------------------------------------------------------
    def _abs(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.root / p)

    # --- paths -------------------------------------------------------------
    @property
    def data_root(self) -> Path:
        return self._abs(self.raw["paths"]["data_root"])

    @property
    def rasters_dir(self) -> Path:
        return self._abs(self.raw["paths"]["rasters_dir"])

    @property
    def vectors_dir(self) -> Path:
        return self._abs(self.raw["paths"]["vectors_dir"])

    @property
    def tables_dir(self) -> Path:
        return self._abs(self.raw["paths"]["tables_dir"])

    @property
    def reference_masks_dir(self) -> Path:
        return self._abs(self.raw["paths"]["reference_masks_dir"])

    @property
    def predictions_dir(self) -> Path:
        d = self._abs(self.raw["paths"]["predictions_dir"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def submission_csv(self) -> Path:
        return self._abs(self.raw["paths"]["submission_csv"])

    @property
    def sample_submission_csv(self) -> Path:
        return self._abs(self.raw["paths"]["sample_submission_csv"])

    @property
    def static_dir(self) -> Path:
        return self._abs(self.raw["paths"]["static_dir"])

    @property
    def pairs_table(self) -> Path:
        return self._abs(self.raw["paths"]["pairs_table"])

    # --- grid / thresholds ---------------------------------------------
    @property
    def crs(self) -> str:
        return self.raw["grid"]["crs"]

    @property
    def pixel_area_ha_fallback(self) -> float:
        return float(self.raw["grid"]["pixel_area_ha_fallback"])

    @property
    def raster_files(self) -> dict[str, str]:
        return self.raw["raster_files"]

    @property
    def band_indices(self) -> dict[str, dict[str, int]]:
        return self.raw["band_indices"]

    @property
    def segmentation(self) -> dict[str, Any]:
        return self.raw["segmentation"]

    @property
    def analysis(self) -> dict[str, Any]:
        return self.raw["analysis"]

    @property
    def cache(self) -> dict[str, Any]:
        return self.raw["cache"]

    @property
    def api(self) -> dict[str, Any]:
        return self.raw["api"]


@lru_cache(maxsize=1)
def get_config(config_path: str | None = None) -> AppConfig:
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig(raw=raw, root=path.parent.parent if path.parent.name == "configs" else Path("."))