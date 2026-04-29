from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable
from urllib.parse import quote_plus
from urllib.request import ProxyHandler, Request, build_opener, urlopen
import xml.etree.ElementTree as ET


RSS_TOP_HEADLINES = "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
RSS_SEARCH = (
    "https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)


@dataclass
class NewsResult:
    ok: bool
    summary: str
    error: str = ""


def _iter_titles(xml_bytes: bytes) -> Iterable[str]:
    root = ET.fromstring(xml_bytes)
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        if title:
            yield title


def _clean_title(title: str) -> str:
    cleaned = " ".join((title or "").split()).strip()
    if " - " in cleaned:
        cleaned = cleaned.rsplit(" - ", 1)[0].strip()
    return cleaned


def query_news(
    topic: str = "",
    *,
    limit: int = 3,
    timeout: float = 8.0,
    language: str = "zh-CN",
) -> NewsResult:
    normalized_topic = " ".join((topic or "").split()).strip()
    url = RSS_SEARCH.format(query=quote_plus(normalized_topic)) if normalized_topic else RSS_TOP_HEADLINES
    request = Request(
        url,
        headers={
            "User-Agent": "interrupt-news-fetch/1.0",
        },
    )
    proxy_url = (
        os.getenv("INTERRUPT_NEWS_PROXY", "").strip()
        or os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("WSS_PROXY", "").strip()
    )
    if proxy_url:
        opener = build_opener(
            ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
        )
        response_ctx = opener.open(request, timeout=timeout)
    else:
        response_ctx = urlopen(request, timeout=timeout)
    with response_ctx as response:
        payload = response.read()
    titles = []
    for raw_title in _iter_titles(payload):
        cleaned = _clean_title(raw_title)
        if not cleaned or cleaned in titles:
            continue
        titles.append(cleaned)
        if len(titles) >= max(1, limit):
            break
    if not titles:
        return NewsResult(ok=False, summary="", error="no headlines")
    if normalized_topic:
        if language == "en":
            prefix = f"Latest news about {normalized_topic}"
        elif language == "zh-YUE":
            prefix = f"{normalized_topic}相關最新新聞"
        else:
            prefix = f"{normalized_topic}相关最新新闻"
    else:
        if language == "en":
            prefix = "Today's top headlines"
        elif language == "zh-YUE":
            prefix = "今日熱點新聞"
        else:
            prefix = "今天的热点新闻"
    if language == "en":
        items = "; ".join(f"{idx}. {title}" for idx, title in enumerate(titles, start=1))
        summary = prefix + ": " + items + "."
    else:
        items = "；".join(f"{idx}. {title}" for idx, title in enumerate(titles, start=1))
        summary = prefix + "：" + items + "。"
    return NewsResult(ok=True, summary=summary)
