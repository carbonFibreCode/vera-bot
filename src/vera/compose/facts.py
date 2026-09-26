import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from vera.dialogue.language import Language

Payload = dict[str, Any]

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

_AGGREGATE_LABELS = {
    "total_unique_ytd": "unique customers this year",
    "total_active_members": "active members",
    "lapsed_180d_plus": "customers lapsed 180+ days",
    "lapsed_90d_plus": "customers lapsed 90+ days",
    "high_risk_adult_count": "high-risk adult patients",
    "chronic_rx_count": "chronic-Rx customers",
    "retention_6mo_pct": "6-month retention",
    "retention_3mo_pct": "3-month retention",
    "repeat_customer_pct": "repeat customers",
    "delivery_share_pct": "delivery share of orders",
    "monthly_churn_pct": "monthly churn",
    "trial_to_paid_pct": "trial-to-paid conversion",
    "delivery_orders_30d": "delivery orders (30d)",
    "dine_in_orders_30d": "dine-in orders (30d)",
}

_PEER_LABELS = {
    "avg_ctr": "CTR",
    "avg_rating": "rating",
    "avg_review_count": "reviews",
    "avg_views_30d": "views/30d",
    "avg_calls_30d": "calls/30d",
    "avg_post_freq_days": "posts every N days",
}


@dataclass(frozen=True, slots=True)
class FactSheet:
    kind: str
    salutation: str
    speaker: str
    language: Language
    voice: str
    taboos: tuple[str, ...]
    vocabulary: tuple[str, ...]
    facts: dict[str, str]
    customer_facing: bool = False
    talking_points: tuple[str, ...] = ()

    def get(self, label: str, default: str = "") -> str:
        return self.facts.get(label, default)

    @property
    def grounding_text(self) -> str:
        return " ".join([self.salutation, self.speaker, *self.facts.values(), *self.talking_points])

    def allowed_numbers(self) -> frozenset[float]:
        return frozenset(numbers_in(self.grounding_text))

    def render(self) -> str:
        return "\n".join(f"- {label}: {value}" for label, value in self.facts.items() if value)


def numbers_in(text: str) -> list[float]:
    return [float(token.replace(",", "")) for token in NUMBER.findall(text)]


def pct(value: Any) -> str:
    return f"{float(value) * 100:.1f}".rstrip("0").rstrip(".") + "%"


def signed_pct(value: Any) -> str:
    number = float(value) * 100
    return f"{number:+.0f}%"


def rupees(value: Any) -> str:
    return f"₹{float(value):,.0f}"


def humanize(token: Any) -> str:
    return str(token).replace("_", " ").strip()


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def nice_date(value: Any) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%-d %b %Y") if parsed else str(value)


def days_between(start: Any, end: date) -> int | None:
    parsed = parse_date(start)
    return (end - parsed).days if parsed else None


def find_digest_item(category: Payload, item_id: Any) -> Payload | None:
    return next((d for d in category.get("digest", []) if d.get("id") == item_id), None)


def digest_facts(item: Payload | None, prefix: str = "item") -> dict[str, str]:
    if not item:
        return {}
    facts = {
        f"{prefix} title": item.get("title", ""),
        f"{prefix} source": item.get("source", ""),
        f"{prefix} summary": item.get("summary", ""),
        f"{prefix} suggested action": item.get("actionable", ""),
    }
    if item.get("trial_n"):
        facts[f"{prefix} sample size"] = f"{item['trial_n']:,} patients"
    if item.get("patient_segment"):
        facts[f"{prefix} applies to"] = humanize(item["patient_segment"])
    return facts


def active_offers(merchant: Payload) -> list[str]:
    return [o["title"] for o in merchant.get("offers", []) if o.get("status") == "active"]


def owner_name(merchant: Payload) -> str:
    return str(merchant.get("identity", {}).get("owner_first_name", "")).strip()


def merchant_salutation(merchant: Payload, category: Payload) -> str:
    owner = owner_name(merchant)
    if not owner:
        return f"{merchant.get('identity', {}).get('name', 'there')} team"
    if category.get("slug") == "dentists" and not owner.lower().startswith("dr"):
        return f"Dr. {owner}"
    return owner


def customer_salutation(customer: Payload) -> str:
    name = str(customer.get("identity", {}).get("name", ""))
    channel = str(customer.get("preferences", {}).get("channel", ""))
    if guardian := re.search(r"\((?:parent|guardian):\s*([^)]+)\)", name):
        return guardian.group(1).strip()
    if "via_" in channel:
        return "Namaste"
    return re.sub(r"\s*\(.*\)", "", name).strip() or "there"


