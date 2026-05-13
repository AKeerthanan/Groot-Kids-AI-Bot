import csv
import random
import re
from functools import lru_cache
from pathlib import Path


DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "fun_facts.csv"

CATEGORY_ALIASES = {
    "animal": "animals",
    "animals": "animals",
    "space": "space",
    "science": "science",
    "food": "food",
    "fruit": "food",
    "nature": "nature",
    "plant": "nature",
    "plants": "nature",
    "body": "body",
    "human": "body",
    "ocean": "ocean",
    "sea": "ocean",
    "dinosaurs": "dinosaurs",
    "dinosaur": "dinosaurs",
}


def _clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


@lru_cache(maxsize=1)
def load_fun_facts():
    facts = []
    with DATASET_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fact = _clean_text(row.get("fact"))
            category = _clean_text(row.get("category")).lower()
            keywords = _clean_text(row.get("keywords")).lower()
            if fact and category:
                facts.append({
                    "fact": fact,
                    "category": category,
                    "keywords": keywords,
                })
    return facts


def detect_fun_fact_category(message):
    text = (message or "").lower()
    for alias, category in CATEGORY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return category
    return None


def choose_fun_fact(message="", last_fun_fact=None):
    try:
        facts = load_fun_facts()
    except Exception:
        return None

    if not facts:
        return None

    category = detect_fun_fact_category(message)
    candidates = [item for item in facts if item["category"] == category] if category else facts
    if not candidates:
        candidates = facts

    if last_fun_fact and len(candidates) > 1:
        non_repeats = [item for item in candidates if item["fact"] != last_fun_fact]
        if non_repeats:
            candidates = non_repeats

    return random.choice(candidates)


def format_fun_fact(item):
    if not item or not item.get("fact"):
        return "I couldn't find a fun fact right now 😊"
    return f"🌟 Fun fact:\n\n{item['fact']}"
