from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from vera.compose.facts import (
    Payload,
    active_offers,
    days_between,
    digest_facts,
    find_digest_item,
    humanize,
    nice_date,
    parse_date,
    pct,
    rupees,
    signed_pct,
)
from vera.store.contexts import ContextBundle


class CtaType(StrEnum):
    OPEN_ENDED = "open_ended"
    BINARY_YES_NO = "binary_yes_no"
    BINARY_CONFIRM_CANCEL = "binary_confirm_cancel"
    MULTI_CHOICE_SLOT = "multi_choice_slot"
    NONE = "none"


class SendAs(StrEnum):
    VERA = "vera"
    MERCHANT_ON_BEHALF = "merchant_on_behalf"


class TriggerFamily(StrEnum):
    KNOWLEDGE = "knowledge"
    COMPLIANCE = "compliance"
    PERFORMANCE = "performance"
    REPUTATION = "reputation"
    COMMERCIAL = "commercial"
    MOMENT = "moment"
    CONVERSATIONAL = "conversational"
    CUSTOMER = "customer"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class Framing:
    family: TriggerFamily
    angle: str
    levers: tuple[str, ...]
    cta: CtaType

    @property
    def send_as(self) -> SendAs:
        return SendAs.MERCHANT_ON_BEHALF if self.family is TriggerFamily.CUSTOMER else SendAs.VERA


