"""Схемы кросс-валидации.

Набор мал (11 пар), эталон построен автоматически, съёмки несинхронны, а приватный
holdout — будущее событие 2026 г. Поэтому корректная валидация критична, и мы считаем
две схемы:

* leave-one-AOI-out — по району интереса (5 фолдов): проверяет пространственную
  обобщаемость;
* leave-one-event-out — по событию (5 фолдов): проверяет временную обобщаемость,
  что ближе к реальному тесту (holdout — новое событие).
"""

from __future__ import annotations

from collections import defaultdict

from .pairs import Pair


def leave_one_group_out(pairs: list[Pair], key: str) -> list[tuple[list[str], list[str]]]:
    """Разбиение по группам: каждый фолд оставляет одну группу в валидации.

    ``key`` — имя атрибута Pair, по которому группируем ("aoi_id" или "event_id").
    """
    groups: dict[str, list[Pair]] = defaultdict(list)
    for p in pairs:
        groups[getattr(p, key)].append(p)

    folds: list[tuple[list[str], list[str]]] = []
    for held_out, gpairs in groups.items():
        val_ids = [p.pair_id for p in gpairs]
        train_ids = [p.pair_id for p in pairs if p.pair_id not in set(val_ids)]
        folds.append((train_ids, val_ids))
    return folds


def leave_one_aoi_out(pairs: list[Pair]) -> list[tuple[list[str], list[str]]]:
    return leave_one_group_out(pairs, "aoi_id")


def leave_one_event_out(pairs: list[Pair]) -> list[tuple[list[str], list[str]]]:
    return leave_one_group_out(pairs, "event_id")


def describe_split(name: str, train_ids: list[str], val_ids: list[str]) -> str:
    return f"{name}: train={len(train_ids)} val={len(val_ids)} | val={val_ids}"
