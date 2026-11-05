"""Building catalog and inventory-aware material selection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .oni_client import get_data_dir


class CatalogError(ValueError):
    """Planning error with a stable machine-readable reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_catalog(root: str | Path | None = None) -> list[dict[str, Any]]:
    path = get_data_dir(root) / "oni_catalog.json"
    with path.open("r", encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    if not isinstance(catalog, list) or any(not isinstance(item, dict) for item in catalog):
        raise CatalogError("invalid_catalog")
    return catalog


def get_building(catalog: Sequence[Mapping[str, Any]], building_id: str) -> Mapping[str, Any]:
    for building in catalog:
        if building.get("id") == building_id:
            return building
    raise CatalogError("unknown_building")


def building_dimensions(building: Mapping[str, Any]) -> tuple[int, int]:
    width = building.get("width")
    height = building.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise CatalogError("invalid_building_dimensions")
    return width, height


def material_categories(building: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    categories = building.get("materials", [])
    if not isinstance(categories, list) or any(not isinstance(item, Mapping) for item in categories):
        raise CatalogError("invalid_material_categories")
    return categories


def choose_materials(building: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    """Select one allowed element per category from `resources.materials` stock."""
    categories = material_categories(building)
    if not categories:
        return []

    resources = state.get("resources")
    stock = resources.get("materials") if isinstance(resources, Mapping) else None
    if not isinstance(stock, Mapping):
        raise CatalogError("material_inventory_unavailable")

    stock_by_name = {
        name.casefold(): amount
        for name, amount in stock.items()
        if isinstance(name, str) and isinstance(amount, (int, float)) and amount > 0
    }

    selected: list[str] = []
    for category in categories:
        options = category.get("options")
        if not isinstance(options, list) or any(not isinstance(option, str) for option in options):
            raise CatalogError("invalid_material_options")
        choice = next((option for option in options if option.casefold() in stock_by_name), None)
        if choice is None:
            raise CatalogError("insufficient_material")
        selected.append(choice)
    return selected

