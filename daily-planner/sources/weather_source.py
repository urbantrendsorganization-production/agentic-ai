"""Today's weather via Open-Meteo (free, no API key required)."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

# https://open-meteo.com/en/docs — WMO weather interpretation codes (subset)
_WMO = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def _geocode(city: str) -> tuple[float, float] | None:
    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        return None
    return results[0]["latitude"], results[0]["longitude"]


def gather_weather(city: str, timezone: str = "auto") -> str:
    if not city:
        return ""
    try:
        coords = _geocode(city)
        if not coords:
            return f"Weather: could not locate '{city}'."
        lat, lon = coords
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weathercode",
                "timezone": timezone or "auto",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        d = resp.json()["daily"]
        code = d["weathercode"][0]
        desc = _WMO.get(code, "unknown conditions")
        return (
            f"Weather in {city}: {desc}, "
            f"{d['temperature_2m_min'][0]:.0f}–{d['temperature_2m_max'][0]:.0f}°C, "
            f"{d['precipitation_probability_max'][0]}% chance of precipitation."
        )
    except Exception as exc:  # noqa: BLE001 — sources must never crash the run
        log.warning("weather source failed: %s", exc)
        return f"Weather: unavailable ({exc})."
