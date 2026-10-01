"""Heuristic entity extraction for dispute NL (ES/PT) — no LLM required."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

_AMOUNT_PATTERNS = [
    # $45.99 / USD 45,99 / 4948.14 COP / R$120,00
    re.compile(
        r"(?P<sym>R\$|US\$|USD|COP|MXN|ARS|\$)?\s*"
        r"(?P<num>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+(?:[.,]\d{2})?)\s*"
        r"(?P<cur>USD|COP|MXN|ARS|BRL|reales?|pesos?)?",
        re.IGNORECASE,
    ),
]

_DATE_PATTERNS = [
    re.compile(
        r"\b(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{2,4})\b"
    ),
    re.compile(
        r"\b(?P<d>\d{1,2})\s+de\s+"
        r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre|"
        r"janeiro|fevereiro|março|abril|maio|junho|julho|agosto|"
        r"setembro|outubro|novembro|dezembro)"
        r"(?:\s+de\s+(?P<y>\d{4}))?\b",
        re.IGNORECASE,
    ),
]

_TXN_ID = re.compile(r"\b(TRX-[A-Z0-9]+)\b", re.IGNORECASE)
_MERCHANT = re.compile(
    r"(?:(?i:en|em|comercio|com[eé]rcio|merchant|tienda|loja)\s*:?\s+|no(?=\s+[A-ZÁÉÍÓÚÑÜ])\s+)"
    r"([A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü&'-]{2,}"
    r"(?:\s+[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü&']{2,}){0,3})"
)

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_CURRENCY_ALIASES = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "COP": "COP",
    "MXN": "MXN",
    "ARS": "ARS",
    "R$": "BRL",
    "BRL": "BRL",
    "real": "BRL",
    "reales": "BRL",
    "peso": "COP",
    "pesos": "COP",
}


@dataclass
class ExtractedEntities:
    amount: float | None = None
    currency: str | None = None
    transaction_date: str | None = None
    merchant_name: str | None = None
    transaction_id: str | None = None
    language_hint: str | None = None
    missing: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing"] = list(self.missing or [])
        return payload


def _parse_amount_number(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(",", ".") if len(parts[-1]) == 2 else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def detect_language(text: str) -> str | None:
    lowered = text.lower()
    pt_markers = ("não", "nao ", "cobrança", "cobranca", "quero", "preciso", "loja")
    es_markers = ("no reconozco", "quiero", "disputo", "comercio", "cargo")
    pt = sum(1 for m in pt_markers if m in lowered)
    es = sum(1 for m in es_markers if m in lowered)
    if pt > es and pt > 0:
        return "pt"
    if es > 0:
        return "es"
    return None


def extract_entities(text: str) -> ExtractedEntities:
    """Pull amount/currency/date/merchant/txn id from free text."""
    result = ExtractedEntities(language_hint=detect_language(text))

    txn = _TXN_ID.search(text)
    if txn:
        result.transaction_id = txn.group(1).upper()

    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        amount = _parse_amount_number(match.group("num"))
        if amount is None:
            continue
        # Skip pure dates mistaken as amounts (e.g. 12/03) — amounts usually have decimals
        # or currency markers; still accept integers when currency present.
        sym = (match.group("sym") or "").strip()
        cur = (match.group("cur") or "").strip()
        currency = None
        for token in (sym, cur):
            if not token:
                continue
            upper = token.upper()
            lower = token.lower()
            if upper in _CURRENCY_ALIASES:
                currency = _CURRENCY_ALIASES[upper]
                break
            if lower in _CURRENCY_ALIASES:
                currency = _CURRENCY_ALIASES[lower]
                break
            if token == "$":
                currency = "USD"
                break
        if (
            currency is None
            and "." not in match.group("num")
            and "," not in match.group("num")
            and not sym
            and not cur
        ):
            # Likely a day/month fragment; keep searching
            continue
        result.amount = amount
        result.currency = currency
        break

    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        if "month" in groups and groups.get("month"):
            month = _MONTHS.get(groups["month"].lower())
            if not month:
                continue
            day = int(groups["d"])
            year = int(groups["y"]) if groups.get("y") else 2026
            if year < 100:
                year += 2000
            result.transaction_date = f"{year:04d}-{month:02d}-{day:02d}"
            break
        day = int(groups["d"])
        month = int(groups["m"])
        year = int(groups["y"])
        if year < 100:
            year += 2000
        result.transaction_date = f"{year:04d}-{month:02d}-{day:02d}"
        break

    merchant = _MERCHANT.search(text)
    if merchant:
        result.merchant_name = merchant.group(1).strip(" .,;:")

    missing: list[str] = []
    if result.amount is None:
        missing.append("amount")
    if result.transaction_id is None and (
        result.merchant_name is None or result.transaction_date is None
    ):
        missing.append("transaction_ref")
    result.missing = missing
    return result


_CATEGORY_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "Transactions",
        "Cargo no reconocido",
        (
            "no reconozco",
            "não reconheço",
            "nao reconheco",
            "cargo no reconocido",
            "cobrança não reconhecida",
            "fraude",
            "fraud",
            "unrecognized",
        ),
    ),
    (
        "Fees",
        "Cobro indebido",
        ("cobro indebido", "cobrança indevida", "fee", "comisión", "comissao"),
    ),
    (
        "Technical",
        "Problema con app",
        ("app", "aplicación", "aplicativo", "technical", "error técnico"),
    ),
]


def classify_from_text(text: str) -> dict[str, Any]:
    """Lightweight keyword classifier until Tamayo's baseline lands (#10)."""
    lowered = text.lower()
    for category, subcategory, keywords in _CATEGORY_RULES:
        if any(k in lowered for k in keywords):
            return {
                "category": category,
                "subcategory": subcategory,
                "confidence": 0.7,
                "classifier": "rules",
            }
    return {
        "category": "Transactions",
        "subcategory": None,
        "confidence": 0.4,
        "classifier": "rules",
    }
