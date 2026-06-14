"""
evaluation/build_logistics_eval.py
──────────────────────────────────
Convert the real after-sales/logistics conversations (cat3) into a structured
evaluation set for the Phase-2 evaluation harness (Proposal slide 8).

Each conversation becomes one eval case:
    {
      "id": "log-001",
      "category": "logistics",
      "conversation": [...all turns except the final assistant reply...],
      "reference_answer": "<the human agent's final reply>",
      "expected_intent": "logistics",
      "should_escalate": <bool, from our own SafetyInterceptor>,
      "expected_tool": "lookup_order | initiate_refund | request_invoice | null"
    }

Run:
    python -m evaluation.build_logistics_eval
Output:
    evaluation/logistics_eval.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path

from safety.interceptor import SafetyInterceptor

_SRC = Path("tra/aftersales_logistic/cat3_aftersales_logistics_real_en.jsonl")
_OUT = Path("evaluation/logistics_eval.jsonl")

_interceptor = SafetyInterceptor()


def classify_expected_tool(conversation: list[dict]) -> str | None:
    """
    Decide which TOOL the agent *should* call for this conversation — this is
    the ground truth for the "tool-selection accuracy" metric.

    Returns one of: "lookup_order", "initiate_refund", "request_invoice", or
    None (a plain Q&A that needs no tool).

    TODO(team): refine these rules with your domain knowledge of what farmers
    actually ask. Below is a simple keyword baseline to get the harness running.
    Consider: which phrasings signal a refund vs. a tracking question? Does
    "where is my package" differ from "I want my money back"? Edit freely.
    """
    text = " ".join(m["content"].lower() for m in conversation if m["role"] == "user")

    if any(w in text for w in ("refund", "return", "money back", "broken", "leak", "damaged")):
        return "initiate_refund"
    if any(w in text for w in ("invoice", "receipt", "vat")):
        return "request_invoice"
    if any(w in text for w in ("track", "courier", "shipped", "delivery", "where is", "package", "arrive")):
        return "lookup_order"
    return None


def build() -> int:
    if not _SRC.exists():
        print(f"❌ Source not found: {_SRC}")
        return 0

    conversations = [json.loads(line) for line in _SRC.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases: list[dict] = []

    for i, conv in enumerate(conversations, start=1):
        messages = conv["messages"]
        # Need a conversation that ends with the human agent's reply to use as reference.
        if messages[-1]["role"] != "assistant":
            continue

        context = messages[:-1]
        reference = messages[-1]["content"]

        # Reuse our OWN interceptor so the eval set's escalation labels match
        # exactly how the live system would classify the same text.
        user_text = " ".join(m["content"] for m in context if m["role"] == "user")
        should_escalate = not _interceptor.check(user_text).is_safe

        cases.append({
            "id": f"log-{i:03d}",
            "category": "logistics",
            "conversation": context,
            "reference_answer": reference,
            "expected_intent": "logistics",
            "should_escalate": should_escalate,
            "expected_tool": classify_expected_tool(context),
        })

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with _OUT.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    # Quick distribution summary
    from collections import Counter
    tools = Counter(c["expected_tool"] for c in cases)
    print(f"✅ Wrote {len(cases)} eval cases → {_OUT}")
    print(f"   Tool distribution: {dict(tools)}")
    print(f"   Should-escalate cases: {sum(c['should_escalate'] for c in cases)}")
    return len(cases)


if __name__ == "__main__":
    build()
