# Локальные библиотеки фронтенда

Требование «Воспроизводимость» кейса — сервис должен запускаться без доступа
в интернет, поэтому все JS/CSS-библиотеки должны лежать здесь локально,
а не подключаться через CDN.

Разложите сюда (структуру подкаталогов можно оставить как ниже — пути уже
прописаны в `static/index.html`):

```
vendor/
├── bootstrap/
│   ├── bootstrap.min.css
│   └── bootstrap.bundle.min.js      # Bootstrap 5, с Popper внутри
├── leaflet/
│   ├── leaflet.css
│   ├── leaflet.js
│   └── images/                       # маркеры Leaflet (marker-icon.png и т.п.)
└── leaflet-sidebyside/
    ├── leaflet-side-by-side.css
    └── leaflet-side-by-side.js       # плагин сравнения дат (ползунок)
```

Скачать один раз (на машине с доступом в интернет) и закоммитить в репозиторий:

- Bootstrap 5: https://getbootstrap.com/docs/5.3/getting-started/download/
- Leaflet: https://leafletjs.com/download.html
- Leaflet.SideBySide: https://github.com/digidem/leaflet-side-by-side

Подложка карты (Esri World Imagery) тайлы подгружает по сети на защите —
это не влияет на работу API и автоматическую проверку сервиса (см. README.md).
