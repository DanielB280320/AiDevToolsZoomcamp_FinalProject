"""Mapping of Open Food Facts products to FitWise foods (spec F6, A3: data quality varies)."""

from typing import Any

import pytest

from app.services.off import parse_product
from tests.fake_off import product


def _with(**nutriments: Any) -> dict[str, Any]:
    base = {
        "energy-kcal_100g": 100,
        "proteins_100g": 10,
        "carbohydrates_100g": 10,
        "fat_100g": 10,
    }
    base.update(nutriments)
    return product("12345678", "Test food", nutriments=base)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "text",
        {},
        product("1234", "x"),  # name too short
        product("123", "Short code"),
        product("123456789012345", "Long code"),
        product("12345678", "No nutriments", nutriments=None),
        product("12345678", "Missing fat", nutriments={"energy-kcal_100g": 1, "proteins_100g": 1}),
        _with(**{"energy-kcal_100g": 901}),
        _with(proteins_100g=100.5),
        _with(fat_100g=-1),
        _with(proteins_100g="abc"),
        _with(proteins_100g=True),
        _with(proteins_100g=float("nan")),
    ],
)
def test_unusable_products_are_skipped(raw: Any) -> None:
    assert parse_product(raw) is None


def test_values_are_rounded_to_one_decimal_and_strings_accepted() -> None:
    parsed = parse_product(_with(proteins_100g="12.34", fat_100g=0.05))
    assert parsed is not None
    assert (parsed.protein_g_per_100g, parsed.fat_g_per_100g) == (12.3, 0.1)


def test_kilojoules_are_used_only_when_kcal_is_missing() -> None:
    only_kj = {"energy_100g": 418.4, "proteins_100g": 0, "carbohydrates_100g": 0, "fat_100g": 0}
    parsed = parse_product(product("12345678", "Kj only", nutriments=only_kj))
    assert parsed is not None and parsed.kcal_per_100g == 100.0


def test_brand_name_and_tags() -> None:
    raw = product(
        "12345678",
        "  A very " + "long " * 40 + "name ",
        brands="First, Second",
        allergens_tags=["en:milk", "en:molluscs", "en:crustaceans", "en:unknown"],
        ingredients_analysis_tags=["en:vegan"],
    )
    parsed = parse_product(raw)
    assert parsed is not None
    assert parsed.brand == "First"
    assert len(parsed.name) == 120
    assert parsed.allergen_tags == ("lactose", "shellfish")
    assert parsed.diet_tags == ("vegan", "vegetarian", "pescatarian")


def test_no_claim_when_diet_is_unknown() -> None:
    parsed = parse_product(
        product("12345678", "Maybe", ingredients_analysis_tags=["en:maybe-vegan"])
    )
    assert parsed is not None and parsed.diet_tags == ()
    parsed = parse_product(product("12345678", "No brand", brands="", allergens_tags=None))
    assert parsed is not None and parsed.brand is None and parsed.allergen_tags == ()
