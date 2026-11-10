"""Item categories used to keep matching within the same kind of object.

The vision model gives every item one category, from its photo when it has one, else
from its description. Two items whose categories are known and different never match;
"other" (unsure) is compatible with everything, so a doubtful label never hides a match.
"""

from __future__ import annotations

import re

OTHER = "other"
CATEGORIES = (
    "wallet", "phone", "computer", "audio", "electronics", "keys", "card", "bag", "bottle",
    "umbrella", "clothing", "eyewear", "jewellery", "stationery", OTHER,
)
PROMPT = (
    "Classify this lost-and-found item into exactly one category: wallet (wallet, purse, card "
    "holder), phone (phone, phone case), computer (laptop, tablet), audio (earbuds, headphones, "
    "their cases), electronics (charger, cable, power bank, calculator, camera), keys, card (ID, "
    "student, bank or transit card), bag (backpack, handbag, tote, pouch, lunch bag), bottle "
    "(water bottle, flask, tumbler, mug), umbrella, clothing (jacket, hoodie, hat, scarf, gloves, "
    "shoes), eyewear (glasses, sunglasses, glasses case), jewellery (watch, ring, bracelet, "
    "necklace), stationery (book, notebook, pen, pencil case, documents), other. "
    "Reply with the category name only."
)


def parse(reply: str) -> str:
    """The first category named in the model's reply, else "other"."""
    return next((w for w in re.findall(r"[a-z]+", (reply or "").lower()) if w in CATEGORIES), OTHER)


def compatible(a: str | None, b: str | None) -> bool:
    """False only when both categories are known and differ."""
    return a in (None, OTHER) or b in (None, OTHER) or a == b
