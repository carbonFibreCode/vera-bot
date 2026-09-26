from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

Payload = dict[str, Any]


class ContextScope(StrEnum):
    CATEGORY = "category"
    MERCHANT = "merchant"
    CUSTOMER = "customer"
    TRIGGER = "trigger"


@dataclass(frozen=True, slots=True)
class StoredContext:
    version: int
    payload: Payload
    stored_at: datetime


class StaleVersionError(Exception):
    def __init__(self, current_version: int) -> None:
        super().__init__(f"already holding version {current_version}")
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class ContextBundle:
    category: Payload
    merchant: Payload
    trigger: Payload | None = None
    customer: Payload | None = None
    fingerprint: tuple[tuple[str, int], ...] = ()

    @property
    def merchant_id(self) -> str:
        return str(self.merchant.get("merchant_id", ""))

    @property
    def trigger_id(self) -> str:
        return str((self.trigger or {}).get("id", ""))


class ContextStore:
    def __init__(self) -> None:
        self._items: dict[ContextScope, dict[str, StoredContext]] = {s: {} for s in ContextScope}

    def put(
        self, scope: ContextScope, context_id: str, version: int, payload: Payload
    ) -> StoredContext:
        current = self._items[scope].get(context_id)
        if current and current.version >= version:
            raise StaleVersionError(current.version)
        stored = StoredContext(version=version, payload=payload, stored_at=datetime.now(UTC))
        self._items[scope][context_id] = stored
        return stored

    def get(self, scope: ContextScope, context_id: str | None) -> Payload | None:
        if not context_id:
            return None
        stored = self._items[scope].get(context_id)
        return stored.payload if stored else None

    def version(self, scope: ContextScope, context_id: str | None) -> int:
        stored = self._items[scope].get(context_id or "")
        return stored.version if stored else 0

    def counts(self) -> dict[str, int]:
        return {scope.value: len(items) for scope, items in self._items.items()}

    def clear(self) -> None:
        for items in self._items.values():
            items.clear()

    def bundle_for_trigger(self, trigger_id: str) -> ContextBundle | None:
        trigger = self.get(ContextScope.TRIGGER, trigger_id)
        if trigger is None:
            return None
        bundle = self.bundle_for_merchant(trigger.get("merchant_id"), trigger.get("customer_id"))
        if bundle is None:
            return None
        return ContextBundle(
            category=bundle.category,
            merchant=bundle.merchant,
            trigger=trigger,
            customer=bundle.customer,
            fingerprint=(
                *bundle.fingerprint,
                (trigger_id, self.version(ContextScope.TRIGGER, trigger_id)),
            ),
        )

    def bundle_for_merchant(
        self, merchant_id: str | None, customer_id: str | None = None
    ) -> ContextBundle | None:
        merchant = self.get(ContextScope.MERCHANT, merchant_id)
        if merchant is None:
            return None
        slug = merchant.get("category_slug")
        category = self.get(ContextScope.CATEGORY, slug)
        if category is None:
            return None
        customer = self.get(ContextScope.CUSTOMER, customer_id)
        fingerprint = (
            (f"category:{slug}", self.version(ContextScope.CATEGORY, slug)),
            (f"merchant:{merchant_id}", self.version(ContextScope.MERCHANT, merchant_id)),
            (f"customer:{customer_id}", self.version(ContextScope.CUSTOMER, customer_id)),
        )
        return ContextBundle(
            category=category, merchant=merchant, customer=customer, fingerprint=fingerprint
        )
