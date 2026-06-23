from __future__ import annotations

import json
from pathlib import Path

from agent.tools import classify_intent


INTENT_MAP = {
    None: "general_qa",
    "General": "general_qa",
    "Diagnosis": "diagnosis",
    "Product": "product",
    "Usage": "usage",
    "Logistics": "logistics",
    "Safety": "safety",
}


def normalize_intent(intent) -> str:
    raw = str(intent or "general_qa").strip()
    return INTENT_MAP.get(raw, raw.lower())


def load_cases(path: str = "evaluation/golden_cases.jsonl") -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    cases = load_cases()
    passed = 0
    total = 0

    for case in cases:
        expected = case.get("expected_intent")
        if not expected:
            continue

        total += 1

        # classify_intent is a LangChain tool, so use invoke
        actual_raw = classify_intent.invoke(case["message"])
        actual = normalize_intent(actual_raw)

        ok = actual == expected

        if ok:
            passed += 1
            print(f"PASS {case['id']}")
        else:
            print(f"FAIL {case['id']}")
            print(f"  message:  {case['message']}")
            print(f"  expected: {expected}")
            print(f"  actual:   {actual}")

    print()
    print(f"Intent Score: {passed}/{total} = {(passed / total * 100 if total else 0):.1f}%")


if __name__ == "__main__":
    main()