FRAMINGS = {
    TriggerFamily.KNOWLEDGE: Framing(
        TriggerFamily.KNOWLEDGE,
        "Share one piece of category knowledge that matters to this merchant. Cite the source "
        "exactly, tie it to their own customers or numbers, offer to do the follow-up work.",
        ("source citation", "curiosity", "reciprocity", "merchant-specific anchor"),
        CtaType.OPEN_ENDED,
    ),
    TriggerFamily.COMPLIANCE: Framing(
        TriggerFamily.COMPLIANCE,
        "Flag a compliance or safety change with its deadline or batch details. Calm and precise, "
        "no alarm. Quantify what it means for this merchant, then offer the checklist or draft.",
        ("urgency", "specificity", "effort externalisation"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.PERFORMANCE: Framing(
        TriggerFamily.PERFORMANCE,
        "Explain what moved in their numbers and why it matters now, using the peer benchmark. "
        "Add a judgment call only when FACTS support it. Offer one concrete fix.",
        ("loss aversion", "peer benchmark", "reframe", "effort externalisation"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.REPUTATION: Framing(
        TriggerFamily.REPUTATION,
        "Point to what customers or the market are saying (review quote, competitor move, "
        "verification gap). Stay factual about competitors. Offer a ready-made response.",
        ("social proof", "loss aversion", "curiosity"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.COMMERCIAL: Framing(
        TriggerFamily.COMMERCIAL,
        "Reconnect around the account itself. Lead with the value they got or stand to lose, "
        "using their real numbers. No hard sell.",
        ("loss aversion", "reciprocity", "single binary commitment"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.MOMENT: Framing(
        TriggerFamily.MOMENT,
        "Use a timely external moment (festival, match, season). Show judgment about whether and "
        "how to act on it for this category, and anchor on an offer they already have.",
        ("timeliness", "contrarian judgment", "effort externalisation"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.CONVERSATIONAL: Framing(
        TriggerFamily.CONVERSATIONAL,
        "Continue a real conversation. Ask the merchant something easy to answer, or hand over "
        "a concrete draft they asked for. Make replying effortless.",
        ("asking the merchant", "reciprocity", "effort externalisation"),
        CtaType.OPEN_ENDED,
    ),
    TriggerFamily.CUSTOMER: Framing(
        TriggerFamily.CUSTOMER,
        "Write as the business to its own customer. Warm, respectful, no pressure or guilt, no "
        "medical claims. Use real dates, slots and prices only. Honour their preferred time.",
        ("personalisation", "specific slot or price", "no-commitment framing"),
        CtaType.BINARY_YES_NO,
    ),
    TriggerFamily.GENERIC: Framing(
        TriggerFamily.GENERIC,
        "Explain plainly why you are reaching out now using the trigger details, then offer one "
        "useful next step.",
        ("specificity", "single binary commitment"),
        CtaType.BINARY_YES_NO,
    ),
}


@dataclass(frozen=True, slots=True)
class TriggerRead:
    facts: dict[str, str]
    hook: str
    deliverable: str
    proof: str = ""
    closing: str = ""
    cta: CtaType | None = None
    options: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ReadContext:
    bundle: ContextBundle
    today: date

    @property
    def payload(self) -> Payload:
        return dict((self.bundle.trigger or {}).get("payload") or {})

    @property
    def merchant(self) -> Payload:
        return self.bundle.merchant

    @property
    def category(self) -> Payload:
        return self.bundle.category

    @property
    def customer(self) -> Payload:
        return self.bundle.customer or {}

    @property
    def business(self) -> str:
        return str(self.merchant.get("identity", {}).get("name", "your business"))

    @property
    def audience(self) -> str:
        return {"dentists": "patients", "gyms": "members", "salons": "clients"}.get(
            str(self.category.get("slug")), "customers"
        )

    @property
    def aggregate(self) -> Payload:
        return dict(self.merchant.get("customer_aggregate") or {})

    def digest(self, item_id: Any = None, kind: str | None = None) -> Payload | None:
        if item_id and (item := find_digest_item(self.category, item_id)):
            return item
        return next((d for d in self.category.get("digest", []) if d.get("kind") == kind), None)

    def first_offer(self) -> str:
        offers = active_offers(self.merchant)
        if offers:
            return offers[0]
        catalog = self.category.get("offer_catalog", [])
        priced = [o for o in catalog if o.get("type") == "service_at_price"] or catalog
        return str(priced[0]["title"]) if priced else ""

    def days_until(self, value: Any) -> int | None:
        target = parse_date(value)
        return (target - self.today).days if target else None


Reader = Callable[[ReadContext], TriggerRead]


@dataclass(frozen=True, slots=True)
class Strategy:
    framing: Framing
    read: Reader


_REGISTRY: dict[str, Strategy] = {}


def reads(family: TriggerFamily, *kinds: str) -> Callable[[Reader], Reader]:
    def register(reader: Reader) -> Reader:
        for kind in kinds:
            _REGISTRY[kind] = Strategy(FRAMINGS[family], reader)
        return reader

    return register


def strategy_for(kind: str, scope: str | None = None) -> Strategy:
    if kind in _REGISTRY:
        return _REGISTRY[kind]
    family = TriggerFamily.CUSTOMER if scope == "customer" else TriggerFamily.GENERIC
    return Strategy(FRAMINGS[family], read_generic)


def read_generic(ctx: ReadContext) -> TriggerRead:
    kind = humanize((ctx.bundle.trigger or {}).get("kind", "update"))
    facts = {
        humanize(key): humanize(value)
        for key, value in ctx.payload.items()
        if isinstance(value, str | int | float) and key not in {"placeholder", "metric_or_topic"}
    }
    return TriggerRead(
        facts=facts,
        hook=f"a quick {kind} update for {ctx.business}.",
        deliverable="take care of the next step for you",
    )


def read_open_thread(ctx: ReadContext) -> TriggerRead:
    signals = " ".join(ctx.merchant.get("signals", []))
    if "stale_posts" in signals:
        deliverable = "draft 3 fresh Google posts for your review"
    elif "unverified" in signals or not ctx.merchant.get("identity", {}).get("verified", True):
        deliverable = "finish your Google profile verification with you"
    elif not active_offers(ctx.merchant) and ctx.first_offer():
        deliverable = f"put {ctx.first_offer()} live on your listing"
    else:
        deliverable = "draft this week's Google post for your review"
    return TriggerRead(facts={}, hook="following up on my last message.", deliverable=deliverable)


@reads(TriggerFamily.KNOWLEDGE, "research_digest", "category_research_digest_release")
def read_research(ctx: ReadContext) -> TriggerRead:
    item: Payload = (
        ctx.digest(ctx.payload.get("top_item_id"), kind="research")
        or ctx.payload.get("top_item")
        or {}
    )
    facts = digest_facts(item)
    cohort = ctx.aggregate.get("high_risk_adult_count")
    if "high_risk" in str(item.get("patient_segment", "")) and cohort:
        facts["matching patients in their roster"] = f"{cohort:,}"
    proof = ""
    if item.get("trial_n"):
        proof = f"It's a {item['trial_n']:,}-patient study"
        matching = facts.get("matching patients in their roster")
        proof += f", and {matching} of your patients fall in that group." if matching else "."
    return TriggerRead(
        facts=facts,
        hook=f"{item.get('source', 'This week’s digest')} has one worth your time: "
        f"{item.get('title', 'a new item in this week’s digest')}.",
        proof=proof,
        deliverable=f"pull the 2-minute summary and draft a note you can share with your {ctx.audience}",
    )


@reads(TriggerFamily.KNOWLEDGE, "cde_opportunity")
def read_cde(ctx: ReadContext) -> TriggerRead:
    item = ctx.digest(ctx.payload.get("digest_item_id"), kind="cde")
    facts = digest_facts(item)
    if ctx.payload.get("credits"):
        facts["CDE credits"] = str(ctx.payload["credits"])
    if ctx.payload.get("fee"):
        facts["fee"] = humanize(ctx.payload["fee"])
    credits = f" ({ctx.payload['credits']} CDE credits, {humanize(ctx.payload.get('fee', ''))})"
    return TriggerRead(
        facts=facts,
        hook=f"{(item or {}).get('title', 'a CDE session is open')}{credits if ctx.payload.get('credits') else ''}.",
        deliverable="register you and block the slot in your calendar",
        cta=CtaType.BINARY_YES_NO,
    )


@reads(TriggerFamily.COMPLIANCE, "regulation_change")
def read_regulation(ctx: ReadContext) -> TriggerRead:
    item = ctx.digest(ctx.payload.get("top_item_id"), kind="compliance")
    facts = digest_facts(item)
    deadline = ctx.payload.get("deadline_iso")
    days = ctx.days_until(deadline)
    if deadline:
        facts["deadline"] = nice_date(deadline)
    if days is not None and days > 0:
        facts["days until deadline"] = str(days)
    when = f" Deadline: {nice_date(deadline)}" + (
        f", {days} days away." if days and days > 0 else "."
    )
    return TriggerRead(
        facts=facts,
        hook=f"{(item or {}).get('source', 'A new circular')}: {(item or {}).get('title', 'a rule change')}."
        + (when if deadline else ""),
        proof=str((item or {}).get("summary", "")),
        deliverable="send you a 5-point audit checklist for your setup",
    )


@reads(TriggerFamily.COMPLIANCE, "supply_alert")
def read_supply_alert(ctx: ReadContext) -> TriggerRead:
    batches = ", ".join(ctx.payload.get("affected_batches", []))
    molecule = humanize(ctx.payload.get("molecule", "a medicine"))
    item = ctx.digest(ctx.payload.get("alert_id"), kind="alert")
    facts = {
        "molecule": molecule,
        "affected batches": batches,
        "manufacturer": str(ctx.payload.get("manufacturer", "")),
        **digest_facts(item, prefix="alert"),
    }
    chronic = ctx.aggregate.get("chronic_rx_count")
    if chronic:
        facts["their chronic-Rx customers"] = f"{chronic:,}"
    return TriggerRead(
        facts=facts,
        hook=f"urgent: recall on {molecule} batches {batches} ({ctx.payload.get('manufacturer', '')}).",
        proof=f"Worth checking which of your {chronic:,} chronic-Rx customers got these batches."
        if chronic
        else "",
        deliverable="draft the customer WhatsApp note and a replacement-pickup checklist",
    )


def _metric_facts(ctx: ReadContext) -> tuple[dict[str, str], str, float | None]:
    metric = str(ctx.payload.get("metric", "views"))
    delta = ctx.payload.get("delta_pct")
    if not isinstance(delta, int | float):
        delta = ctx.merchant.get("performance", {}).get("delta_7d", {}).get(f"{metric}_pct")
    facts = {"metric": humanize(metric), "window": str(ctx.payload.get("window", "7d"))}
    if isinstance(delta, int | float):
        facts["change"] = signed_pct(delta)
    if ctx.payload.get("vs_baseline") is not None:
        facts[f"baseline {humanize(metric)}"] = str(ctx.payload["vs_baseline"])
    current = ctx.merchant.get("performance", {}).get(metric)
    if current is not None:
        facts[f"current {humanize(metric)} (30d)"] = f"{current:,}"
    peer = ctx.category.get("peer_stats", {}).get(f"avg_{metric}_30d")
    if peer is not None:
        facts[f"peer average {humanize(metric)} (30d)"] = f"{peer:,}"
    return facts, humanize(metric), float(delta) if isinstance(delta, int | float) else None


@reads(TriggerFamily.PERFORMANCE, "perf_dip", "perf_spike")
def read_perf_move(ctx: ReadContext) -> TriggerRead:
    facts, metric, delta = _metric_facts(ctx)
    rising = delta > 0 if delta else str((ctx.bundle.trigger or {}).get("kind")) == "perf_spike"
    driver = ctx.payload.get("likely_driver")
    if driver:
        facts["likely driver"] = humanize(driver)
    signals = " ".join(ctx.merchant.get("signals", []))
    if rising:
        deliverable = (
            f"turn the {humanize(driver)} into a repeatable weekly post"
            if driver
            else "draft a Google post to ride this momentum"
        )
    elif "stale_posts" in signals:
        deliverable = "draft 3 fresh Google posts to lift your visibility"
    elif not active_offers(ctx.merchant) and ctx.first_offer():
        deliverable = f"put {ctx.first_offer()} live as an offer on your listing"
    else:
        deliverable = "draft a Google post and an offer refresh to win them back"
    direction = "up" if rising else "down"
    movement = f"{direction} {facts['change'].lstrip('+-')}" if delta else f"trending {direction}"
    return TriggerRead(
        facts=facts,
        hook=f"your {metric} are {movement} over the last {facts['window']}.",
        proof=_peer_gap(ctx, metric),
        deliverable=deliverable,
    )


def _peer_gap(ctx: ReadContext, metric: str) -> str:
    perf = ctx.merchant.get("performance", {})
    peers = ctx.category.get("peer_stats", {})
    if perf.get("ctr") is not None and peers.get("avg_ctr"):
        return f"Your CTR is {pct(perf['ctr'])} against a peer average of {pct(peers['avg_ctr'])}."
    peer = peers.get(f"avg_{metric}_30d")
    if perf.get(metric) is not None and peer:
        return f"You're at {perf[metric]:,} {metric} in 30 days; peers average {peer:,}."
    return ""


@reads(TriggerFamily.PERFORMANCE, "seasonal_perf_dip")
def read_seasonal_dip(ctx: ReadContext) -> TriggerRead:
    facts, metric, _ = _metric_facts(ctx)
    change = facts.get("change", "down")
    note = humanize(ctx.payload.get("season_note", "the seasonal lull"))
    facts["season note"] = note
    facts["expected seasonal"] = "yes" if ctx.payload.get("is_expected_seasonal") else "no"
    if item := ctx.digest(kind="seasonal"):
        facts.update(digest_facts(item, prefix="seasonal insight"))
    members = ctx.aggregate.get("total_active_members")
    focus = f"your {members:,} {ctx.audience}" if members else f"your existing {ctx.audience}"
    return TriggerRead(
        facts=facts,
        hook=f"your {metric} are {change} this week, but this is the expected {note}, not a problem with your listing.",
        proof="Better to hold ad spend now and put the energy into retention.",
        deliverable=f"draft a retention challenge to keep {focus} engaged through the dip",
    )


@reads(TriggerFamily.PERFORMANCE, "milestone_reached")
def read_milestone(ctx: ReadContext) -> TriggerRead:
    metric = humanize(ctx.payload.get("metric", "reviews")).replace("review count", "reviews")
    now, target = ctx.payload.get("value_now"), ctx.payload.get("milestone_value")
    if now is None or target is None:
        views = ctx.merchant.get("performance", {}).get("views")
        return TriggerRead(
            facts={"profile views (30d)": f"{views:,}"} if views else {},
            hook=f"{ctx.business} crossed {views:,} profile views in the last 30 days."
            if views
            else f"{ctx.business} just hit a new milestone on Google.",
            deliverable="turn the milestone into a Google post that thanks your regulars",
        )
    facts = {"metric": metric, "current value": str(now), "milestone": str(target)}
    gap = target - now if isinstance(now, int) and isinstance(target, int) else None
    if gap and gap > 0:
        facts["remaining to milestone"] = str(gap)
        hook = f"you're at {now} {metric}, just {gap} away from {target}."
        deliverable = (
            f"draft a thank-you message asking happy {ctx.audience} for those last {gap} reviews"
        )
    else:
        hook = f"you've crossed {target} {metric}."
        deliverable = "turn the milestone into a Google post that thanks your regulars"
    return TriggerRead(facts=facts, hook=hook, deliverable=deliverable)


@reads(TriggerFamily.REPUTATION, "review_theme_emerged")
def read_review_theme(ctx: ReadContext) -> TriggerRead:
    theme = humanize(ctx.payload.get("theme", "a recurring issue"))
    count = ctx.payload.get("occurrences_30d")
    quote = ctx.payload.get("common_quote", "")
    facts = {
        "theme": theme,
        "mentions in 30 days": str(count or ""),
        "trend": humanize(ctx.payload.get("trend", "")),
        "typical review quote": quote,
    }
    return TriggerRead(
        facts=facts,
        hook=f"{count} reviews in the last 30 days mention {theme}"
        + (f' — "{quote}".' if quote else "."),
        deliverable="draft a public reply for these reviews plus one fix your team can try this week",
    )


@reads(TriggerFamily.REPUTATION, "gbp_unverified")
def read_unverified(ctx: ReadContext) -> TriggerRead:
    uplift = ctx.payload.get("estimated_uplift_pct")
    path = humanize(ctx.payload.get("verification_path", "postcard or phone call"))
    facts = {"verification route": path}
    if uplift:
        facts["estimated visibility uplift once verified"] = pct(uplift)
    return TriggerRead(
        facts=facts,
        hook=f"{ctx.business}'s Google profile is still unverified"
        + (
            f", and verified listings typically see about {pct(uplift)} more visibility."
            if uplift
            else "."
        ),
        deliverable=f"walk you through verification by {path} (about 5 minutes)",
    )


@reads(TriggerFamily.REPUTATION, "competitor_opened")
def read_competitor(ctx: ReadContext) -> TriggerRead:
    name = ctx.payload.get("competitor_name")
    distance = ctx.payload.get("distance_km")
    offer = ctx.payload.get("their_offer")
    facts = {
        "competitor": str(name or ""),
        "distance": f"{distance} km" if distance else "",
        "their offer": str(offer or ""),
        "opened on": nice_date(ctx.payload["opened_date"])
        if ctx.payload.get("opened_date")
        else "",
    }
    if not name:
        return TriggerRead(
            facts=facts,
            hook="a new competitor has opened near you.",
            deliverable="draft a Google post that sharpens what makes you different",
        )
    own = ctx.first_offer()
    where = f" {distance} km from you" if distance else " nearby"
    return TriggerRead(
        facts=facts,
        hook=f"{name} opened{where}" + (f", leading with {offer}." if offer else "."),
        proof=f"You already have {own} to lean on." if own else "",
        deliverable="draft a Google post that puts your strengths and pricing up front this week",
    )


@reads(TriggerFamily.COMMERCIAL, "renewal_due")
def read_renewal(ctx: ReadContext) -> TriggerRead:
    days = ctx.payload.get("days_remaining")
    amount = ctx.payload.get("renewal_amount")
    plan = ctx.payload.get("plan", "")
    facts = {
        "plan": str(plan),
        "days remaining": str(days),
        "renewal amount": rupees(amount) if amount else "",
    }
    return TriggerRead(
        facts=facts,
        hook=f"your {plan} plan renews in {days} days"
        + (f" ({rupees(amount)})." if amount else "."),
        proof=_value_proof(ctx),
        deliverable="share the renewal steps so your listing boosts don't pause",
    )


def _value_proof(ctx: ReadContext) -> str:
    perf = ctx.merchant.get("performance", {})
    if perf.get("views") and perf.get("calls") is not None:
        return f"Last 30 days: {perf['views']:,} profile views and {perf['calls']:,} calls."
    return ""


@reads(TriggerFamily.COMMERCIAL, "winback_eligible")
def read_winback(ctx: ReadContext) -> TriggerRead:
    days = ctx.payload.get("days_since_expiry")
    dip = ctx.payload.get("perf_dip_pct")
    lapsed = ctx.payload.get("lapsed_customers_added_since_expiry")
    facts = {
        "days since subscription expired": str(days),
        "performance change since expiry": signed_pct(dip) if dip is not None else "",
        "customers lapsed since expiry": str(lapsed or ""),
    }
    hook = f"it's been {days} days since your magicpin plan lapsed"
    hook += f", and views are {signed_pct(dip)} since then." if dip is not None else "."
    return TriggerRead(
        facts=facts,
        hook=hook,
        proof=f"{lapsed} of your {ctx.audience} have also gone quiet in that time."
        if lapsed
        else "",
        deliverable=f"reactivate your plan and send a win-back note to those {lapsed} {ctx.audience}"
        if lapsed
        else "reactivate your plan and restart your listing boosts",
    )


@reads(TriggerFamily.COMMERCIAL, "dormant_with_vera")
def read_dormant(ctx: ReadContext) -> TriggerRead:
    days = ctx.payload.get("days_since_last_merchant_message")
    topic = humanize(ctx.payload.get("last_topic", ""))
    item = ctx.digest(kind="trend") or ctx.digest(kind="research")
    facts = {"days since we last spoke": str(days or ""), "last topic": topic, **digest_facts(item)}
    title = (item or {}).get("title")
    return TriggerRead(
        facts=facts,
        hook=(
            f"it's been {days} days since we last spoke"
            if days
            else "it's been a while since we spoke"
        )
        + (f". One thing worth a look this week: {title}." if title else "."),
        deliverable="send you the 2-minute summary and what it means for you",
        cta=CtaType.OPEN_ENDED,
    )


@reads(TriggerFamily.MOMENT, "festival_upcoming")
def read_festival(ctx: ReadContext) -> TriggerRead:
    beats = ctx.category.get("seasonal_beats", [])
    offer = ctx.first_offer()
    festival = ctx.payload.get("festival")
    if not festival:
        beat = beats[0] if beats else {}
        return TriggerRead(
            facts={
                "season window": str(beat.get("month_range", "")),
                "pattern": str(beat.get("note", "")),
                "offer to anchor on": offer,
            },
            hook=f"the {beat.get('month_range', 'coming')} season is close: {beat.get('note', 'demand picks up')}.",
            deliverable=f"draft a seasonal campaign around {offer}"
            if offer
            else "draft a seasonal campaign",
        )
    when = ctx.payload.get("date")
    days = ctx.days_until(when)
    if days is None or days < 0:
        days = ctx.payload.get("days_until")
    facts = {
        "festival": str(festival),
        "date": nice_date(when),
        "days away": str(days or ""),
        "offer to anchor on": offer,
    }
    if beats:
        facts["seasonal pattern"] = str(beats[0]["note"])
    return TriggerRead(
        facts=facts,
        hook=f"{festival} is on {nice_date(when)}" + (f", {days} days out." if days else "."),
        proof=f"Season pattern for your category: {beats[0]['note']}." if beats else "",
        deliverable=f"draft a {festival} campaign around {offer}"
        if offer
        else f"draft a {festival} campaign",
    )


@reads(TriggerFamily.MOMENT, "ipl_match_today")
def read_ipl(ctx: ReadContext) -> TriggerRead:
    match = ctx.payload.get("match", "tonight's match")
    kickoff = ctx.payload.get("match_time_iso")
    time_label = _clock(kickoff)
    weeknight = bool(ctx.payload.get("is_weeknight"))
    item = next((d for d in ctx.category.get("digest", []) if "IPL" in d.get("title", "")), None)
    offer = ctx.first_offer()
    facts = {
        "match": str(match),
        "venue": str(ctx.payload.get("venue", "")),
        "start time": time_label,
        "weeknight match": "yes" if weeknight else "no (weekend)",
        **digest_facts(item, prefix="match-day data"),
    }
    if offer:
        facts["their active offer"] = offer
    hook = f"{match} at {ctx.payload.get('venue', 'the stadium')} tonight, {time_label}."
    if weeknight:
        return TriggerRead(
            facts=facts, hook=hook, deliverable=f"set up a match-night combo around {offer}"
        )
    return TriggerRead(
        facts=facts,
        hook=hook,
        proof=f"Heads-up: {item['summary'].split('.')[0]}." if item else "",
        deliverable=f"push {offer} as a delivery-only special tonight instead of a dine-in promo"
        if offer
        else "set up a delivery-only special for tonight",
    )


def _clock(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%-I:%M%p").lower().replace(":00", "")
    except ValueError:
        return ""


@reads(TriggerFamily.MOMENT, "category_seasonal")
def read_category_seasonal(ctx: ReadContext) -> TriggerRead:
    trends = [_trend(t) for t in ctx.payload.get("trends", [])]
    season = humanize(ctx.payload.get("season", "this season"))
    facts = {"season": season, "demand shifts": "; ".join(trends)}
    if item := ctx.digest(kind="seasonal"):
        facts.update(digest_facts(item, prefix="seasonal insight"))
    return TriggerRead(
        facts=facts,
        hook=f"{season} demand is shifting: {', '.join(trends[:3])}.",
        deliverable="draft a shelf plan and a WhatsApp note for your regulars based on this",
    )


def _trend(raw: str) -> str:
    name, _, change = str(raw).rpartition("_")
    return (
        f"{humanize(name).replace(' demand', '')} {change}%"
        if change[:1] in "+-"
        else humanize(raw)
    )


@reads(TriggerFamily.CONVERSATIONAL, "curious_ask_due")
def read_curious_ask(ctx: ReadContext) -> TriggerRead:
    signal = next(iter(ctx.category.get("trend_signals", [])), None)
    facts = {"ask": humanize(ctx.payload.get("ask_template", "what's in demand this week"))}
    if signal:
        facts["trending search"] = f'"{signal["query"]}" {signed_pct(signal["delta_yoy"])} YoY'
    return TriggerRead(
        facts=facts,
        hook=f"quick one: what's been the most asked-for service at {ctx.business} this week?",
        deliverable="turn your answer into a Google post and a ready WhatsApp reply for price questions",
        closing="I'll turn your answer into a Google post and a ready WhatsApp reply for price "
        "questions. Takes 5 minutes.",
    )


@reads(TriggerFamily.CONVERSATIONAL, "active_planning_intent")
def read_planning(ctx: ReadContext) -> TriggerRead:
    topic = humanize(ctx.payload.get("intent_topic", "the plan"))
    said = ctx.payload.get("merchant_last_message", "")
    facts = {"what they asked about": topic, "their last message": said}
    catalog = [
        o["title"]
        for o in ctx.category.get("offer_catalog", [])
        if o.get("type") != "percentage_discount"
    ][:4]
    if catalog:
        facts["category offer patterns"] = "; ".join(catalog)
    return TriggerRead(
        facts=facts,
        hook=f"picking up on your {topic} idea — I can have a first version ready for you today.",
        deliverable=f"turn this into a ready-to-share {topic} flyer and WhatsApp note",
        cta=CtaType.OPEN_ENDED,
    )


def _slot_labels(slots: list[Payload]) -> tuple[str, ...]:
    return tuple(str(s.get("label")) for s in slots if s.get("label"))


def _slot_closing(options: tuple[str, ...]) -> str:
    picks = ", ".join(f"{i} for {label}" for i, label in enumerate(options, start=1))
    return f"Reply {picks}, or tell us a time that suits you."


@reads(TriggerFamily.CUSTOMER, "recall_due")
def read_recall(ctx: ReadContext) -> TriggerRead:
    recent = ctx.customer.get("relationship", {}).get("services_received") or ["next visit"]
    service = humanize(ctx.payload.get("service_due", recent[-1])).replace("6 month", "6-month")
    options = _slot_labels(ctx.payload.get("available_slots", []))
    offer = next((o for o in active_offers(ctx.merchant) if _mentions(o, service)), "")
    facts = {
        "service due": service,
        "last service": nice_date(ctx.payload.get("last_service_date")),
        "due date": nice_date(ctx.payload.get("due_date")),
        "open slots": "; ".join(options),
        "matching offer": offer,
    }
    elapsed = days_between(ctx.payload.get("last_service_date"), ctx.today)
    since = (
        f"it's been about {round(elapsed / 30)} months since your last visit, so "
        if elapsed and elapsed > 60
        else ""
    )
    return TriggerRead(
        facts=facts,
        hook=f"{since}your {service} is due.",
        proof=f"{offer} as always." if offer else "",
        deliverable="hold a slot for you",
        closing=_slot_closing(options) if options else "Reply YES and we'll hold a slot for you.",
        cta=CtaType.MULTI_CHOICE_SLOT if options else CtaType.BINARY_YES_NO,
        options=options,
    )


def _mentions(offer: str, service: str) -> bool:
    return any(word in offer.lower() for word in service.lower().split() if len(word) > 3)


@reads(TriggerFamily.CUSTOMER, "appointment_tomorrow")
def read_appointment(ctx: ReadContext) -> TriggerRead:
    facts = {
        humanize(k): humanize(v)
        for k, v in ctx.payload.items()
        if k not in {"placeholder", "metric_or_topic"}
    }
    return TriggerRead(
        facts=facts,
        hook="a quick reminder that your appointment with us is tomorrow.",
        deliverable="keep your slot ready",
        closing="Reply YES to confirm, or tell us if another time works better.",
        cta=CtaType.BINARY_YES_NO,
    )


@reads(TriggerFamily.CUSTOMER, "chronic_refill_due")
def read_refill(ctx: ReadContext) -> TriggerRead:
    molecules = ", ".join(humanize(m) for m in ctx.payload.get("molecule_list", []))
    runs_out = ctx.payload.get("stock_runs_out_iso")
    saved = ctx.payload.get("delivery_address_saved") or ctx.customer.get("preferences", {}).get(
        "delivery_address"
    )
    facts = {
        "medicines": molecules,
        "stock runs out": nice_date(runs_out) if runs_out else "",
        "delivery address saved": "yes" if saved else "no",
        "store offers": "; ".join(active_offers(ctx.merchant)),
    }
    what = f"the monthly medicines ({molecules})" if molecules else "the regular refill"
    hook = (
        f"{what} will run out on {nice_date(runs_out)}."
        if runs_out
        else f"{what} is due for a top-up."
    )
    return TriggerRead(
        facts=facts,
        hook=hook,
        proof="Same dose and brand, packed and ready.",
        deliverable="pack and deliver the refill",
        closing="Reply CONFIRM and we'll deliver to your saved address."
        if saved
        else "Reply CONFIRM and we'll keep it ready for pickup.",
        cta=CtaType.BINARY_CONFIRM_CANCEL,
    )


@reads(TriggerFamily.CUSTOMER, "customer_lapsed_hard", "customer_lapsed_soft")
def read_lapsed(ctx: ReadContext) -> TriggerRead:
    days = ctx.payload.get("days_since_last_visit") or days_between(
        ctx.customer.get("relationship", {}).get("last_visit"), ctx.today
    )
    focus = humanize(ctx.payload.get("previous_focus", ""))
    offer = ctx.first_offer()
    facts = {
        "days since last visit": str(days or ""),
        "previous focus": focus,
        "previous membership months": str(ctx.payload.get("previous_membership_months", "")),
        "offer available": offer,
    }
    weeks = (
        f"about {round(days / 7)} weeks"
        if days and days < 120
        else f"about {round(days / 30)} months"
        if days
        else "a while"
    )
    return TriggerRead(
        facts=facts,
        hook=f"it's been {weeks} since your last visit. It happens to everyone, no judgment at all.",
        proof=f"{offer} is running right now"
        + (f" and fits your {focus} goal well." if focus else ".")
        if offer
        else "",
        deliverable="hold a spot for you",
        closing="Reply YES and we'll hold a spot for you. No commitment.",
    )


@reads(TriggerFamily.CUSTOMER, "trial_followup")
def read_trial(ctx: ReadContext) -> TriggerRead:
    options = _slot_labels(ctx.payload.get("next_session_options", []))
    trial = ctx.payload.get("trial_date")
    facts = {
        "trial date": nice_date(trial) if trial else "",
        "next session options": "; ".join(options),
    }
    return TriggerRead(
        facts=facts,
        hook=f"thanks for coming in for the trial on {nice_date(trial)}."
        if trial
        else "thanks for trying us out.",
        deliverable="book your next session",
        closing=_slot_closing(options)
        if options
        else "Reply YES and we'll book your next session.",
        cta=CtaType.MULTI_CHOICE_SLOT if options else CtaType.BINARY_YES_NO,
        options=options,
    )


@reads(TriggerFamily.CUSTOMER, "wedding_package_followup")
def read_wedding(ctx: ReadContext) -> TriggerRead:
    wedding = ctx.payload.get("wedding_date")
    days = ctx.days_until(wedding)
    if days is None or days < 0:
        days = ctx.payload.get("days_to_wedding")
    step = humanize(ctx.payload.get("next_step_window_open", "prep program")).replace(
        "30day", "30-day"
    )
    facts = {
        "wedding date": nice_date(wedding),
        "days to wedding": str(days or ""),
        "next step": step,
        "bridal trial done on": nice_date(ctx.payload.get("trial_completed")),
    }
    return TriggerRead(
        facts=facts,
        hook=f"{days} days to your wedding, and this is the right window to start the {step}.",
        deliverable="block your first session",
        closing="Reply YES and we'll block your first session.",
    )
