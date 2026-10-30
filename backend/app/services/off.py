"""Open Food Facts client: search, product lookup, 24 h cache and result mapping (spec F6, D44).

* Requests carry `User-Agent: FitWise/<version> (<contact>)` and are abandoned after the
  configured total deadline (3 s for the whole request, not per phase). Failures never raise:
  they become an `OffUnavailable` result with a reason (`timeout` or `upstream_error`) so the
  API can answer `available: false` (F6.3).
* Successful searches are cached for 24 h per normalised query; every product seen is cached by
  code for the same time so `POST /foods/import` does not need a second upstream call.
* Nothing here logs the query, product names or brands: they are user content (spec section 6.5).
  Only the failure kind is logged.
"""

import datetime as dt
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final, Literal

import httpx2 as httpx

from app.config import Settings
from app.telemetry import get_logger

log = get_logger(__name__)

CACHE_TTL: Final = dt.timedelta(hours=24)
MAX_CACHED_SEARCHES: Final = 500
MAX_CACHED_PRODUCTS: Final = 5000
# Upstream page size: one cached upstream page serves every `limit` up to the API maximum.
UPSTREAM_PAGE_SIZE: Final = 50
UPSTREAM_FIELDS: Final = (
    "code,product_name,brands,nutriments,allergens_tags,ingredients_analysis_tags"
)
KJ_PER_KCAL: Final = 4.184

UnavailableReason = Literal["disabled", "timeout", "upstream_error"]

_ALLERGENS: Final = {
    "en:gluten": "gluten",
    "en:milk": "lactose",
    "en:nuts": "nuts",
    "en:eggs": "eggs",
    "en:soybeans": "soy",
    "en:crustaceans": "shellfish",
    "en:molluscs": "shellfish",
    "en:fish": "fish",
}


@dataclass(frozen=True, slots=True)
class OffProduct:
    code: str
    name: str
    brand: str | None
    kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    diet_tags: tuple[str, ...]
    allergen_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OffUnavailable:
    reason: UnavailableReason


class _UpstreamError(Exception):
    def __init__(self, reason: UnavailableReason) -> None:
        super().__init__(reason)
        self.reason = reason


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, int | float) and math.isfinite(value):
        return float(value)
    return None


def _round1(value: float) -> float:
    return math.floor(value * 10 + 0.5) / 10


def parse_product(raw: Any) -> OffProduct | None:
    """Map one upstream product; `None` when it lacks a usable code, name or nutrition.

    Open Food Facts data quality varies (spec A3), so anything outside the `Food` limits is
    skipped rather than clamped.
    """
    if not isinstance(raw, dict):
        return None
    code = raw.get("code")
    name = raw.get("product_name")
    if not (isinstance(code, str) and code.isascii() and code.isdigit() and 4 <= len(code) <= 14):
        return None
    if not isinstance(name, str) or len(name.strip()) < 2:
        return None
    nutriments = raw.get("nutriments")
    if not isinstance(nutriments, dict):
        return None
    kcal = _number(nutriments.get("energy-kcal_100g"))
    if kcal is None:
        kj = _number(nutriments.get("energy_100g"))
        kcal = kj / KJ_PER_KCAL if kj is not None else None
    protein = _number(nutriments.get("proteins_100g"))
    carbs = _number(nutriments.get("carbohydrates_100g"))
    fat = _number(nutriments.get("fat_100g"))
    if kcal is None or protein is None or carbs is None or fat is None:
        return None
    kcal, protein, carbs, fat = (_round1(v) for v in (kcal, protein, carbs, fat))
    if not (0 <= kcal <= 900 and all(0 <= v <= 100 for v in (protein, carbs, fat))):
        return None
    brand_raw = raw.get("brands")
    brand = brand_raw.split(",")[0].strip()[:80] if isinstance(brand_raw, str) else ""
    allergen_raw = raw.get("allergens_tags")
    allergens = (
        {_ALLERGENS[t] for t in allergen_raw if t in _ALLERGENS}
        if isinstance(allergen_raw, list)
        else set()
    )
    analysis = raw.get("ingredients_analysis_tags")
    tags = set(analysis) if isinstance(analysis, list) else set()
    if "en:vegan" in tags:
        diets: tuple[str, ...] = ("vegan", "vegetarian", "pescatarian")
    elif "en:vegetarian" in tags:
        diets = ("vegetarian", "pescatarian")
    else:
        diets = ()
    return OffProduct(
        code=code,
        name=name.strip()[:120],
        brand=brand or None,
        kcal_per_100g=kcal,
        protein_g_per_100g=protein,
        carbs_g_per_100g=carbs,
        fat_g_per_100g=fat,
        diet_tags=diets,
        allergen_tags=tuple(sorted(allergens)),
    )


