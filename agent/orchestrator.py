"""
agent/orchestrator.py
─────────────────────
AgroMindAgent — single-agent, multimodal, 4-stage pipeline.
Powered by OpenAI gpt-4o (text + vision).

Stage 1 → Safety Intercept  (pre-LLM, keyword/regex)
Stage 2 → Intent Classification  (OpenAI call)
Stage 3 → Branch Handler  (diagnosis | logistics | product_rec | general_qa)
Stage 4 → Memory Write  (async, non-blocking)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI

from safety.interceptor import SafetyInterceptor
from memory.customer_memory import CustomerMemory
from rag.catalog_loader import search_catalog, all_products_summary, get_product_by_id
from agent.prompts import (
    SYSTEM_PROMPT,
    INTENT_PROMPT,
    LOGISTICS_PROMPT,
    DIAGNOSIS_TEXT_PROMPT,
    DIAGNOSIS_VISION_PROMPT,
    PRODUCT_RECOMMENDATION_PROMPT,
    GENERAL_QA_PROMPT,
    FEW_SHOT_EXAMPLES,
    ALLOWED_CROPS,
)

logger = logging.getLogger("agro_mind")

# ── OpenAI configuration ───────────────────────────────────────────────────────
_API_KEY = os.getenv("OPENAI_API_KEY", "")
_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o")

_client = OpenAI(api_key=_API_KEY) if _API_KEY else None


# ── Response contract ──────────────────────────────────────────────────────────

@dataclass
class AgentResponse:
    intent: str
    safety_risk_detected: bool
    escalate_human: bool
    response_text: str
    recommended_product_id: Optional[str] = None
    group_purchase_triggered: bool = False
    human_summary_brief: Optional[str] = None
    matched_products: list[dict] = field(default_factory=list)
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "safety_risk_detected": self.safety_risk_detected,
            "escalate_human": self.escalate_human,
            "response_text": self.response_text,
            "recommended_product_id": self.recommended_product_id,
            "group_purchase_triggered": self.group_purchase_triggered,
            "human_summary_brief": self.human_summary_brief,
            "matched_products": self.matched_products,
            "session_id": self.session_id,
        }


# ── Canned responses ───────────────────────────────────────────────────────────

def _off_topic_response(session_id: str) -> AgentResponse:
    return AgentResponse(
        intent="diagnosis",
        safety_risk_detected=False,
        escalate_human=False,
        response_text=(
            "Dear customer, I'm here to help! However, I can only analyze crops "
            "in our supported catalog (Citrus, Rice, Tomatoes, Onions, Ginger, Garlic, "
            "Cruciferous Vegetables, Strawberries, Peppers, Cucumbers, and more). "
            "Please send a clear photo of your crop and I'll be happy to assist!"
        ),
        session_id=session_id,
    )


def _zero_guess_response(session_id: str) -> AgentResponse:
    return AgentResponse(
        intent="diagnosis",
        safety_risk_detected=False,
        escalate_human=True,
        response_text=(
            "We do not have a verified matching product or diagnosis for this specific "
            "crop context. Escalating to a human expert."
        ),
        human_summary_brief="Low-confidence diagnosis or no matching product found. Agronomist review required.",
        session_id=session_id,
    )


def _safety_response(safety_result, session_id: str) -> AgentResponse:
    return AgentResponse(
        intent="safety_escalation",
        safety_risk_detected=True,
        escalate_human=True,
        response_text=(
            "Dear customer, your safety and life are of utmost importance. "
            "Automated support has been stopped to protect your health. "
            "A human expert has been alerted to assist you immediately. "
            "Please know that you are not alone — help is on the way. "
            "If you are in immediate danger, please call your local emergency services."
        ),
        human_summary_brief=safety_result.human_summary_brief,
        session_id=session_id,
    )


# ── JSON extraction helper ─────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract a JSON object from an OpenAI response that may include markdown fences."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from response: {text[:300]}")


# ── OpenAI call helpers ────────────────────────────────────────────────────────

async def _openai_chat(messages: list[dict], temperature: float = 0.3) -> str:
    """Async wrapper around the synchronous OpenAI client."""
    loop = asyncio.get_event_loop()

    def _call():
        response = _client.chat.completions.create(
            model=_MODEL_NAME,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    return await loop.run_in_executor(None, _call)


async def _openai_chat_vision(
    system_prompt: str, user_text: str, image_bytes: bytes, temperature: float = 0.3
) -> str:
    """Async wrapper for vision (image + text) OpenAI call."""
    loop = asyncio.get_event_loop()
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    def _call():
        response = _client.chat.completions.create(
            model=_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                        },
                    ],
                },
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    return await loop.run_in_executor(None, _call)


# ── Main Agent ─────────────────────────────────────────────────────────────────

class AgroMindAgent:
    """
    Single-agent multimodal customer support system powered by OpenAI gpt-4o.
    """

    def __init__(self) -> None:
        self._interceptor = SafetyInterceptor()
        self._catalog_summary = all_products_summary()

        if not _client:
            logger.warning("⚠️  OPENAI_API_KEY not set — agent will return errors for LLM calls.")

        logger.info("🌿 AgroMindAgent initialized | model=%s", _MODEL_NAME)

    # ── Public entry point ─────────────────────────────────────────────────────

    async def run(
        self,
        session_id: str,
        user_text: str,
        image_bytes: Optional[bytes] = None,
        order_id: Optional[str] = None,
    ) -> AgentResponse:
        mem = CustomerMemory(session_id)
        mem.append_turn("user", user_text)
        memory_ctx = mem.get_context_string()

        # ── Stage 1: Safety Intercept ─────────────────────────────────────────
        safety_result = self._interceptor.check(user_text)
        if not safety_result.is_safe:
            logger.warning("Safety flag [%s]: %s", safety_result.risk_category, safety_result.triggered_phrase)
            response = _safety_response(safety_result, session_id)
            mem.append_turn("assistant", response.response_text)
            mem.update(last_intent="safety_escalation")
            return response

        # ── Stage 2: Intent Classification ────────────────────────────────────
        intent = await self._classify_intent(user_text, image_bytes)
        logger.info("Intent classified: %s", intent)

        # ── Stage 3: Branch routing ───────────────────────────────────────────
        try:
            if intent == "diagnosis" or (image_bytes is not None):
                response = await self._handle_diagnosis(user_text, image_bytes, memory_ctx, session_id)
            elif intent == "logistics":
                response = await self._handle_logistics(user_text, memory_ctx, order_id, session_id)
            elif intent == "product_recommendation":
                response = await self._handle_product_recommendation(user_text, memory_ctx, session_id)
            else:
                response = await self._handle_general_qa(user_text, memory_ctx, session_id)

        except Exception as exc:
            logger.error("Agent error: %s", exc, exc_info=True)
            response = AgentResponse(
                intent="general_qa",
                safety_risk_detected=False,
                escalate_human=False,
                response_text=(
                    "Dear customer, I'm here! I'm experiencing a technical issue right now. "
                    f"Error: {str(exc)[:200]}. "
                    "Please try again in a moment, or contact our human support team."
                ),
                session_id=session_id,
            )

        # ── Stage 4: Memory write ─────────────────────────────────────────────
        asyncio.create_task(self._async_memory_update(mem, response, user_text))

        mem.append_turn("assistant", response.response_text)
        response.session_id = session_id
        return response

    # ── Stage 2: Intent Classification ────────────────────────────────────────

    async def _classify_intent(self, user_text: str, image_bytes: Optional[bytes]) -> str:
        if image_bytes:
            return "diagnosis"

        if not _client:
            return "general_qa"

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an intent classifier. Respond with exactly ONE word from this list: "
                        "diagnosis, logistics, product_recommendation, general_qa. "
                        "- diagnosis: crop disease, pest, leaf symptoms, plant image\n"
                        "- logistics: shipping, order, refund, return, invoice, delivery\n"
                        "- product_recommendation: which product to use for pest/disease\n"
                        "- general_qa: anything else"
                    ),
                },
                {"role": "user", "content": user_text},
            ]
            # For classification, don't force JSON response format
            loop = asyncio.get_event_loop()

            def _call():
                r = _client.chat.completions.create(
                    model=_MODEL_NAME,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=10,
                )
                return r.choices[0].message.content.strip().lower()

            result = await loop.run_in_executor(None, _call)

            for label in ("diagnosis", "logistics", "product_recommendation", "general_qa"):
                if label in result:
                    return label
        except Exception as exc:
            logger.warning("Intent classification failed: %s", exc)

        return "general_qa"

    # ── Stage 3a: Diagnosis ────────────────────────────────────────────────────

    async def _handle_diagnosis(
        self, user_text: str, image_bytes: Optional[bytes], memory_ctx: str, session_id: str
    ) -> AgentResponse:
        system = (
            SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n"
            + DIAGNOSIS_VISION_PROMPT.format(
                message=user_text or "(No additional text)",
                memory_context=memory_ctx or "No prior context.",
                catalog_summary=self._catalog_summary,
            )
        ) if image_bytes else (
            SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n"
            + DIAGNOSIS_TEXT_PROMPT.format(
                message=user_text,
                memory_context=memory_ctx or "No prior context.",
                catalog_summary=self._catalog_summary,
            )
        )

        if image_bytes:
            raw = await _openai_chat_vision(system, user_text or "Analyze this crop image.", image_bytes)
        else:
            raw = await _openai_chat([
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ])

        return self._parse_response(raw, "diagnosis", session_id)

    # ── Stage 3b: Logistics ────────────────────────────────────────────────────

    async def _handle_logistics(
        self, user_text: str, memory_ctx: str, order_id: Optional[str], session_id: str
    ) -> AgentResponse:
        order_ctx = f"Order ID: {order_id}" if order_id else "No order ID provided."
        system = (
            SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n"
            + LOGISTICS_PROMPT.format(
                message=user_text,
                memory_context=memory_ctx or "No prior context.",
                order_context=order_ctx,
            )
        )
        raw = await _openai_chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ])
        return self._parse_response(raw, "logistics", session_id)

    # ── Stage 3c: Product Recommendation ──────────────────────────────────────

    async def _handle_product_recommendation(
        self, user_text: str, memory_ctx: str, session_id: str
    ) -> AgentResponse:
        matched = search_catalog(user_text, max_results=3)
        matched_text = (
            "\n\n".join(r.summary() for r in matched) if matched else "NO PRODUCTS FOUND"
        )
        system = (
            SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n"
            + PRODUCT_RECOMMENDATION_PROMPT.format(
                message=user_text,
                memory_context=memory_ctx or "No prior context.",
                matched_products=matched_text,
            )
        )
        raw = await _openai_chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ])
        resp = self._parse_response(raw, "product_recommendation", session_id)
        resp.matched_products = [r.to_dict() for r in matched]
        if matched and not resp.recommended_product_id:
            resp.recommended_product_id = matched[0].product_id
        if resp.recommended_product_id:
            resp.group_purchase_triggered = True
        return resp

    # ── Stage 3d: General QA ──────────────────────────────────────────────────

    async def _handle_general_qa(
        self, user_text: str, memory_ctx: str, session_id: str
    ) -> AgentResponse:
        system = (
            SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES + "\n\n"
            + GENERAL_QA_PROMPT.format(
                message=user_text,
                memory_context=memory_ctx or "No prior context.",
            )
        )
        raw = await _openai_chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ])
        return self._parse_response(raw, "general_qa", session_id)

    # ── JSON response parser ───────────────────────────────────────────────────

    def _parse_response(self, raw: str, fallback_intent: str, session_id: str) -> AgentResponse:
        try:
            data = _extract_json(raw)
        except ValueError:
            logger.warning("JSON parse failed, using raw text as response_text")
            data = {}

        return AgentResponse(
            intent=data.get("intent", fallback_intent),
            safety_risk_detected=bool(data.get("safety_risk_detected", False)),
            escalate_human=bool(data.get("escalate_human", False)),
            response_text=data.get("response_text", raw),
            recommended_product_id=data.get("recommended_product_id") or None,
            group_purchase_triggered=bool(data.get("group_purchase_triggered", False)),
            human_summary_brief=data.get("human_summary_brief") or None,
            session_id=session_id,
        )

    # ── Stage 4: Async memory update ──────────────────────────────────────────

    @staticmethod
    async def _async_memory_update(
        mem: CustomerMemory, response: AgentResponse, user_text: str
    ) -> None:
        try:
            user_lower = user_text.lower()
            detected_crop = None
            for crop in ALLOWED_CROPS:
                if crop in user_lower:
                    detected_crop = crop
                    break

            mem.update(
                crop_type=detected_crop,
                last_product_id=response.recommended_product_id,
                last_intent=response.intent,
                infestation_note=(
                    f"{response.intent}: {user_text[:120]}"
                    if response.intent == "diagnosis"
                    else None
                ),
            )
        except Exception as exc:
            logger.debug("Memory update failed (non-fatal): %s", exc)
