"""Точка входа сервиса.

Запуск: uvicorn src.service.main:app --host 0.0.0.0 --port 8000
(из корня репозитория, чтобы относительные пути конфига разрешались верно).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .deps import get_app_config, get_repository, get_segmenter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hydromonitor")

cfg = get_app_config()

app = FastAPI(title=cfg.api["title"], version=cfg.api["version"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.api.get("cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
def on_startup() -> None:
    segmenter = get_segmenter()
    repo = get_repository()
    logger.info(
        "HydroWatch backend запущен. Сегментатор: %s. Пар в реестре: %d.",
        segmenter.name,
        len(repo.list_pairs()),
    )


# Статика (Bootstrap + Leaflet + app.js) — отдаём последним, чтобы не перекрывать /api/*.
if cfg.static_dir.exists():
    app.mount("/", StaticFiles(directory=str(cfg.static_dir), html=True), name="static")
