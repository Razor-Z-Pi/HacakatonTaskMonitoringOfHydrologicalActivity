"""Загрузка конфигурации.

Все пороги, параметры модели и пути задаются в YAML-файлах в ``configs/``,
а не магическими числами в коде (требование критерия «Структура проекта»).
Абсолютные пути, специфичные для машины разработчика, недопустимы: пути
разрешаются относительно корня проекта и каталога данных из ``configs/paths.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"


class Config:
    """Плоский словарь с доступом через атрибуты и точку (a.b.c)."""

    def __init__(self, data: dict):
        object.__setattr__(self, "_data", data)

    @classmethod
    def from_yaml(cls, *paths: Path) -> "Config":
        data: dict = {}
        for p in paths:
            with open(p, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Ожидался словарь в {p}")
            _deep_merge(data, loaded)
        return cls(data)

    def get(self, key: str, default=None):
        cur = self._data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def __getattr__(self, key: str):
        data = object.__getattribute__(self, "_data")
        if key in data:
            val = data[key]
            if isinstance(val, dict):
                return Config(val)
            return val
        raise AttributeError(key)

    def as_dict(self) -> dict:
        return self._data

    def __repr__(self) -> str:  # pragma: no cover - отладочное
        return f"Config({self._data})"


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_config() -> Config:
    """Загрузить все YAML из ``configs/`` и подставить пути из ``paths.yaml``.

    Каталог данных можно переопределить переменной окружения ``HYDRO_DATA_DIR`` —
    это единственная легальная точка подключения машиноспецифичного пути.
    """
    cfg = Config.from_yaml(
        CONFIG_DIR / "paths.yaml",
        CONFIG_DIR / "thresholds.yaml",
        CONFIG_DIR / "model.yaml",
    )

    data_dir = os.environ.get("HYDRO_DATA_DIR") or cfg.get("paths.data_dir", "../hydrowatch_amur")
    data_dir = Path(data_dir)
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()

    cfg._data["paths"]["data_dir"] = str(data_dir)
    for key in ("rasters_dir", "reference_masks_dir", "vectors_dir", "tables_dir"):
        if key in cfg._data["paths"]:
            p = Path(cfg._data["paths"][key])
            cfg._data["paths"][key] = str(p if p.is_absolute() else data_dir / p)

    cfg._data["paths"]["project_root"] = str(PROJECT_ROOT)
    cfg._data["paths"]["config_dir"] = str(CONFIG_DIR)

    out = cfg._data["paths"].get("output_dir", "output")
    p_out = Path(out)
    if not p_out.is_absolute():
        p_out = PROJECT_ROOT / p_out
    cfg._data["paths"]["output_dir"] = str(p_out)
    return cfg


def resolve_data_path(cfg: Config, *parts: str) -> Path:
    """Путь внутри каталога данных: ``resolve_data_path(cfg, "pairs.csv")``."""
    return Path(cfg.paths.data_dir, *parts)
