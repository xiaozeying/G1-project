from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


WTTR_TIMEOUT_S = 8.0
WTTR_USER_AGENT = "interrupt-agent/1.0"
LANGUAGE_ALIASES = {
    "zh-CN": "zh-cn",
    "zh-YUE": "zh-cn",
    "en": "en",
}


@dataclass
class WeatherResult:
    ok: bool
    summary: str
    raw_text: str
    error: str = ""


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": WTTR_USER_AGENT})
    with urlopen(request, timeout=WTTR_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def query_weather(location: str, *, language: str = "zh-CN") -> WeatherResult:
    normalized = (location or "").strip()
    if not normalized:
        normalized = "广州"

    wttr_language = LANGUAGE_ALIASES.get(language, "zh-cn")
    url = f"https://wttr.in/{quote(normalized)}?format=j1&lang={wttr_language}"
    try:
        payload = _fetch_json(url)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return WeatherResult(
            ok=False,
            summary="",
            raw_text="",
            error=str(exc),
        )

    current = (payload.get("current_condition") or [{}])[0]
    today = (payload.get("weather") or [{}])[0]
    if wttr_language == "en":
        desc_items = current.get("weatherDesc") or [{}]
    else:
        desc_items = current.get("lang_zh") or current.get("weatherDesc") or [{}]
    desc = (desc_items[0] or {}).get("value", "").strip() if desc_items else ""
    temp_c = str(current.get("temp_C", "")).strip()
    feels_like_c = str(current.get("FeelsLikeC", "")).strip()
    humidity = str(current.get("humidity", "")).strip()
    wind = str(current.get("windspeedKmph", "")).strip()
    max_temp = str(today.get("maxtempC", "")).strip()
    min_temp = str(today.get("mintempC", "")).strip()

    if language == "en":
        summary_parts = [f"Current weather in {normalized}"]
        if desc:
            summary_parts.append(desc)
        if temp_c:
            summary_parts.append(f"temperature {temp_c} degrees Celsius")
        if feels_like_c:
            summary_parts.append(f"feels like {feels_like_c} degrees")
        if humidity:
            summary_parts.append(f"humidity {humidity} percent")
        if wind:
            summary_parts.append(f"wind speed {wind} kilometers per hour")
        if max_temp or min_temp:
            summary_parts.append(f"today {min_temp or '?'} to {max_temp or '?'} degrees")
        summary = ", ".join(summary_parts) + "."
    elif language == "zh-YUE":
        summary_parts = [f"{normalized}而家"]
        if desc:
            summary_parts.append(desc)
        if temp_c:
            summary_parts.append(f"氣溫{temp_c}度")
        if feels_like_c:
            summary_parts.append(f"體感{feels_like_c}度")
        if humidity:
            summary_parts.append(f"濕度{humidity}%")
        if wind:
            summary_parts.append(f"風速{wind}公里每小時")
        if max_temp or min_temp:
            summary_parts.append(f"今日{min_temp or '?'}到{max_temp or '?'}度")
        summary = "，".join(summary_parts) + "。"
    else:
        summary_parts = [f"{normalized}当前"]
        if desc:
            summary_parts.append(desc)
        if temp_c:
            summary_parts.append(f"气温{temp_c}度")
        if feels_like_c:
            summary_parts.append(f"体感{feels_like_c}度")
        if humidity:
            summary_parts.append(f"湿度{humidity}%")
        if wind:
            summary_parts.append(f"风速{wind}公里每小时")
        if max_temp or min_temp:
            summary_parts.append(f"今天{min_temp or '?'}到{max_temp or '?'}度")
        summary = "，".join(summary_parts) + "。"
    return WeatherResult(
        ok=True,
        summary=summary,
        raw_text=json.dumps(payload, ensure_ascii=False),
    )
