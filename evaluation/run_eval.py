from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent.orchestrator import AgroMindAgent


def normalize_intent(intent: Any) -> str:
    raw = str(intent or "general_qa").strip().lower()
    return {
        "general": "general_qa",
        "generalqa": "general_qa",
        "product_recommendation": "product",
    }.get(raw, raw)


def load_cases(path: str = "evaluation/golden_cases.jsonl") -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def contains_any(text: str, phrases: list[str]) -> bool:
    lowered = text.casefold()
    return any(str(phrase).casefold() in lowered for phrase in phrases)


def check_case(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    expected_intent = case.get("expected_intent")
    if expected_intent:
        actual_intent = normalize_intent(result.get("intent"))
        if actual_intent != expected_intent:
            failures.append(f"intent expected={expected_intent}, actual={actual_intent}")

    if case.get("expected_escalate") is not None:
        if bool(result.get("escalate_human")) != bool(case["expected_escalate"]):
            failures.append(
                f"escalate expected={case['expected_escalate']}, actual={result.get('escalate_human')}"
            )

    if case.get("expected_escalation_type") is not None:
        actual_type = result.get("escalation_type")
        if actual_type != case["expected_escalation_type"]:
            failures.append(
                f"escalation_type expected={case['expected_escalation_type']}, actual={actual_type}"
            )

    if case.get("expected_priority") is not None:
        actual_priority = result.get("escalation_priority")
        if actual_priority != case["expected_priority"]:
            failures.append(
                f"priority expected={case['expected_priority']}, actual={actual_priority}"
            )

    # Optional: this will only be checked if your AgentResponse includes safety_type.
    if case.get("expected_safety_type") is not None and "safety_type" in result:
        actual_safety_type = result.get("safety_type")
        if actual_safety_type != case["expected_safety_type"]:
            failures.append(
                f"safety_type expected={case['expected_safety_type']}, actual={actual_safety_type}"
            )

    text = str(result.get("response_text") or "")

    for phrase in case.get("must_contain", []):
        if str(phrase).casefold() not in text.casefold():
            failures.append(f"missing required phrase: {phrase}")

    if case.get("must_contain_any"):
        if not contains_any(text, case["must_contain_any"]):
            failures.append(f"missing one of required phrases: {case['must_contain_any']}")

    for phrase in case.get("must_not_contain", []):
        if str(phrase).casefold() in text.casefold():
            failures.append(f"forbidden phrase found: {phrase}")

    return failures


async def run_case(agent: AgroMindAgent, case: dict[str, Any]) -> dict[str, Any]:
    response = await agent.run(
        session_id=f"eval-{case['id']}",
        user_text=case["message"],
    )

    result = response.to_dict()
    failures = check_case(case, result)

    return {
        "id": case["id"],
        "category": case.get("category"),
        "passed": not failures,
        "failures": failures,
        "result": result,
    }


async def main() -> None:
    cases = load_cases()
    agent = AgroMindAgent()

    results = []
    for case in cases:
        try:
            results.append(await run_case(agent, case))
        except Exception as exc:
            results.append({
                "id": case["id"],
                "category": case.get("category"),
                "passed": False,
                "failures": [f"runtime error: {exc}"],
                "result": {},
            })

    passed = sum(1 for item in results if item["passed"])
    total = len(results)

    print()
    print(f"Final Eval Score: {passed}/{total} = {(passed / total * 100 if total else 0):.1f}%")
    print()

    by_category: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_category.setdefault(item.get("category") or "uncategorized", []).append(item)

    for category, items in by_category.items():
        category_passed = sum(1 for item in items if item["passed"])
        print(f"{category}: {category_passed}/{len(items)}")

    print()

    for item in results:
        if item["passed"]:
            print(f"PASS {item['id']}")
            continue

        print(f"FAIL {item['id']}")
        for failure in item["failures"]:
            print(f"  - {failure}")

        response_text = str(item.get("result", {}).get("response_text") or "")
        if response_text:
            print(f"  response: {response_text[:300]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
