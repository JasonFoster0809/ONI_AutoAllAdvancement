import json
from pathlib import Path

import pytest

from agent.catalog import CatalogError, choose_materials


FIXTURES = Path(__file__).parent / "fixtures"


def load_material_state():
    return json.loads(
        (FIXTURES / "material_inventory.json").read_text(encoding="utf-8")
    )


def load_building(filename):
    return json.loads(
        (FIXTURES / filename).read_text(encoding="utf-8")
    )


def test_choose_materials_selects_materials_when_stock_meets_mass_and_preserves_casing():
    building = load_building("catalog_with_masses.json")

    assert choose_materials(building, load_material_state()) == [
        "SandStone",
        "Dirt",
    ]


def test_choose_materials_rejects_stock_below_required_mass():
    building = load_building("catalog_with_masses.json")
    building["materials"][0]["mass_kg"] = 1200.1

    with pytest.raises(CatalogError) as error:
        choose_materials(building, load_material_state())
    assert error.value.reason == "insufficient_material"


def test_choose_materials_uses_positive_stock_with_legacy_catalog(caplog):
    building = load_building("catalog_without_masses.json")

    assert choose_materials(building, load_material_state()) == ["SandStone"]
    assert "has no mass_kg" in caplog.text


def test_choose_materials_reports_missing_material_inventory():
    building = load_building("catalog_with_masses.json")

    with pytest.raises(CatalogError) as error:
        choose_materials(building, {"resources": {"food_kcal": 10}})
    assert error.value.reason == "material_inventory_unavailable"
