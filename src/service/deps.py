from __future__ import annotations

from functools import lru_cache

from ..config import AppConfig, get_config
from ..repository import DataRepository
from ..segmentation.base import Segmenter
from ..segmentation.registry import build_segmenter_from_config


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return get_config()


@lru_cache(maxsize=1)
def get_segmenter() -> Segmenter:
    cfg = get_app_config()
    return build_segmenter_from_config(cfg.segmentation)


@lru_cache(maxsize=1)
def get_repository() -> DataRepository:
    cfg = get_app_config()
    segmenter = get_segmenter()
    return DataRepository(cfg, segmenter)
