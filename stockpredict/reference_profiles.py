"""Explicit candidate references for Taiwan securities, without correlation claims."""

import re
from dataclasses import dataclass

from stockpredict.data import EXAMPLES, SYMBOL_ALIASES, normalize_symbol

TAIWAN_PATTERN = r"^[0-9]{4,6}[A-Z]{0,2}\.(?:TW|TWO)$"
BARE_TAIWAN_PATTERN = r"^[0-9]{4,6}[A-Z]{0,2}$"
FACTOR_LABELS = {
    "UMC": {"zh-TW": "聯電 ADR（UMC）", "en": "UMC ADR (UMC)"},
    "TSM": {"zh-TW": "台積電 ADR（TSM）", "en": "TSMC ADR (TSM)"},
    "SOXX": {"zh-TW": "半導體 ETF（SOXX）", "en": "Semiconductor ETF (SOXX)"},
    "SPY": {"zh-TW": "標普 500 ETF（SPY）", "en": "S&P 500 ETF (SPY)"},
    "QQQ": {"zh-TW": "Nasdaq-100 ETF（QQQ）", "en": "Nasdaq-100 ETF (QQQ)"},
}


@dataclass(frozen=True)
class ReferenceProfile:
    id: str
    symbols: tuple[str, str]
    kind: str


PROFILES = {
    "umc": ReferenceProfile("umc", ("UMC", "SOXX"), "adr_sector"),
    "tsmc": ReferenceProfile("tsmc", ("TSM", "SOXX"), "adr_sector"),
    "taiwan_market": ReferenceProfile("taiwan_market", ("SPY", "QQQ"), "broad_market"),
}
STOCK_PROFILES = {"2303.TW": "umc", "2330.TW": "tsmc"}
FACTOR_PAIRS = frozenset(profile.symbols for profile in PROFILES.values())


def canonical_reference_symbol(symbol: str) -> str:
    value = normalize_symbol(symbol)
    return value + ".TW" if re.fullmatch(BARE_TAIWAN_PATTERN, value) else value


def profile_for(symbol: str) -> ReferenceProfile | None:
    value = canonical_reference_symbol(symbol)
    if not re.fullmatch(TAIWAN_PATTERN, value):
        return None
    return PROFILES[STOCK_PROFILES.get(value, "taiwan_market")]


def profile_payload(profile: ReferenceProfile) -> dict:
    return {
        "id": profile.id,
        "market": "taiwan",
        "symbols": list(profile.symbols),
        "kind": profile.kind,
        "names": {
            language: [FACTOR_LABELS[symbol][language] for symbol in profile.symbols]
            for language in ("zh-TW", "en")
        },
    }


def public_catalog() -> dict:
    return {
        "profiles": {key: profile_payload(profile) for key, profile in PROFILES.items()},
        "stock_profiles": dict(STOCK_PROFILES),
        "symbol_aliases": dict(SYMBOL_ALIASES),
        "demo_symbols": list(EXAMPLES),
        "default_taiwan_profile": "taiwan_market",
        "taiwan_pattern": TAIWAN_PATTERN,
        "bare_taiwan_pattern": BARE_TAIWAN_PATTERN,
    }
