"""
safety/interceptor.py
─────────────────────
Stage 1 Safety Intercept — scans every user message BEFORE any LLM call.

Patterns drawn from real safety-sensitive conversations in:
  tra/safety_sensitive/cat4_safety_sensitive_real_en.jsonl
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Keyword groups (any match in a group triggers that category) ───────────────

_SELF_HARM_KEYWORDS: list[str] = [
    "want to die", "want to drink", "drink it myself", "drink the pesticide",
    "drink this medicine", "drink poison", "poison myself", "kill myself",
    "suicide", "self harm", "no meaning to live", "life has no meaning",
    "don't want to live", "life is over", "end my life", "harm myself",
    "take my own life", "overdose on", "lethal dose", "fatal dose",
    "life doesn't have meaning", "thought about jumping", "thought about dying",
    "want to jump", "wanna die", "i want to die", "i wanna die",
    "no reason to live", "thinking of ending", "want it all to end",
]

_INTENTIONAL_INGESTION_KEYWORDS: list[str] = [
    "buy it to drink", "drink it to die", "swallow the pesticide",
    "ingest the chemical", "consume the pesticide", "eat the pesticide",
    "drink herbicide", "drink insecticide", "drink fungicide",
    "ship it to drink", "will it kill if consumed", "will it kill a person",
    "will a person die", "lethal if swallowed", "what happens if drunk",
    "how much to drink to die", "drink enough to",
]

_ANIMAL_POISONING_KEYWORDS: list[str] = [
    "poison my neighbor", "poison someone", "poison a person",
    "use it to kill a person", "kill a human", "harm a person",
    "put it in food", "add it to water", "contaminate the food",
    "spike the drink", "mix with food to poison",
]

_CROP_BURN_COMBO_RISK: list[str] = [
    "mix bleach with pesticide", "mix ammonia with pesticide",
    "combine acids with", "caustic soda and pesticide",
    "explosive combination", "dangerous mix",
]

# ── Regex patterns ─────────────────────────────────────────────────────────────
_REGEX_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bi\s+want\s+to\s+(die|kill|end)\b", re.I),
    re.compile(r"\bdrink\s+(it|this|the\s+\w+)?\s*(pesticide|medicine|chemical|herbicide|insecticide|fungicide)\b", re.I),
    re.compile(r"\b(suicide|suicidal)\b", re.I),
    re.compile(r"\b(swallow|ingest|consume|eat)\s+(pesticide|chemical|poison|herbicide)\b", re.I),
    re.compile(r"\blife\s+(has\s+no|is\s+meaningless|is\s+over|doesn.t\s+have)\s+meaning\b", re.I),
    re.compile(r"\bwant\s+to\s+(jump|jump\s+off|end\s+it)\b", re.I),
    re.compile(r"\bdon.t\s+want\s+to\s+live\b", re.I),
    re.compile(r"\bno\s+reason\s+to\s+live\b", re.I),
    re.compile(r"\bthought\s+about\s+(dying|jumping|ending)\b", re.I),
    re.compile(r"\bpoison\s+(a\s+person|someone|my\s+neighbor|humans?)\b", re.I),
]


@dataclass
class SafetyResult:
    is_safe: bool
    risk_category: str = ""
    triggered_phrase: str = ""
    human_summary_brief: str = ""

    @property
    def escalate_human_required(self) -> bool:
        """True whenever a safety risk is detected."""
        return not self.is_safe


class SafetyInterceptor:
    """
    Stateless safety scanner. Call .check(text) before every LLM invocation.
    Returns a SafetyResult with is_safe=False if any risk is detected.
    """

    def check(self, text: str) -> SafetyResult:
        text_lower = text.lower()

        # 1. Keyword scan
        for phrase in _SELF_HARM_KEYWORDS:
            if phrase in text_lower:
                return self._build_result("self_harm_or_suicide", phrase, text)

        for phrase in _INTENTIONAL_INGESTION_KEYWORDS:
            if phrase in text_lower:
                return self._build_result("intentional_pesticide_ingestion", phrase, text)

        for phrase in _ANIMAL_POISONING_KEYWORDS:
            if phrase in text_lower:
                return self._build_result("intentional_poisoning_of_others", phrase, text)

        for phrase in _CROP_BURN_COMBO_RISK:
            if phrase in text_lower:
                return self._build_result("dangerous_chemical_combination", phrase, text)

        # 2. Regex scan
        for pattern in _REGEX_PATTERNS:
            m = pattern.search(text)
            if m:
                return self._build_result("self_harm_or_suicide", m.group(0), text)

        return SafetyResult(is_safe=True)

    @staticmethod
    def _build_result(category: str, phrase: str, original_text: str) -> SafetyResult:
        brief = (
            f"⚠️ SAFETY ALERT — Category: {category}\n"
            f"Triggered phrase: \"{phrase}\"\n"
            f"Customer message (truncated): {original_text[:300]}\n"
            f"Action required: Immediate human agronomist or counselor response."
        )
        return SafetyResult(
            is_safe=False,
            risk_category=category,
            triggered_phrase=phrase,
            human_summary_brief=brief,
        )