def merchant_facts(merchant: Payload, category: Payload) -> dict[str, str]:
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    facts = {
        "business": identity.get("name", ""),
        "owner": owner_name(merchant),
        "location": ", ".join(filter(None, [identity.get("locality"), identity.get("city")])),
        "Google profile verified": "yes" if identity.get("verified") else "no",
        "active offers": "; ".join(active_offers(merchant)) or "none running",
        "reporting window": "last 30 days; weekly change covers the last 7 days",
        "last 30 days": _performance_line(perf),
        "7-day change": _delta_line(perf.get("delta_7d", {})),
        "peer benchmark": _peer_line(category.get("peer_stats", {})),
        "customer base": _aggregate_line(merchant.get("customer_aggregate", {})),
        "account signals": ", ".join(_signal(s) for s in merchant.get("signals", [])),
        "review themes": _review_line(merchant.get("review_themes", [])),
        "subscription": _subscription_line(merchant.get("subscription", {})),
    }
    if last := _last_exchange(merchant.get("conversation_history", [])):
        facts["last exchange with Vera"] = last
    return facts


def customer_facts(customer: Payload, today: date) -> dict[str, str]:
    identity = customer.get("identity", {})
    relation = customer.get("relationship", {})
    prefs = customer.get("preferences", {})
    services = list(dict.fromkeys(reversed(relation.get("services_received", []))))
    facts = {
        "customer": re.sub(r"\s*\(.*\)", "", str(identity.get("name", ""))),
        "address them as": customer_salutation(customer),
        "customer status": humanize(customer.get("state", "")),
        "visits so far": str(relation.get("visits_total", "")),
        "last visit": nice_date(relation.get("last_visit")) if relation.get("last_visit") else "",
        "recent services": ", ".join(humanize(s) for s in services[:3]),
        "preferred time": humanize(prefs.get("preferred_slots", "")),
        "consented to": ", ".join(
            humanize(s) for s in customer.get("consent", {}).get("scope", [])
        ),
    }
    days = days_between(relation.get("last_visit"), today)
    if days is not None and days > 0:
        facts["time since last visit"] = _elapsed(days)
    if identity.get("senior_citizen"):
        facts["senior citizen"] = "yes"
    for extra in ("training_focus", "health_focus", "preferred_stylist", "wedding_date"):
        if prefs.get(extra):
            facts[humanize(extra)] = humanize(prefs[extra])
    return facts


def _performance_line(perf: Payload) -> str:
    parts = [
        f"{perf[key]:,} {label}"
        for key, label in (
            ("views", "views"),
            ("calls", "calls"),
            ("directions", "direction requests"),
            ("leads", "leads"),
        )
        if isinstance(perf.get(key), int)
    ]
    if perf.get("ctr") is not None:
        parts.append(f"CTR {pct(perf['ctr'])}")
    return ", ".join(parts)


def _delta_line(delta: Payload) -> str:
    return ", ".join(
        f"{humanize(key.removesuffix('_pct'))} {signed_pct(value)}"
        for key, value in delta.items()
        if isinstance(value, int | float)
    )


def _peer_line(peers: Payload) -> str:
    parts = []
    for key, label in _PEER_LABELS.items():
        if key in peers:
            value = pct(peers[key]) if key == "avg_ctr" else f"{peers[key]:,}"
            parts.append(f"{label} {value}")
    scope = humanize(peers.get("scope", "peers"))
    return f"{scope}: " + ", ".join(parts) if parts else ""


def _aggregate_line(aggregate: Payload) -> str:
    parts = []
    for key, value in aggregate.items():
        label = _AGGREGATE_LABELS.get(key, humanize(key))
        parts.append(f"{label} {pct(value) if key.endswith('_pct') else f'{value:,}'}")
    return ", ".join(parts)


def _signal(raw: str) -> str:
    name, _, detail = raw.partition(":")
    return f"{humanize(name)} ({detail})" if detail else humanize(name)


def _review_line(themes: list[Payload]) -> str:
    return "; ".join(
        f"{humanize(t.get('theme'))} ({t.get('sentiment')}, {t.get('occurrences_30d')} in 30d)"
        + (f': "{t["common_quote"]}"' if t.get("common_quote") else "")
        for t in themes
    )


def _subscription_line(subscription: Payload) -> str:
    if not subscription:
        return ""
    line = f"{subscription.get('plan', '')} plan, {subscription.get('status', '')}"
    if subscription.get("days_remaining") is not None:
        line += f", {subscription['days_remaining']} days left"
    return line


def _last_exchange(history: list[Payload]) -> str:
    if not history:
        return ""
    last = history[-1]
    speaker = "Vera" if last.get("from") == "vera" else "merchant"
    return f'{speaker} said "{last.get("body", "")}" ({humanize(last.get("engagement", ""))})'


def _elapsed(days: int) -> str:
    if days < 60:
        return f"{days} days"
    return f"about {round(days / 30)} months"
