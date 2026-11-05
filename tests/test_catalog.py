import json
from pathlib import Path

import pytest

from agent.catalog import CatalogError, choose_materials


FIXTURES = Path(__file__).parent / "fixtures"


def load_material_state():
    return json.loads(
        (FIXTURES / "material_inventory.json").read_text(encoding="utf-8")
    )


def test_choose_materials_selects_positive_stock_and_preserves_state_casing():
    building = {
        "materials": [
            {"category": "Metal", "options": ["Cuprite", "sandstone"]},
            {"category": "Organic", "options": ["Dirt", "Algae"]},
        ]
    }

    assert choose_materials(building, load_material_state()) == [
        "SandStone",
        "Dirt",
    ]


def test_choose_materials_raises_insufficient_when_no_allowed_option_is_stocked():
    building = {
        "materials": [
            {"category": "Metal", "options": ["Cuprite"]},
        ]
    }

    with pytest.raises(CatalogError) as error:
        choose_materials(building, load_material_state())
    assert error.value.reason == "insufficient_material"


def test_choose_materials_reports_missing_material_inventory():
    building = {
        "materials": [
            {"category": "Metal", "options": ["Cuprite"]},
        ]
    }

    with pytest.raises(CatalogError) as error:
        choose_materials(building, {"resources": {"food_kcal": 10}})
    assert error.value.reason == "material_inventory_unavailable"
