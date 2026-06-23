from __future__ import annotations

import httpx
from typing import Optional


WEB_CONTEXT_TERMS = (
    "weather",
    "climate",
    "season",
    "humidity",
    "rain",
    "temperature",
    "spray today",
    "best time to spray",
    "wind",
)


def asks_for_web_context(message: str) -> bool:
    normalized = (message or "").casefold()
    return any(term in normalized for term in WEB_CONTEXT_TERMS)


def extract_location_hint(message: str) -> Optional[str]:
    normalized = (message or "").casefold()

    known_locations = {
        "riyadh": "Riyadh, Saudi Arabia",
        "jeddah": "Jeddah, Saudi Arabia",
        "dammam": "Dammam, Saudi Arabia",
        "dubai": "Dubai, United Arab Emirates",
        "cairo": "Cairo, Egypt",
    }

    for key, value in known_locations.items():
        if key in normalized:
            return value

    return None


def get_weather_context(location: str) -> dict:
    if not location:
        return {}

    try:
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": location,
                "count": 1,
                "language": "en",
                "format": "json",
            },
            timeout=3,
        )
        geo.raise_for_status()

        results = geo.json().get("results") or []
        if not results:
            return {}

        place = results[0]
        lat = place["latitude"]
        lon = place["longitude"]

        weather = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,rain,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=3,
        )
        weather.raise_for_status()

        current = weather.json().get("current") or {}

        return {
            "location": location,
            "temperature_c": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "rain": current.get("rain"),
            "wind_speed": current.get("wind_speed_10m"),
            "source": "Open-Meteo",
        }

    except Exception:
        return {}


def format_web_context_for_prompt(context: dict) -> str:
    if not context:
        return ""

    return (
        "External weather context for agronomic timing only:\n"
        f"- Location: {context.get('location')}\n"
        f"- Temperature: {context.get('temperature_c')} C\n"
        f"- Humidity: {context.get('humidity')}%\n"
        f"- Rain: {context.get('rain')} mm\n"
        f"- Wind speed: {context.get('wind_speed')} km/h\n"
        f"- Source: {context.get('source')}\n\n"
        "Use this only for spray timing and weather risk. "
        "Do not use it to invent product names, dosage, prices, or catalog claims."
    )