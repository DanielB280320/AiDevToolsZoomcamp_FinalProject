"""Open Food Facts search and import on top of the local `Food` table (spec F6, D44).

Search and import degrade instead of failing: a disabled flag, a timeout or an upstream error
gives `available: false` (search) or 503 `off_unavailable` (import of a product that is neither
imported nor cached). An imported product is stored once, unique on its product code (F6.2).

Nothing here logs: queries, names and brands are user content (spec section 6.5).
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import Food
from app.schemas.foods import Food as FoodOut
from app.schemas.foods import OffProduct as OffProductOut
from app.schemas.foods import OffSearchResult
from app.services.foods import _food_view
from app.services.off import OffClient, OffProduct, OffUnavailable, UnavailableReason
from app.telemetry.metrics import FitwiseMetrics, OffSearchOutcome

UNAVAILABLE_MESSAGE = "Online food search is unavailable — use the library or create a custom food."

_OUTCOME: dict[UnavailableReason, OffSearchOutcome] = {
    "disabled": "disabled",
    "timeout": "timeout",
    "upstream_error": "error",
}


def _unavailable(reason: UnavailableReason) -> OffSearchResult:
    return OffSearchResult(
        available=False, unavailable_reason=reason, message=UNAVAILABLE_MESSAGE, items=[]
    )


def search(
    session: Session,
    off: OffClient,
    metrics: FitwiseMetrics,
    *,
    enabled: bool,
    query: str,
    limit: int,
    now: dt.datetime,
) -> OffSearchResult:
    """Search results (cached 24 h) with `imported_food_id` for products already imported."""
    if not enabled:
        metrics.off_search("disabled")
        return _unavailable("disabled")
    found = off.search(query, now)
    if isinstance(found, OffUnavailable):
        metrics.off_search(_OUTCOME[found.reason])
        return _unavailable(found.reason)
    metrics.off_search("ok")
    products = found[:limit]
    codes = [p.code for p in products]
    imported: dict[str | None, object] = {}
    if codes:
        rows = session.execute(
            select(Food.external_code, Food.id).where(Food.external_code.in_(codes))
        ).all()
        imported = {code: food_id for code, food_id in rows}  # noqa: C416
    items = [
        OffProductOut.model_validate(
            {
                "code": p.code,
                "name": p.name,
                "brand": p.brand,
                "kcal_per_100g": p.kcal_per_100g,
                "protein_g_per_100g": p.protein_g_per_100g,
                "carbs_g_per_100g": p.carbs_g_per_100g,
                "fat_g_per_100g": p.fat_g_per_100g,
                "imported_food_id": imported.get(p.code),
            }
        )
        for p in products
    ]
    return OffSearchResult(available=True, unavailable_reason=None, message=None, items=items)


def _by_code(session: Session, code: str) -> Food | None:
    return session.scalars(select(Food).where(Food.external_code == code)).first()


def import_product(
    session: Session, off: OffClient, *, enabled: bool, code: str, now: dt.datetime
) -> tuple[FoodOut, bool]:
    """The local food for `code` and whether it was created now (201) or existed (200)."""
    existing = _by_code(session, code)
    if existing is not None:
        return _food_view(existing, None), False
    unavailable = ProblemError(503, "off_unavailable", UNAVAILABLE_MESSAGE)
    if not enabled:
        raise unavailable
    product = off.product(code, now)  # the 24 h cache first, then one upstream lookup
    if isinstance(product, OffUnavailable):
        raise unavailable
    if product is None:
        raise ProblemError(404, "not_found", "Open Food Facts has no product with that code.")
    created = _insert(session, product)
    if created is None:  # a concurrent import won the unique index
        existing = _by_code(session, code)
        assert existing is not None  # noqa: S101 - the conflict proves the row exists
        return _food_view(existing, None), False
    return _food_view(created, None), True


def _insert(session: Session, product: OffProduct) -> Food | None:
    row_id = session.execute(
        insert(Food)
        .values(
            owner_id=None,
            source="openfoodfacts",
            external_code=product.code,
            name=product.name,
            brand=product.brand,
            kcal_per_100g=product.kcal_per_100g,
            protein_g_per_100g=product.protein_g_per_100g,
            carbs_g_per_100g=product.carbs_g_per_100g,
            fat_g_per_100g=product.fat_g_per_100g,
            diet_tags=list(product.diet_tags),
            allergen_tags=list(product.allergen_tags),
        )
        .on_conflict_do_nothing(
            index_elements=[Food.external_code], index_where=Food.external_code.is_not(None)
        )
        .returning(Food.id)
    ).scalar()
    session.commit()
    return session.get(Food, row_id) if row_id is not None else None