class OffClient:
    """Thread-safe client with the 24 h caches. One instance per app (`app.state.off`)."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.off_base_url
        self._timeout = settings.off_timeout_seconds
        self._client = httpx.Client(
            timeout=settings.off_timeout_seconds,
            headers={
                "User-Agent": f"FitWise/{settings.app_version} ({settings.off_contact})",
                "Accept": "application/json",
            },
        )
        self._lock = threading.Lock()
        self._searches: OrderedDict[str, tuple[dt.datetime, tuple[OffProduct, ...]]] = OrderedDict()
        self._products: OrderedDict[str, tuple[dt.datetime, OffProduct]] = OrderedDict()

    @property
    def http_client(self) -> httpx.Client:
        return self._client

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, now: dt.datetime) -> tuple[OffProduct, ...] | OffUnavailable:
        key = " ".join(query.lower().split())
        with self._lock:
            hit = self._searches.get(key)
            if hit is not None and now < hit[0]:
                return hit[1]
        try:
            payload = self._get(
                "/cgi/search.pl",
                {
                    "search_terms": query,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "page_size": UPSTREAM_PAGE_SIZE,
                    "fields": UPSTREAM_FIELDS,
                },
            )
        except _UpstreamError as error:
            return OffUnavailable(error.reason)
        raw_products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(raw_products, list):
            log.warning("open food facts response invalid", outcome="error")
            return OffUnavailable("upstream_error")
        products = tuple(p for p in map(parse_product, raw_products) if p is not None)
        expires = now + CACHE_TTL
        with self._lock:
            self._searches[key] = (expires, products)
            self._searches.move_to_end(key)
            while len(self._searches) > MAX_CACHED_SEARCHES:
                self._searches.popitem(last=False)
            for product in products:
                self._products[product.code] = (expires, product)
                self._products.move_to_end(product.code)
            while len(self._products) > MAX_CACHED_PRODUCTS:
                self._products.popitem(last=False)
        return products

    def cached_product(self, code: str, now: dt.datetime) -> OffProduct | None:
        with self._lock:
            hit = self._products.get(code)
        return hit[1] if hit is not None and now < hit[0] else None

    def product(self, code: str, now: dt.datetime) -> OffProduct | OffUnavailable | None:
        """Cached or fetched product; `None` when Open Food Facts does not know the code."""
        cached = self.cached_product(code, now)
        if cached is not None:
            return cached
        try:
            payload = self._get(f"/api/v2/product/{code}.json", {"fields": UPSTREAM_FIELDS})
        except _UpstreamError as error:
            return OffUnavailable(error.reason)
        if not isinstance(payload, dict):
            return OffUnavailable("upstream_error")
        product = parse_product(payload.get("product"))
        if product is None or product.code != code:
            return None
        with self._lock:
            self._products[code] = (now + CACHE_TTL, product)
        return product

    def _fetch(self, url: str, params: dict[str, Any], box: dict[str, Any]) -> None:
        """Worker: runs one request, streaming the body; stores `response` or `error` in `box`."""
        try:
            with self._client.stream("GET", url, params=params) as streamed:
                box["stream"] = streamed
                body = b"".join(streamed.iter_bytes())
                box["response"] = httpx.Response(
                    streamed.status_code, headers=streamed.headers, content=body
                )
        except Exception as error:  # re-raised on the caller's thread
            box["error"] = error

    def _request(self, url: str, params: dict[str, Any]) -> httpx.Response:
        """One request under a total deadline of `off_timeout_seconds` (httpx limits each phase
        separately, so a response trickling in slowly would otherwise outlive the setting)."""
        box: dict[str, Any] = {}
        worker = threading.Thread(target=self._fetch, args=(url, params, box), daemon=True)
        worker.start()
        worker.join(self._timeout)
        if worker.is_alive():
            stream = box.get("stream")
            if stream is not None:
                stream.close()  # unblocks the worker's read
            raise httpx.ReadTimeout("total deadline exceeded")
        if "error" in box:
            raise box["error"]
        response: httpx.Response = box["response"]
        return response

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = self._request(f"{self._base_url}{path}", params)
        except httpx.TimeoutException as error:
            log.warning(
                "open food facts request failed",
                outcome="timeout",
                error_type=type(error).__name__,
            )
            raise _UpstreamError("timeout") from error
        except httpx.HTTPError as error:
            log.warning(
                "open food facts request failed",
                outcome="error",
                error_type=type(error).__name__,
            )
            raise _UpstreamError("upstream_error") from error
        if response.status_code == 404 and "/product/" in path:
            return {"status": 0}  # Open Food Facts answers 404 for an unknown barcode
        if response.status_code != 200:
            log.warning(
                "open food facts request failed", outcome="error", status=response.status_code
            )
            raise _UpstreamError("upstream_error")
        try:
            return response.json()
        except ValueError as error:
            log.warning(
                "open food facts request failed",
                outcome="error",
                error_type=type(error).__name__,
            )
            raise _UpstreamError("upstream_error") from error
