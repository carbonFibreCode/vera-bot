import re
from enum import StrEnum
from typing import Any


class Language(StrEnum):
    ENGLISH = "english"
    HINGLISH = "hinglish"
    HINDI = "hindi"


HINDI_MARKERS = frozenset(
    """
    aap aapka aapke aapki apke hai hain hoon kya karein karna karo kar kijiye chahiye abhi nahi
    nahin haan ji mein main hum humein bhi toh liye wala wali accha acha theek thik bataiye batao
    chaliye dekhiye kal aaj ho gaya raha rahi bahut shukriya
    """.split()
)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_WORD = re.compile(r"[a-zA-Z]+")


def detect_language(text: str) -> Language:
    if _DEVANAGARI.search(text):
        return Language.HINDI
    words = [w.casefold() for w in _WORD.findall(text)]
    hits = sum(w in HINDI_MARKERS for w in words)
    if hits >= 2 or (words and hits / len(words) > 0.25):
        return Language.HINGLISH
    return Language.ENGLISH


def merchant_language(merchant: dict[str, Any], category: dict[str, Any]) -> Language:
    languages = merchant.get("identity", {}).get("languages", [])
    code_mix = category.get("voice", {}).get("code_mix", "")
    if "hi" in languages and code_mix.startswith("hindi_english"):
        return Language.HINGLISH
    return Language.ENGLISH


def customer_language(customer: dict[str, Any]) -> Language:
    preference = str(customer.get("identity", {}).get("language_pref", "")).casefold()
    if preference == "hi":
        return Language.HINDI
    if preference.startswith("hi"):
        return Language.HINGLISH
    return Language.ENGLISH


def has_hindi_flavour(text: str) -> bool:
    return detect_language(text) is not Language.ENGLISH
