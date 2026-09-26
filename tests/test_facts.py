from datetime import date

import pytest
from support import Seeds

from vera.compose.composer import Composer
from vera.compose.facts import merchant_salutation, pct, signed_pct
from vera.dialogue.language import Language, customer_language, merchant_language
from vera.store.contexts import ContextBundle

TODAY = date(2026, 4, 26)


def bundle(seeds: Seeds, trigger_id: str) -> ContextBundle:
    trigger = seeds.triggers[trigger_id]
    merchant = seeds.merchants[trigger["merchant_id"]]
    return ContextBundle(
        category=seeds.categories[merchant["category_slug"]],
        merchant=merchant,
        trigger=trigger,
        customer=seeds.customers.get(trigger.get("customer_id") or ""),
    )


@pytest.mark.parametrize(("value", "expected"), [(0.021, "2.1%"), (0.03, "3%"), (0.625, "62.5%")])
def test_pct_formatting(value: float, expected: str) -> None:
    assert pct(value) == expected


def test_signed_pct_keeps_direction() -> None:
    assert signed_pct(-0.5) == "-50%"
    assert signed_pct(0.18) == "+18%"


def test_dentist_salutation_is_not_doubled(seeds: Seeds) -> None:
    dentists = seeds.categories["dentists"]
    meera = seeds.merchants["m_001_drmeera_dentist_delhi"]
    already_titled = {**meera, "identity": {**meera["identity"], "owner_first_name": "Dr. Rajan"}}
    assert merchant_salutation(meera, dentists) == "Dr. Meera"
    assert merchant_salutation(already_titled, dentists) == "Dr. Rajan"


def test_language_follows_merchant_and_customer(seeds: Seeds) -> None:
    meera = seeds.merchants["m_001_drmeera_dentist_delhi"]
    gym = seeds.merchants["m_008_zenyoga_gym_chennai"]
    assert merchant_language(meera, seeds.categories["dentists"]) is Language.HINGLISH
    assert merchant_language(gym, seeds.categories["gyms"]) is Language.ENGLISH
    assert customer_language(seeds.customers["c_001_priya_for_m001"]) is Language.HINGLISH
    assert customer_language(seeds.customers["c_002_rohit_for_m001"]) is Language.ENGLISH


def test_research_sheet_carries_verifiable_anchors(seeds: Seeds) -> None:
    plan = Composer(None).plan(bundle(seeds, "trg_001_research_digest_dentists"), TODAY)
    facts = plan.sheet.facts
    assert facts["item source"] == "JIDA Oct 2026, p.14"
    assert facts["item sample size"] == "2,100 patients"
    assert facts["matching patients in their roster"] == "124"
    assert "CTR 2.1%" in facts["last 30 days"]
    assert {2100.0, 124.0, 38.0} <= plan.sheet.allowed_numbers()


def test_customer_sheet_hides_merchant_performance(seeds: Seeds) -> None:
    plan = Composer(None).plan(bundle(seeds, "trg_003_recall_due_priya"), TODAY)
    assert plan.sheet.customer_facing
    assert plan.sheet.speaker == "Dr. Meera's Dental Clinic"
    assert plan.sheet.salutation == "Priya"
    assert "last 30 days" not in plan.sheet.facts
    assert plan.read.options == ("Wed 5 Nov, 6pm", "Thu 6 Nov, 5pm")


def test_guardian_is_addressed_for_child_patients(seeds: Seeds) -> None:
    aanya = seeds.customers["c_003_aanya_for_m001"]
    trigger = {**seeds.triggers["trg_003_recall_due_priya"], "customer_id": aanya["customer_id"]}
    sheet = (
        Composer(None)
        .plan(
            ContextBundle(
                seeds.categories["dentists"],
                seeds.merchants["m_001_drmeera_dentist_delhi"],
                trigger,
                aanya,
            ),
            TODAY,
        )
        .sheet
    )
    assert sheet.salutation == "Sneha"
    assert sheet.facts["customer"] == "Aanya"


def test_weekend_ipl_match_recommends_delivery(seeds: Seeds) -> None:
    plan = Composer(None).plan(bundle(seeds, "trg_010_ipl_match_delhi"), TODAY)
    assert "delivery-only" in plan.read.deliverable
    assert "12%" in plan.read.proof


def test_every_seed_trigger_has_a_grounded_fallback(seeds: Seeds) -> None:
    composer = Composer(None)
    for trigger_id in seeds.triggers:
        message = composer.fallback(composer.plan(bundle(seeds, trigger_id), TODAY))
        assert message.body
        assert "None" not in message.body
        assert "  " not in message.body
