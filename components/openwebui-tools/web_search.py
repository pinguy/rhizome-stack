"""
Open WebUI tool for live public web search through Brave.

This is stored in Open WebUI's tool table too; keep this file as the
recoverable source of truth for future edits.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests


OPENWEBUI_DB = Path(os.environ.get("OPENWEBUI_DB", str(Path.home() / ".local/share/rhizome-stack/state/openwebui-data/webui.db")))
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", str(Path.home() / ".openclaw/openclaw.json")))
LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "UTC"))
TOOL_VERSION = "1.7.0"
F1_RACING_URL = "https://www.formula1.com/en/racing/{year}"
F1_EVENTS_API_URL = "https://api.formula1.com/v1/editorial-eventlisting/events"
F1_PUBLIC_API_KEY_FALLBACK = os.getenv(
    "F1_PUBLIC_API_KEY", "BQ1SiSmLUOsp460VzXBlLrh689kGgYEZ"
)

RECENCY_TERMS = (
    "breaking",
    "current",
    "latest",
    "live",
    "new",
    "news",
    "now",
    "recent",
    "release",
    "today",
    "tonight",
    "this morning",
    "this afternoon",
    "this evening",
    "this week",
    "update",
)

ACTIVE_EVENT_TERMS = (
    "breaking",
    "coverage",
    "currently happening",
    "election results",
    "latest updates",
    "live",
    "live blog",
    "live coverage",
    "live feed",
    "live score",
    "live updates",
    "minute by minute",
    "ongoing",
    "race updates",
    "right now",
    "score centre",
    "scorecenter",
    "scores",
    "tracker",
)

OFFICIAL_DOMAINS = (
    # UK government, Parliament, courts, police, regulators, and public bodies.
    "gov.uk",
    "nationalcrimeagency.gov.uk",
    "cps.gov.uk",
    "judiciary.uk",
    "parliament.uk",
    "committees.parliament.uk",
    "police.uk",
    "fca.org.uk",
    "ofcom.org.uk",
    "ico.org.uk",
    "hse.gov.uk",
    "cqc.org.uk",
    "ofgem.gov.uk",
    "ofwat.gov.uk",
    "ons.gov.uk",
    "bankofengland.co.uk",
    "england.nhs.uk",
    "electoralcommission.org.uk",
    "environment-agency.gov.uk",
    # Sport and team sources retained from the original tool.
    "formula1.com",
    "fia.com",
    "redbullracing.com",
    "mclaren.com",
    "ferrari.com",
    "mercedesamgf1.com",
    "astonmartinf1.com",
    "alpinecars.com",
    "williamsf1.com",
    "visacashapprb.com",
    "haasf1team.com",
    "stakef1team.com",
)

PRIMARY_DOCUMENT_DOMAINS = (
    "bailii.org",
    "legislation.gov.uk",
    "supremecourt.uk",
)

REPUTABLE_REPORTING_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
    "itv.com",
    "channel4.com",
    "news.sky.com",
    "skysports.com",
    "ft.com",
    "politico.com",
    "politico.eu",
    "independent.co.uk",
    "theguardian.com",
    "telegraph.co.uk",
    "nytimes.com",
    "washingtonpost.com",
    "nbcnews.com",
    "cbsnews.com",
    "abcnews.go.com",
    "aljazeera.com",
    "cnbc.com",
    "autosport.com",
    "motorsport.com",
    "the-race.com",
    "espn.com",
    "espn.co.uk",
    "racingnews365.com",
    "planetf1.com",
)

SPECULATION_TERMS = (
    "could",
    "may",
    "might",
    "rumor",
    "rumour",
    "speculation",
    "speculative",
    "paddock talk",
    "linked with",
    "reportedly",
    "reports claim",
    "sources claim",
    "it is claimed",
    "understood",
    "fiction",
    "denied",
)

CONFIRMATION_TERMS = (
    "announced",
    "confirmed",
    "official",
    "statement",
    "said",
    "quoted",
    "according to the fia",
    "according to formula 1",
)

VOLATILE_FACT_TERMS = (
    "casualty",
    "casualties",
    "critical care",
    "death toll",
    "dead",
    "fatalities",
    "funded until",
    "injured",
    "latest count",
    "missing",
    "next prime minister",
    "office-holder",
    "polling",
    "run out of cash",
    "standings",
    "survivors",
    "vote count",
)

RELATIONAL_FACT_TERMS = (
    "final",
    "fixture",
    "quarter-final",
    "quarterfinal",
    "round of 16",
    "semi-final",
    "semifinal",
    "versus",
    " vs ",
    "face ",
    "faces ",
)

NEWS_QUERY_TERMS = (
    "breaking news",
    "headlines",
    "latest news",
    "main news",
    "news update",
    "news today",
    "top news",
    "top stories",
    "world news",
)

MAIN_NEWS_QUERY_TERMS = (
    "headlines",
    "main news",
    "news today",
    "top news",
    "top stories",
    "world news",
)

LOCAL_NEWS_QUERY_TERMS = (
    "around me",
    "in my area",
    "local headlines",
    "local news",
    "near me",
)

DEFAULT_LOCALITY = os.environ.get("DEFAULT_LOCALITY", "")
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
NEWS_CURRENT_MAX_AGE_DAYS = 2
NEWS_BACKGROUND_MAX_AGE_DAYS = 14

BAD_CITATION_DOMAINS = (
    "google.com",
    "news.google.com",
    "bing.com",
    "brave.com",
    "duckduckgo.com",
    "search.yahoo.com",
)

BAD_CITATION_PATH_TERMS = (
    "/archive",
    "/archives",
    "/category",
    "/categories",
    "/section",
    "/sections",
    "/tag/",
    "/tags/",
    "/topics/",
    "/topic/",
    "/search",
    "/video",
    "/videos",
)

BACKGROUND_TERMS = (
    "background",
    "context",
    "explainer",
    "profile",
    "timeline",
    "what to know",
)

NEWS_ARTICLEISH_DOMAINS = (
    "aljazeera.com",
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
    "cbsnews.com",
    "cnbc.com",
    "cnn.com",
    "foxnews.com",
    "independent.co.uk",
    "nbcnews.com",
    "nytimes.com",
    "reuters.com",
    "theguardian.com",
    "telegraph.co.uk",
)

MONTH_PATH_TERMS = (
    "jan",
    "january",
    "feb",
    "february",
    "mar",
    "march",
    "apr",
    "april",
    "may",
    "jun",
    "june",
    "jul",
    "july",
    "aug",
    "august",
    "sep",
    "sept",
    "september",
    "oct",
    "october",
    "nov",
    "november",
    "dec",
    "december",
)

EVENT_DATE_TERMS = (
    "announced",
    "arrested",
    "charged",
    "died",
    "final pmqs",
    "posted",
    "published",
    "released",
    "resigned",
    "said",
    "threat",
)

CUSTODY_STATE_TERMS = (
    "arrest",
    "arrested",
    "bail",
    "bailed",
    "charged",
    "custody",
    "detained",
    "released",
    "suspect",
)

RELEASED_CUSTODY_TERMS = (
    "released on bail",
    "released on police bail",
    "released under investigation",
    "held overnight and released",
    "questioned and released",
    "released after",
    "bailed",
)

DETAINED_CUSTODY_TERMS = (
    "remains in custody",
    "remained in custody",
    "still in custody",
    "detained",
    "held in custody",
)

# Conservative cached subset of AllSides ratings. Lean ratings are preserved in
# detail and normalised to left/right for balancing. Unknown outlets stay unknown.
ALLSIDES_BIAS_RATINGS = {
    "allsides.com": ("Center", "center"),
    "bbc.com": ("Center", "center"),
    "bbc.co.uk": ("Center", "center"),
    "cnn.com": ("Lean Left", "left"),
    "dailymail.co.uk": ("Right", "right"),
    "foxnews.com": ("Right", "right"),
    "msnbc.com": ("Left", "left"),
    "nationalreview.com": ("Right", "right"),
    "newsweek.com": ("Center", "center"),
    "nypost.com": ("Lean Right", "right"),
    "nytimes.com": ("Lean Left", "left"),
    "reuters.com": ("Center", "center"),
    "theguardian.com": ("Lean Left", "left"),
    "telegraph.co.uk": ("Lean Right", "right"),
    "usatoday.com": ("Lean Left", "left"),
    "vox.com": ("Left", "left"),
    "washingtonexaminer.com": ("Lean Right", "right"),
    "washingtonpost.com": ("Lean Left", "left"),
}

LEFT_NEWS_DOMAINS = tuple(
    domain for domain, (_, bucket) in ALLSIDES_BIAS_RATINGS.items() if bucket == "left"
)
RIGHT_NEWS_DOMAINS = tuple(
    domain for domain, (_, bucket) in ALLSIDES_BIAS_RATINGS.items() if bucket == "right"
)



BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
HTTP_TIMEOUT = (5, 20)
HTTP_RETRIES = 3
MAX_QUERY_CHARS = 500
DEFAULT_RESULTS = 10
MAX_RESULTS = 12
MAX_ADDITIONAL_SOURCES = 5
MIN_CANDIDATE_POOL = 20
MAX_CUSTODY_VALIDATIONS = 2
MAX_UPSTREAM_CHASES = 6
MAX_UPSTREAM_SOURCES_PER_HINT = 2
UPSTREAM_SEARCH_RESULTS = 8
USER_AGENT = f"OpenWebUI-Rhizome/{TOOL_VERSION}"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
TRACKING_QUERY_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}

# Signals in reporting that imply a more authoritative upstream source exists.
# These are intentionally conservative: a detected hint triggers a targeted
# official-domain search rather than upgrading the secondary article itself.
UPSTREAM_SOURCE_RULES = (
    {
        "id": "nca",
        "source_name": "National Crime Agency",
        "source_type": "law_enforcement",
        "document_type": "official case release or statement",
        "domains": ("nationalcrimeagency.gov.uk",),
        "patterns": (
            r"\b(?:the\s+)?(?:national crime agency|nca)\s+(?:said|announced|confirmed|stated|reported|published|warned|alleged)\b",
            r"\baccording to\s+(?:the\s+)?(?:national crime agency|nca)\b",
        ),
        "confidence": "high",
    },
    {
        "id": "cps",
        "source_name": "Crown Prosecution Service",
        "source_type": "prosecuting_authority",
        "document_type": "official prosecution release or case statement",
        "domains": ("cps.gov.uk",),
        "patterns": (
            r"\b(?:the\s+)?(?:crown prosecution service|cps)\s+(?:said|announced|confirmed|stated|authorised|charged|published)\b",
            r"\baccording to\s+(?:the\s+)?(?:crown prosecution service|cps)\b",
        ),
        "confidence": "high",
    },
    {
        "id": "uk_government",
        "source_name": "UK government or named department",
        "source_type": "government",
        "document_type": "GOV.UK announcement, statement, guidance, or data release",
        "domains": ("gov.uk",),
        "patterns": (
            r"\bgov\.uk\s+(?:said|announced|confirmed|published|released|stated)\b",
            r"\b(?:the\s+)?government\s+(?:said|announced|confirmed|published|released|stated)\b",
            r"\b(?:home office|cabinet office|downing street|hm treasury|ministry of justice|department for [a-z][a-z &-]{2,60}|department of [a-z][a-z &-]{2,60})\s+(?:said|announced|confirmed|published|released|stated|reported)\b",
            r"\baccording to\s+(?:gov\.uk|the government|the home office|hm treasury|the ministry of justice)\b",
        ),
        "confidence": "high",
    },
    {
        "id": "court_record",
        "source_name": "Court or prosecuting authority",
        "source_type": "court_record",
        "document_type": "judgment, ruling, sentencing remarks, indictment, or prosecution release",
        "domains": ("judiciary.uk", "supremecourt.uk", "cps.gov.uk", "bailii.org"),
        "patterns": (
            r"\bcourt\s+(?:heard|was told)\b",
            r"\b(?:court|legal) documents?\s+(?:said|showed|revealed|alleged|state|states)\b",
            r"\b(?:a|the)\s+(?:judge|magistrate)\s+(?:said|ruled|found|heard)\b",
            r"\b(?:judgment|judgement|ruling|sentencing remarks|indictment|charge sheet)\b",
        ),
        "confidence": "medium",
    },
    {
        "id": "police",
        "source_name": "Named police force",
        "source_type": "police",
        "document_type": "official police statement, appeal, or case update",
        "domains": ("police.uk",),
        "patterns": (
            r"\b(?:[a-z][a-z'& -]{2,45}\s+police|police scotland|police service of northern ireland|metropolitan police|the police)\s+(?:said|announced|confirmed|stated|reported|appealed|released|added)\b",
            r"\baccording to\s+(?:[a-z][a-z'& -]{2,45}\s+police|police scotland|the metropolitan police|the police)\b",
        ),
        "confidence": "medium",
    },
    {
        "id": "parliament",
        "source_name": "UK Parliament",
        "source_type": "parliamentary_record",
        "document_type": "Hansard, committee evidence, report, or written statement",
        "domains": ("parliament.uk", "committees.parliament.uk"),
        "patterns": (
            r"\b(?:parliament|the commons|the lords|mps|peers|a parliamentary committee|the committee)\s+(?:heard|was told|said|published|reported)\b",
            r"\b(?:hansard|written ministerial statement|committee evidence|select committee report)\b",
        ),
        "confidence": "high",
    },
    {
        "id": "fca",
        "source_name": "Financial Conduct Authority",
        "source_type": "regulator",
        "document_type": "regulatory notice, decision, warning, or data release",
        "domains": ("fca.org.uk",),
        "patterns": (r"\b(?:financial conduct authority|fca)\s+(?:said|announced|confirmed|published|warned|fined|found)\b",),
        "confidence": "high",
    },
    {
        "id": "cma",
        "source_name": "Competition and Markets Authority",
        "source_type": "regulator",
        "document_type": "CMA decision, investigation update, or case document",
        "domains": ("gov.uk",),
        "patterns": (r"\b(?:competition and markets authority|cma)\s+(?:said|announced|confirmed|published|found|ruled|opened|cleared|blocked)\b",),
        "confidence": "high",
    },
    {
        "id": "ofcom",
        "source_name": "Ofcom",
        "source_type": "regulator",
        "document_type": "Ofcom decision, bulletin, consultation, or data release",
        "domains": ("ofcom.org.uk",),
        "patterns": (r"\bofcom\s+(?:said|announced|confirmed|published|found|ruled|warned|fined)\b",),
        "confidence": "high",
    },
    {
        "id": "ico",
        "source_name": "Information Commissioner's Office",
        "source_type": "regulator",
        "document_type": "ICO enforcement notice, decision, statement, or guidance",
        "domains": ("ico.org.uk",),
        "patterns": (r"\b(?:information commissioner's office|information commissioner|ico)\s+(?:said|announced|confirmed|published|found|warned|fined)\b",),
        "confidence": "high",
    },
    {
        "id": "hse",
        "source_name": "Health and Safety Executive",
        "source_type": "regulator",
        "document_type": "HSE prosecution release, notice, report, or guidance",
        "domains": ("hse.gov.uk",),
        "patterns": (r"\b(?:health and safety executive|hse)\s+(?:said|announced|confirmed|published|found|warned|prosecuted)\b",),
        "confidence": "high",
    },
    {
        "id": "cqc",
        "source_name": "Care Quality Commission",
        "source_type": "regulator",
        "document_type": "inspection report, enforcement action, or statement",
        "domains": ("cqc.org.uk",),
        "patterns": (r"\b(?:care quality commission|cqc)\s+(?:said|announced|confirmed|published|found|rated|warned)\b",),
        "confidence": "high",
    },
    {
        "id": "ofgem",
        "source_name": "Ofgem",
        "source_type": "regulator",
        "document_type": "Ofgem decision, consultation, enforcement notice, or data release",
        "domains": ("ofgem.gov.uk",),
        "patterns": (r"\bofgem\s+(?:said|announced|confirmed|published|found|warned|fined)\b",),
        "confidence": "high",
    },
    {
        "id": "ofwat",
        "source_name": "Ofwat",
        "source_type": "regulator",
        "document_type": "Ofwat decision, enforcement notice, consultation, or data release",
        "domains": ("ofwat.gov.uk",),
        "patterns": (r"\bofwat\s+(?:said|announced|confirmed|published|found|warned|fined)\b",),
        "confidence": "high",
    },
    {
        "id": "ons",
        "source_name": "Office for National Statistics",
        "source_type": "official_statistics",
        "document_type": "ONS statistical bulletin, dataset, or methodology note",
        "domains": ("ons.gov.uk",),
        "patterns": (
            r"\b(?:office for national statistics|ons)\s+(?:said|announced|confirmed|published|reported|found|estimated)\b",
            r"\b(?:ons figures|official figures from the ons)\s+(?:show|showed|suggest|suggested)\b",
        ),
        "confidence": "high",
    },
    {
        "id": "bank_of_england",
        "source_name": "Bank of England",
        "source_type": "central_bank",
        "document_type": "Bank statement, decision, minutes, speech, or data release",
        "domains": ("bankofengland.co.uk",),
        "patterns": (r"\b(?:bank of england|boe)\s+(?:said|announced|confirmed|published|reported|warned|held|cut|raised)\b",),
        "confidence": "high",
    },
    {
        "id": "nhs_england",
        "source_name": "NHS England",
        "source_type": "public_health_body",
        "document_type": "NHS England statement, guidance, report, or data release",
        "domains": ("england.nhs.uk",),
        "patterns": (r"\bnhs england\s+(?:said|announced|confirmed|published|reported|warned)\b",),
        "confidence": "high",
    },
    {
        "id": "electoral_commission",
        "source_name": "Electoral Commission",
        "source_type": "regulator",
        "document_type": "Electoral Commission decision, register, report, or statement",
        "domains": ("electoralcommission.org.uk",),
        "patterns": (r"\b(?:electoral commission|the commission)\s+(?:said|announced|confirmed|published|found|warned|fined)\b",),
        "confidence": "high",
    },
)

UPSTREAM_STOPWORDS = {
    "about", "after", "again", "against", "amid", "and", "announced", "before",
    "being", "between", "could", "court", "from", "government", "have", "into",
    "latest", "more", "news", "official", "over", "said", "says", "source", "that",
    "their", "them", "then", "there", "this", "through", "today", "under", "update",
    "with", "would",
}

GENERIC_SOURCE_INDICATORS = {
    "agency", "association", "authority", "bank", "board", "charity", "commission", "committee",
    "company", "council", "department", "executive", "foundation", "government", "institute",
    "ministry", "office", "organisation", "organization", "parliament", "police", "regulator",
    "service", "trust", "union", "university", "watchdog",
}
GENERIC_SOURCE_EXCLUSIONS = {
    "associated press", "bbc", "cnn", "daily mail", "financial times", "fox news",
    "guardian", "itv news", "new york times", "reuters", "sky news", "telegraph",
    "the independent", "the times", "washington post",
}
UPSTREAM_OFFICIAL_MARKERS = (
    "announcement", "decision", "guidance", "judgment", "judgement", "media release",
    "news release", "newsroom", "official statement", "press release", "publication",
    "report", "ruling", "sentencing remarks", "statement",
)


class SearchToolError(RuntimeError):
    """Expected network, provider, or response-shape failure."""


def _decode_secret_value(raw: object) -> str:
    """Decode values stored as JSON strings, plain strings, or small mappings."""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        for key in ("api_key", "apiKey", "key", "value"):
            value = raw.get(key)
            if value:
                return str(value).strip()
        return ""
    if not isinstance(raw, str):
        return str(raw).strip()

    value = raw.strip()
    if not value:
        return ""
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value
    if decoded == raw:
        return value
    return _decode_secret_value(decoded)


def _read_brave_key() -> str:
    for name in ("BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value

    if OPENWEBUI_DB.exists():
        try:
            with sqlite3.connect(OPENWEBUI_DB) as conn:
                row = conn.execute(
                    "select value from config where key='web.search.brave_search_api_key'"
                ).fetchone()
            value = _decode_secret_value(row[0] if row else None)
            if value:
                return value
        except (OSError, sqlite3.Error):
            pass

    if OPENCLAW_CONFIG.exists():
        try:
            data = json.loads(OPENCLAW_CONFIG.read_text(encoding="utf-8"))
            raw = (
                data.get("plugins", {})
                .get("entries", {})
                .get("brave", {})
                .get("config", {})
                .get("webSearch", {})
                .get("apiKey")
            )
            value = _decode_secret_value(raw)
            if value:
                return value
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    return ""


def _current_time_context() -> dict:
    now = datetime.now(LOCAL_TZ)
    return {
        "timezone": str(LOCAL_TZ),
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "date_long": now.strftime("%A, %d %B %Y"),
        "year": str(now.year),
    }


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    cleaned = " ".join(str(term or "").strip().split())
    escaped = re.escape(cleaned).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    value = str(text or "")
    return any(term and _term_pattern(term).search(value) for term in terms)


def _clean_query(query: str) -> str:
    return " ".join(str(query or "").split())[:MAX_QUERY_CHARS].strip()


def _wants_fresh_sources(query: str) -> bool:
    return _contains_any(_clean_query(query), RECENCY_TERMS)


def _build_search_query(query: str, clock: dict) -> str:
    cleaned = _clean_query(query)
    if not cleaned:
        return clock["date"]
    if not _wants_fresh_sources(cleaned):
        return cleaned

    additions: list[str] = []
    if clock["date"] not in cleaned and not re.search(rf"(?<!\d){re.escape(clock['year'])}(?!\d)", cleaned):
        additions.append(clock["date"])
    if not _contains_any(cleaned, ("latest", "current", "today", "now")):
        additions.append("latest")
    return " ".join((cleaned, *additions)).strip()


def _freshness_filter(query: str) -> str | None:
    return "pm" if _wants_fresh_sources(query) else None


def _domain_for_url(url: str) -> str:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _domain_matches(domain: str, candidates: tuple[str, ...]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in candidates)


def _looks_like_news_query(query: str) -> bool:
    q = _clean_query(query).lower()
    return _contains_any(q, ("news",)) or _contains_any(q, NEWS_QUERY_TERMS)


def _looks_like_main_news_query(query: str) -> bool:
    return _contains_any(_clean_query(query), MAIN_NEWS_QUERY_TERMS)


def _looks_like_local_news_query(query: str) -> bool:
    return _contains_any(_clean_query(query), LOCAL_NEWS_QUERY_TERMS)


def _allsides_bias_for_url(url: str) -> dict:
    domain = _domain_for_url(url)
    for candidate, (detailed, bucket) in ALLSIDES_BIAS_RATINGS.items():
        if domain == candidate or domain.endswith(f".{candidate}"):
            return {
                "rating": bucket,
                "allsides_rating": detailed,
                "rating_source": "cached AllSides Media Bias Rating",
                "rating_lookup": f"https://www.allsides.com/media-bias/media-bias-ratings?search={candidate}",
            }
    return {
        "rating": "unknown",
        "allsides_rating": None,
        "rating_source": "AllSides rating not cached",
        "rating_lookup": (
            f"https://www.allsides.com/media-bias/media-bias-ratings?search={domain}"
            if domain
            else None
        ),
    }


def _site_query(domains: tuple[str, ...]) -> str:
    return "(" + " OR ".join(f"site:{domain}" for domain in domains) + ")"


def _mentioned_years(text: str) -> list[int]:
    return list(dict.fromkeys(int(match.group(1)) for match in re.finditer(r"\b(20[0-9]{2})\b", text)))


def _source_published_at(result: dict) -> str | None:
    for key in ("published_at", "published", "date", "page_age", "age"):
        value = result.get(key)
        if value:
            return str(value)
    return None


def _relative_number(value: str) -> int | None:
    value = value.lower()
    if value in {"a", "an", "one"}:
        return 1
    return int(value) if value.isdigit() else None


def _parse_absolute_date(value: str) -> date | None:
    candidate = value.strip().strip("·-")
    if not candidate:
        return None

    iso_candidate = candidate.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(candidate).date()
    except (TypeError, ValueError, OverflowError):
        pass

    patterns = (
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue

    date_match = re.search(
        r"(?:\b\d{4}-\d{1,2}-\d{1,2}\b|\b[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b)",
        candidate,
    )
    if date_match and date_match.group(0) != candidate:
        return _parse_absolute_date(date_match.group(0))
    return None


def _result_age_days(result: dict, clock: dict) -> int | None:
    values = [
        str(result.get(key, "") or "")
        for key in ("age", "page_age", "published", "published_at", "date")
    ]
    combined = " ".join(values).strip().lower()
    if not combined:
        return None

    if _contains_any(combined, ("just now", "today")):
        return 0
    if _contains_any(combined, ("yesterday",)):
        return 1

    relative = re.search(
        r"\b(a|an|one|\d+)\s+(minute|hour|day|week|month|year)s?\s+ago\b",
        combined,
    )
    if relative:
        amount = _relative_number(relative.group(1))
        unit = relative.group(2)
        if amount is not None:
            multipliers = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
            return amount * multipliers[unit]

    today = date.fromisoformat(clock["date"])
    for value in values:
        parsed = _parse_absolute_date(value)
        if parsed:
            return max(0, (today - parsed).days)
    return None


def _result_text(result: dict) -> str:
    return "\n".join(
        str(result.get(key, "") or "")
        for key in ("title", "description", "url", "age", "page_age", "published_at")
    )


def _canonical_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_QUERY_PARAMETERS],
        doseq=True,
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))


def _normalised_title(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = value.rsplit(" - ", 1)[0]
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _title_similarity(first: str, second: str) -> float:
    a = _normalised_title(first)
    b = _normalised_title(second)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    return (sequence * 0.65) + (overlap * 0.35)


def _dedupe_results(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    output: list[dict] = []
    for result in results:
        key = _canonical_url(result.get("url", ""))
        if not key:
            key = f"{_domain_for_url(result.get('url', ''))}|{_normalised_title(result.get('title', ''))}"
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output


def _select_diverse_results(results: list[dict], count: int) -> list[dict]:
    unique = _dedupe_results(results)
    selected: list[dict] = []
    deferred: list[dict] = []
    seen_domains: set[str] = set()
    for result in unique:
        domain = _domain_for_url(result.get("url", ""))
        if domain and domain not in seen_domains:
            selected.append(result)
            seen_domains.add(domain)
        else:
            deferred.append(result)
        if len(selected) >= count:
            return selected[:count]
    selected.extend(deferred[: max(0, count - len(selected))])
    return selected[:count]


def _additional_source_target(primary_count: int, *, local_news: bool = False) -> int:
    """Return a useful supporting-source pool without letting payloads explode."""
    target = max(3, (primary_count + 1) // 2)
    if local_news:
        target = min(target, 4)
    return min(MAX_ADDITIONAL_SOURCES, target)


def _exclude_seen_results(results: list[dict], seen_results: list[dict]) -> list[dict]:
    seen_urls = {_canonical_url(item.get("url", "")) for item in seen_results}
    seen_titles = {_normalised_title(item.get("title", "")) for item in seen_results}
    output: list[dict] = []
    for result in results:
        canonical = _canonical_url(result.get("url", ""))
        title = _normalised_title(result.get("title", ""))
        if canonical and canonical in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        output.append(result)
    return output


def _clean_referenced_source_name(value: str) -> str:
    value = re.sub(r"^(?:the|a|an)\s+", "", " ".join(str(value or "").split()), flags=re.IGNORECASE)
    return value.strip(" \t\r\n,;:()[]{}\"'’")


def _looks_like_institutional_source_name(value: str) -> bool:
    source = _clean_referenced_source_name(value)
    if not source or len(source) > 80:
        return False
    lower = source.lower()
    words = re.findall(r"[a-z0-9]+", lower)
    if not words or len(words) > 9 or lower in GENERIC_SOURCE_EXCLUSIONS:
        return False
    if words[0] in {"he", "she", "they", "it", "sources", "experts", "officials", "witnesses"}:
        return False
    if any(word in GENERIC_SOURCE_INDICATORS for word in words):
        return True
    if len(words) == 1:
        raw = re.sub(r"[^A-Za-z0-9]", "", source)
        return (raw.isupper() and 2 <= len(raw) <= 10) or (raw[:1].isupper() and len(raw) >= 4)
    # Two ordinary title-cased words are usually a person's name. Three or more
    # capitalised words are much more likely to be an organisation or campaign.
    if len(words) >= 3:
        capitals = re.findall(r"(?:^|\s)([A-Z][A-Za-z0-9'’&-]*)", source)
        return len(capitals) >= 2
    return False


def _generic_upstream_hints(text: str, seen_source_names: set[str]) -> list[dict]:
    hints: list[dict] = []
    sentences = [part.strip() for part in re.split(r"[.!?;\n]+", text) if part.strip()]
    verbs = r"said|announced|confirmed|published|reported|found|warned|stated|released"
    for sentence in sentences:
        matches: list[tuple[str, str]] = []
        according = re.search(
            r"\baccording to\s+(?:the\s+)?(.{2,70}?)(?=,|$|\s+(?:which|who|that)\b)",
            sentence,
            flags=re.IGNORECASE,
        )
        if according:
            matches.append((according.group(1), according.group(0)))
        attributed = re.match(
            rf"^(?:the\s+)?(.{{2,70}}?)\s+({verbs})\b",
            sentence,
            flags=re.IGNORECASE,
        )
        if attributed:
            matches.append((attributed.group(1), attributed.group(0)))

        for raw_source, matched_signal in matches:
            source_name = _clean_referenced_source_name(raw_source)
            normalised = _normalised_title(source_name)
            if not _looks_like_institutional_source_name(source_name):
                continue
            if normalised in seen_source_names or source_name.lower() in GENERIC_SOURCE_EXCLUSIONS:
                continue
            seen_source_names.add(normalised)
            hints.append(
                {
                    "hint_id": f"referenced_organisation:{normalised.replace(' ', '_')}",
                    "source_name": source_name,
                    "source_type": "referenced_organisation",
                    "document_type": "official statement, release, report, filing, or publication",
                    "matched_signal": " ".join(matched_signal.split()),
                    "official_domains": [],
                    "confidence": "medium",
                    "chase_required": True,
                }
            )
    return hints


def _detect_upstream_source_hints(result: dict) -> list[dict]:
    """Detect references to primary institutions in a title/search snippet."""
    text = "\n".join(
        str(result.get(key, "") or "") for key in ("title", "description")
    )
    if not text.strip():
        return []

    hints: list[dict] = []
    seen_ids: set[str] = set()
    seen_source_names: set[str] = set()
    for rule in UPSTREAM_SOURCE_RULES:
        matched_signal = None
        for pattern in rule["patterns"]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                matched_signal = " ".join(match.group(0).split())
                break
        if not matched_signal or rule["id"] in seen_ids:
            continue
        seen_ids.add(rule["id"])
        seen_source_names.add(_normalised_title(rule["source_name"]))
        hints.append(
            {
                "hint_id": rule["id"],
                "source_name": rule["source_name"],
                "source_type": rule["source_type"],
                "document_type": rule["document_type"],
                "matched_signal": matched_signal,
                "official_domains": list(rule["domains"]),
                "confidence": rule["confidence"],
                "chase_required": True,
            }
        )
    for generic_hint in _generic_upstream_hints(text, seen_source_names):
        generic_source = _normalised_title(generic_hint.get("source_name", ""))
        duplicate = any(
            generic_source
            and generic_source in _normalised_title(existing.get("matched_signal", ""))
            for existing in hints
        )
        if not duplicate:
            hints.append(generic_hint)
    return hints


def _upstream_topic_terms(result: dict, limit: int = 12) -> list[str]:
    """Extract stable story terms for a targeted primary-source search."""
    title = str(result.get("title", "") or "").rsplit(" - ", 1)[0]
    description = str(result.get("description", "") or "")
    tokens = re.findall(r"[a-z0-9][a-z0-9'’-]{2,}", f"{title} {description}".lower())
    output: list[str] = []
    for token in tokens:
        token = token.strip("'’- ")
        if len(token) < 4 or token in UPSTREAM_STOPWORDS or token.isdigit():
            continue
        if token not in output:
            output.append(token)
        if len(output) >= limit:
            break
    return output


def _upstream_chase_query(result: dict, hint: dict) -> str:
    domains = tuple(str(domain) for domain in hint.get("official_domains", []) if domain)
    site_clause = _site_query(domains) if domains else ""
    topic = " ".join(_upstream_topic_terms(result))
    source_name = str(hint.get("source_name", "") or "")
    source_phrase = f'"{source_name}"' if source_name else ""
    official_marker = "" if domains else "official statement release report"
    return _clean_query(f"{site_clause} {source_phrase} {official_marker} {topic}")


def _token_overlap(first: str, second: str) -> float:
    a = set(_normalised_title(first).split()) - UPSTREAM_STOPWORDS
    b = set(_normalised_title(second).split()) - UPSTREAM_STOPWORDS
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _upstream_candidate_score(candidate: dict, source_result: dict, hint: dict, clock: dict) -> float:
    domain = _domain_for_url(candidate.get("url", ""))
    expected = tuple(hint.get("official_domains", []))
    if expected and not _domain_matches(domain, expected):
        return 0.0
    quality = _citation_url_quality(candidate.get("url", ""))
    if not quality["usable_as_final_citation"]:
        return 0.0

    source_title = str(source_result.get("title", "") or "")
    candidate_title = str(candidate.get("title", "") or "")
    source_text = f"{source_result.get('title', '')} {source_result.get('description', '')}"
    candidate_text = f"{candidate.get('title', '')} {candidate.get('description', '')}"
    title_score = _title_similarity(source_title, candidate_title)
    overlap_score = _token_overlap(source_text, candidate_text)
    age_days = _result_age_days(candidate, clock)
    freshness_score = 0.08 if age_days is not None and age_days <= 31 else 0.03 if age_days is not None else 0.0

    source_name = str(hint.get("source_name", "") or "")
    source_tokens = [
        token for token in _normalised_title(source_name).split()
        if token not in UPSTREAM_STOPWORDS and token not in {"limited", "ltd", "plc", "group"}
    ]
    compact_domain = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    domain_affinity = any(
        len(token) >= 4 and (token in compact_domain or compact_domain in token)
        for token in source_tokens
    )
    source_named_on_page = bool(source_name and _token_overlap(source_name, candidate_text) >= 0.5)
    official_marker = _contains_any(candidate_text + " " + str(candidate.get("url", "")), UPSTREAM_OFFICIAL_MARKERS)

    if _domain_matches(domain, REPUTABLE_REPORTING_DOMAINS) and not expected:
        return 0.0
    if _domain_matches(domain, OFFICIAL_DOMAINS + PRIMARY_DOCUMENT_DOMAINS):
        primary_bonus = 0.52
    elif domain_affinity or source_named_on_page:
        primary_bonus = 0.38
    else:
        primary_bonus = 0.0
    marker_bonus = 0.08 if official_marker else 0.0
    return round(primary_bonus + marker_bonus + (title_score * 0.18) + (overlap_score * 0.18) + freshness_score, 4)


def _compact_upstream_source(candidate: dict, source_result: dict, hint: dict, query: str, score: float, clock: dict) -> dict:
    return {
        "title": candidate.get("title", ""),
        "url": candidate.get("url", ""),
        "snippet": candidate.get("description", ""),
        "published_at": _source_published_at(candidate),
        "domain": _domain_for_url(candidate.get("url", "")),
        "source_name": hint.get("source_name"),
        "source_type": hint.get("source_type"),
        "document_type": hint.get("document_type"),
        "relation": "upstream_primary_source",
        "matched_signal": hint.get("matched_signal"),
        "referenced_by": {
            "title": source_result.get("title", ""),
            "url": source_result.get("url", ""),
        },
        "chase_query": query,
        "match_score": score,
        "citation_quality": _citation_url_quality(candidate.get("url", "")),
        "freshness": _freshness_for_result(candidate, query, clock),
        "claim_label": _claim_label_for_result(candidate, clock),
    }


def _resolve_upstream_sources(
    api_key: str,
    selected_results: list[dict],
    original_query: str,
    clock: dict,
) -> tuple[dict[str, dict], list[dict], dict, list[str]]:
    """Chase detected source attributions back to official or primary records."""
    lookup: dict[str, dict] = {}
    pooled: list[dict] = []
    pooled_urls: set[str] = set()
    warnings: list[str] = []
    cache: dict[tuple[str, str], list[dict]] = {}
    chase_count = 0
    detected_count = 0
    resolved_hint_count = 0
    unresolved: list[dict] = []

    work_items: list[tuple[str, dict]] = []
    query_probe = {"title": original_query, "description": original_query, "url": ""}
    if _detect_upstream_source_hints(query_probe):
        work_items.append(("__query__", query_probe))
    for result in _dedupe_results(selected_results):
        key = _canonical_url(result.get("url", "")) or _normalised_title(result.get("title", ""))
        if key:
            work_items.append((key, result))

    for result_key, result in work_items:
        hints = _detect_upstream_source_hints(result)
        if not hints:
            continue
        detected_count += len(hints)
        entry = lookup.setdefault(result_key, {"hints": hints, "sources": []})
        result_domain = _domain_for_url(result.get("url", ""))

        for hint in hints:
            expected_domains = tuple(hint.get("official_domains", []))
            if result.get("url") and expected_domains and _domain_matches(result_domain, expected_domains):
                direct_score = 1.0
                direct = _compact_upstream_source(
                    result,
                    result,
                    hint,
                    "already on referenced primary domain",
                    direct_score,
                    clock,
                )
                direct["relation"] = "result_is_primary_source"
                entry["sources"].append(direct)
                resolved_hint_count += 1
                canonical = _canonical_url(direct.get("url", ""))
                if canonical and canonical not in pooled_urls:
                    pooled_urls.add(canonical)
                    pooled.append(direct)
                continue

            topic_key = " ".join(_upstream_topic_terms(result, limit=7))
            cache_key = (str(hint.get("hint_id", "")), topic_key)
            attempted_search = False
            if cache_key in cache:
                candidates = []
                for cached in cache[cache_key]:
                    rebound = dict(cached)
                    rebound["referenced_by"] = {
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                    }
                    rebound["matched_signal"] = hint.get("matched_signal")
                    candidates.append(rebound)
            elif chase_count >= MAX_UPSTREAM_CHASES:
                candidates = []
            else:
                attempted_search = True
                chase_query = _upstream_chase_query(result, hint)
                chase_count += 1
                try:
                    raw = _brave_results(
                        api_key,
                        chase_query,
                        UPSTREAM_SEARCH_RESULTS,
                        "py" if _wants_fresh_sources(original_query) else None,
                    )
                except SearchToolError as exc:
                    warnings.append(f"Upstream chase failed for {hint['source_name']}: {exc}")
                    raw = []
                ranked = []
                for candidate in _dedupe_results(raw):
                    score = _upstream_candidate_score(candidate, result, hint, clock)
                    if score >= 0.62:
                        ranked.append((score, candidate))
                ranked.sort(key=lambda pair: pair[0], reverse=True)
                chase_query = _upstream_chase_query(result, hint)
                candidates = [
                    _compact_upstream_source(candidate, result, hint, chase_query, score, clock)
                    for score, candidate in ranked[:MAX_UPSTREAM_SOURCES_PER_HINT]
                ]
                cache[cache_key] = candidates

            if candidates:
                entry["sources"].extend(candidates)
                resolved_hint_count += 1
                for source in candidates:
                    canonical = _canonical_url(source.get("url", ""))
                    if canonical and canonical not in pooled_urls:
                        pooled_urls.add(canonical)
                        pooled.append(source)
            else:
                reason = (
                    "upstream chase budget exhausted"
                    if not attempted_search and cache_key not in cache and chase_count >= MAX_UPSTREAM_CHASES
                    else "no sufficiently matching public primary document found"
                )
                unresolved.append(
                    {
                        "referenced_by": result.get("title", original_query),
                        "source_name": hint.get("source_name"),
                        "matched_signal": hint.get("matched_signal"),
                        "reason": reason,
                    }
                )

    summary = {
        "policy": (
            "When reporting names an agency, court, government body, regulator, or official record, "
            "search that institution's primary domain and prefer the resulting document for claims it directly supports."
        ),
        "detected_hint_count": detected_count,
        "resolved_hint_count": resolved_hint_count,
        "unresolved_hint_count": len(unresolved),
        "chase_queries_run": chase_count,
        "chase_query_limit": MAX_UPSTREAM_CHASES,
        "primary_source_count": len(pooled),
        "unresolved_hints": unresolved,
    }
    return lookup, pooled, summary, warnings


def _citation_url_quality(url: str) -> dict:
    domain = _domain_for_url(url)
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        parsed = urlparse("")
    lower_path = (parsed.path or "").lower()
    reasons: list[str] = []

    if not url or parsed.scheme not in ("http", "https") or not domain:
        reasons.append("missing_or_non_http_url")
    if _domain_matches(domain, BAD_CITATION_DOMAINS):
        reasons.append("search_or_aggregator_domain")
    if domain.endswith("allsides.com"):
        reasons.append("allsides_comparison_only_not_final_receipt")
    if lower_path in ("", "/"):
        reasons.append("homepage_url")
    if any(term in lower_path for term in BAD_CITATION_PATH_TERMS):
        reasons.append("section_archive_search_or_video_url")

    segments = [segment for segment in lower_path.split("/") if segment]
    if segments and segments[-1] in {"all", "latest", "news", "sport", "video", "videos"}:
        reasons.append("news_section_or_index_url")

    has_article_marker = any(
        marker in lower_path
        for marker in ("/article/", "/articles/", "/live-news/", "/live/", "/story/")
    )
    has_date_marker = bool(
        re.search(r"/20[0-9]{2}/[0-9]{1,2}/[0-9]{1,2}(?:/|$)", lower_path)
        or re.search(r"/20[0-9]{2}/[a-z]{3}/[0-9]{1,2}(?:/|$)", lower_path)
        or re.search(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", lower_path)
        or re.search(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*-[0-9]{1,2}-20[0-9]{2}", lower_path)
    )
    final_slug = segments[-1] if segments else ""
    has_article_slug = len(segments) >= 2 and len(final_slug) >= 18 and ("-" in final_slug or re.search(r"[0-9]", final_slug))

    if _domain_matches(domain, NEWS_ARTICLEISH_DOMAINS) and not (has_article_marker or has_date_marker or has_article_slug):
        reasons.append("known_news_domain_without_article_marker")
    if domain.endswith("theguardian.com") and not re.search(r"/20[0-9]{2}/[a-z]{3}/[0-9]{1,2}(?:/|$)", lower_path):
        reasons.append("guardian_section_or_home_url")
    if domain.endswith(("bbc.co.uk", "bbc.com")) and not (
        lower_path.startswith("/news/")
        or lower_path.startswith("/sport/")
        or lower_path.startswith("/weather/")
        or lower_path.startswith("/articles/")
    ):
        reasons.append("bbc_non_article_url")

    reasons = list(dict.fromkeys(reasons))
    return {"usable_as_final_citation": not reasons, "reasons": reasons, "domain": domain}


def _should_keep_current_news_result(result: dict, query: str, clock: dict) -> bool:
    if not _citation_url_quality(result.get("url", ""))["usable_as_final_citation"]:
        return False
    if not _wants_fresh_sources(query) and not _looks_like_news_query(query):
        return True

    age_days = _result_age_days(result, clock)
    if age_days is None or age_days <= NEWS_CURRENT_MAX_AGE_DAYS:
        return True
    wants_background = _contains_any(query, BACKGROUND_TERMS)
    is_background = _contains_any(_result_text(result), BACKGROUND_TERMS)
    return bool(wants_background and is_background and age_days <= NEWS_BACKGROUND_MAX_AGE_DAYS)


def _should_keep_allsides_context(result: dict, query: str, clock: dict) -> bool:
    if not _wants_fresh_sources(query):
        return True
    age_days = _result_age_days(result, clock)
    if age_days is None or age_days <= NEWS_CURRENT_MAX_AGE_DAYS:
        return True
    return bool(
        _contains_any(query, BACKGROUND_TERMS)
        and _contains_any(_result_text(result), BACKGROUND_TERMS)
        and age_days <= NEWS_BACKGROUND_MAX_AGE_DAYS
    )


def _claim_discipline_for_result(result: dict, query: str, clock: dict) -> dict:
    result_text = _result_text(result)
    age_days = _result_age_days(result, clock)
    current_news = _wants_fresh_sources(query) or _looks_like_news_query(query)
    wants_background = _contains_any(query, BACKGROUND_TERMS)
    is_background = _contains_any(result_text, BACKGROUND_TERMS)
    custody_required = _contains_any(result_text, CUSTODY_STATE_TERMS)
    return {
        "source_age_days": age_days,
        "source_age_unknown": age_days is None,
        "current_news_window_days": NEWS_CURRENT_MAX_AGE_DAYS if current_news else None,
        "usable_as_current_news": (
            not current_news
            or age_days is None
            or age_days <= NEWS_CURRENT_MAX_AGE_DAYS
            or (wants_background and is_background)
        ),
        "background_only": bool(current_news and age_days is not None and age_days > NEWS_CURRENT_MAX_AGE_DAYS),
        "event_date_required": _contains_any(result_text, EVENT_DATE_TERMS),
        "event_date_rule": "Separate the event date from the publication date.",
        "custody_state_required": custody_required,
        "custody_state_rule": "Use the newest verified arrest, charge, bail, release, or detention state.",
    }


def _source_reliability_rank(url: str) -> int:
    domain = _domain_for_url(url)
    if _domain_matches(domain, OFFICIAL_DOMAINS):
        return 0
    if _domain_matches(domain, REPUTABLE_REPORTING_DOMAINS):
        return 1
    return 2


def _custody_validation(api_key: str, result: dict, query: str, clock: dict) -> dict | None:
    discipline = _claim_discipline_for_result(result, query, clock)
    if not discipline["custody_state_required"]:
        return None

    title = str(result.get("title", "") or "").rsplit(" - ", 1)[0].strip()[:180]
    if not title:
        return None
    source_domain = _domain_for_url(result.get("url", ""))
    validation_query = f'"{title}" bail released custody charged latest'
    unknown_wording = "An arrest was reported; the current custody state was not verified."

    try:
        candidates = _brave_results(api_key, validation_query, 8, "pm")
    except SearchToolError as exc:
        return {
            "checked": False,
            "error": str(exc),
            "current_state": "unknown",
            "recommended_wording": unknown_wording,
            "rule": "Do not imply continued detention without current evidence.",
        }

    evidence: list[dict] = []
    for candidate in candidates:
        candidate_url = candidate.get("url", "") or ""
        if not _citation_url_quality(candidate_url)["usable_as_final_citation"]:
            continue
        similarity = _title_similarity(title, candidate.get("title", ""))
        if similarity < 0.32:
            continue
        text = _result_text(candidate)
        state = None
        matched = None
        if _contains_any(text, RELEASED_CUSTODY_TERMS):
            state = "released_or_bailed"
            matched = "release_or_bail_language"
        elif _contains_any(text, DETAINED_CUSTODY_TERMS):
            state = "detained_or_in_custody"
            matched = "detention_language"
        if not state:
            continue
        evidence.append(
            {
                "title": candidate.get("title", ""),
                "url": candidate_url,
                "snippet": candidate.get("description", ""),
                "age": candidate.get("age", ""),
                "source_age_days": _result_age_days(candidate, clock),
                "matched": matched,
                "state": state,
                "title_similarity": round(similarity, 3),
                "same_domain": bool(source_domain and _domain_for_url(candidate_url) == source_domain),
                "reliability_rank": _source_reliability_rank(candidate_url),
            }
        )

    evidence.sort(
        key=lambda item: (
            item["source_age_days"] if item["source_age_days"] is not None else 9999,
            item["reliability_rank"],
            not item["same_domain"],
            -item["title_similarity"],
        )
    )

    if not evidence:
        state = "unknown"
        wording = unknown_wording
    else:
        newest_age = evidence[0]["source_age_days"]
        newest = [item for item in evidence if item["source_age_days"] == newest_age]
        states = {item["state"] for item in newest}
        if len(states) > 1:
            state = "conflicting_current_reports"
            wording = "Current snippets conflict on custody status; attribute the status to the newest cited source."
        else:
            state = evidence[0]["state"]
            wording = (
                "The person was arrested and later released on bail/after questioning; do not imply continuing detention."
                if state == "released_or_bailed"
                else "The newest returned source says the person remains detained/in custody."
            )

    return {
        "checked": True,
        "query": validation_query,
        "current_state": state,
        "recommended_wording": wording,
        "evidence": evidence[:3],
        "rule": "Use the newest relevant evidence and preserve attribution when status is uncertain.",
    }


def _freshness_for_result(result: dict, query: str, clock: dict) -> dict:
    combined = "\n".join((str(query or ""), str(result.get("title", "") or ""), str(result.get("description", "") or "")))
    volatile = _contains_any(combined, VOLATILE_FACT_TERMS)
    relational = _contains_any(combined, RELATIONAL_FACT_TERMS)
    return {
        "as_of": clock["iso"],
        "volatile": volatile,
        "source_published_at": _source_published_at(result),
        "source_age": str(result.get("age", "") or "") or None,
        "recheck_before_publish": volatile or relational or _wants_fresh_sources(query),
        "same_record_validation": relational,
    }


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            return min(float(retry_after), 8.0)
    return min(0.75 * (2**attempt), 4.0)


def _request(method: str, url: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", USER_AGENT)
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    last_error: Exception | None = None

    for attempt in range(HTTP_RETRIES):
        response: requests.Response | None = None
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 >= HTTP_RETRIES:
                break
            time.sleep(_retry_delay(None, attempt))
            continue

        if response.status_code < 400:
            return response
        if response.status_code not in RETRYABLE_HTTP_STATUS or attempt + 1 >= HTTP_RETRIES:
            detail = " ".join(response.text[:240].split())
            raise SearchToolError(f"HTTP {response.status_code} from {_domain_for_url(url)}: {detail}")
        time.sleep(_retry_delay(response, attempt))

    raise SearchToolError(f"Request to {_domain_for_url(url)} failed: {last_error}")


def _request_json(method: str, url: str, **kwargs) -> dict:
    response = _request(method, url, **kwargs)
    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchToolError(f"Invalid JSON returned by {_domain_for_url(url)}") from exc
    if not isinstance(payload, dict):
        raise SearchToolError(f"Unexpected JSON shape returned by {_domain_for_url(url)}")
    return payload


def _brave_results(api_key: str, query: str, count: int, freshness: str | None) -> list[dict]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params: dict[str, object] = {"q": _clean_query(query), "count": max(1, min(int(count), 20))}
    if freshness:
        params["freshness"] = freshness
    payload = _request_json("GET", BRAVE_SEARCH_URL, headers=headers, params=params)
    results = payload.get("web", {}).get("results", [])
    if not isinstance(results, list):
        raise SearchToolError("Brave Search returned an unexpected results shape")
    return [item for item in results if isinstance(item, dict)]


def _local_news_location_query(query: str) -> str:
    cleaned = _clean_query(query)
    if not cleaned:
        return DEFAULT_LOCALITY
    if _contains_any(cleaned, ("near me", "around me", "in my area")):
        return f"{cleaned} {DEFAULT_LOCALITY}"

    generic_words = {
        "breaking", "current", "headlines", "latest", "local", "news",
        "now", "stories", "today", "top", "update",
    }
    meaningful = [token for token in re.findall(r"[a-z0-9]+", cleaned.lower()) if token not in generic_words]
    if not meaningful:
        return f"{cleaned} {DEFAULT_LOCALITY}"
    return cleaned


def _looks_like_active_event_query(query: str) -> bool:
    return _contains_any(_clean_query(query), ACTIVE_EVENT_TERMS)


def _google_news_results(
    api_key: str,
    query: str,
    count: int,
    clock: dict,
    *,
    window: str,
) -> list[dict]:
    """Discover current stories in Google News RSS, then resolve publisher URLs."""
    response = _request(
        "GET",
        GOOGLE_NEWS_RSS_URL,
        params={"q": f"{_clean_query(query)} when:{window}", "hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
    )
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise SearchToolError("Google News RSS returned malformed XML") from exc

    discovered = root.findall("./channel/item")[: max(count * 3, count)]
    resolved: list[dict] = []
    seen_urls: set[str] = set()
    for item in discovered:
        rss_title = (item.findtext("title") or "").strip()
        if not rss_title:
            continue
        title_parts = rss_title.rsplit(" - ", 1)
        article_title = title_parts[0].strip()
        publisher = title_parts[1].strip() if len(title_parts) == 2 else ""
        search = f'"{article_title}" {publisher}'.strip()
        candidates = _brave_results(api_key, search, 6, "pw")
        ranked = sorted(
            (
                (_title_similarity(article_title, candidate.get("title", "")), candidate)
                for candidate in candidates
                if _should_keep_current_news_result(candidate, query, clock)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.52:
            continue
        direct = dict(ranked[0][1])
        canonical = _canonical_url(direct.get("url", ""))
        if not canonical or canonical in seen_urls:
            continue
        pub_date = (item.findtext("pubDate") or "").strip()
        direct["google_news_discovered_title"] = rss_title
        direct["google_news_discovered_at"] = clock["iso"]
        direct["google_news_published_at"] = pub_date or None
        direct["resolver_title_similarity"] = round(ranked[0][0], 3)
        direct["discovery_provider"] = "Google News RSS"
        seen_urls.add(canonical)
        resolved.append(direct)
        if len(resolved) >= count:
            break
    return resolved


def _google_local_news_results(api_key: str, query: str, count: int, clock: dict) -> list[dict]:
    """Discover local stories in Google News RSS, then resolve publisher URLs."""
    return _google_news_results(
        api_key,
        _local_news_location_query(query),
        count,
        clock,
        window="7d",
    )


def _active_event_results(
    api_key: str,
    search_query: str,
    query: str,
    count: int,
    clock: dict,
) -> tuple[list[dict], int, list[str]]:
    """Find live blogs/trackers through Brave plus Google News discovery."""
    warnings: list[str] = []
    live_query = (
        f'{search_query} ("live updates" OR "live blog" OR '
        f'"minute by minute" OR "live coverage")'
    )
    brave_live = _brave_results(api_key, live_query, min(20, max(count * 3, 10)), "pd")
    brave_base = _brave_results(api_key, search_query, min(20, max(count * 2, 8)), "pd")
    google_live: list[dict] = []
    try:
        google_live = _google_news_results(
            api_key,
            f'{query} "live" OR "updates"',
            min(max(count, 3), 8),
            clock,
            window="1d",
        )
    except SearchToolError as exc:
        warnings.append(f"Google News live discovery failed: {exc}")

    candidates = [*google_live, *brave_live, *brave_base]
    candidates = [
        item
        for item in _dedupe_results(candidates)
        if _should_keep_current_news_result(item, query, clock)
    ]
    return _select_diverse_results(candidates, count), len(candidates), warnings


def _format_result(result: dict, query: str, clock: dict) -> dict:
    item = {
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "snippet": result.get("description", ""),
        "age": result.get("age", ""),
        "published_at": _source_published_at(result),
        "citation_quality": _citation_url_quality(result.get("url", "")),
        "freshness": _freshness_for_result(result, query, clock),
        "claim_discipline": _claim_discipline_for_result(result, query, clock),
        "political_bias": _allsides_bias_for_url(result.get("url", "")),
        "claim_label": _claim_label_for_result(result, clock),
    }
    if result.get("discovery_provider"):
        item["discovery"] = {
            "provider": result.get("discovery_provider"),
            "headline": result.get("google_news_discovered_title"),
            "discovered_at": result.get("google_news_discovered_at"),
            "published_at": result.get("google_news_published_at"),
            "resolver_title_similarity": result.get("resolver_title_similarity"),
        }
    return item


def _claim_label_for_result(result: dict, clock: dict) -> dict:
    title = result.get("title", "") or ""
    snippet = result.get("description", "") or ""
    claim_text = f"{title}\n{snippet}"
    domain = _domain_for_url(result.get("url", ""))
    source_relation = "general_web"
    label = "inference"
    reason = "A search snippet is discovery context; verify the exact claim before presenting it as fact."

    if _domain_matches(domain, OFFICIAL_DOMAINS):
        source_relation = "official_source"
        label = "confirmed"
        reason = "Official source; only treat the statement actually shown as confirmed."
    elif _domain_matches(domain, PRIMARY_DOCUMENT_DOMAINS):
        source_relation = "primary_document"
        label = "confirmed"
        reason = "Primary legal or legislative document repository; verify the exact passage before quoting it."
    elif _domain_matches(domain, REPUTABLE_REPORTING_DOMAINS):
        source_relation = "reputable_reporting"
        label = "credibly_reported"
        reason = "Reputable reporting, but not direct official confirmation."

    if _contains_any(claim_text, SPECULATION_TERMS):
        label = "rumour/speculation"
        reason = "The title or snippet contains explicit uncertainty, denial, or report-claim language."
    elif source_relation == "general_web" and _contains_any(
        claim_text,
        ("announced", "confirmed", "official statement", "according to the fia", "according to formula 1"),
    ):
        label = "credibly_reported"
        reason = "The snippet reports an announcement or statement; keep attribution unless independently confirmed."

    current_year = int(clock["year"])
    old_years = [year for year in _mentioned_years(claim_text) if year < current_year]
    stale_context = bool(old_years)
    if stale_context and label != "rumour/speculation":
        reason += f" It mentions older year(s) {old_years}; check whether that is background."

    return {
        "label": label,
        "source_relation": source_relation,
        "domain": domain,
        "stale_context_warning": stale_context,
        "reason": reason,
    }


def _looks_like_f1_schedule_query(query: str) -> bool:
    f1_terms = ("f1", "formula 1", "formula one", "grand prix", "grandprix")
    schedule_terms = ("calendar", "date", "dates", "event", "fixture", "next", "race", "schedule", "where", "when")
    return _contains_any(query, f1_terms) and _contains_any(query, schedule_terms)


def _extract_f1_api_key(page_text: str) -> str:
    patterns = (
        r'NEXT_PUBLIC_GLOBAL_EVENTTRACKER_APIKEY\\?":\\?"([^"\\]+)',
        r'NEXT_PUBLIC_GLOBAL_BROADCAST_APIKEY\\?":\\?"([^"\\]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, page_text)
        if match:
            return match.group(1)
    return F1_PUBLIC_API_KEY_FALLBACK


def _parse_f1_date(value: str) -> date:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise SearchToolError(f"Invalid Formula 1 event date: {value!r}") from exc


def _format_f1_date_range(event: dict) -> str:
    start = _parse_f1_date(event["meetingStartDate"])
    end = _parse_f1_date(event["meetingEndDate"])
    if start == end:
        return start.strftime("%d %B %Y")
    if start.month == end.month and start.year == end.year:
        return f"{start.day}-{end.day} {end.strftime('%B %Y')}"
    return f"{start.strftime('%d %B %Y')}-{end.strftime('%d %B %Y')}"


def _normalise_f1_event(event: dict) -> dict:
    event_url = str(event.get("url", "") or "")
    if event_url.startswith("http"):
        url = event_url
    else:
        url = f"https://www.formula1.com{event_url}"
    return {
        "event_name": event.get("meetingName", ""),
        "official_name": event.get("meetingOfficialName", ""),
        "date_range": _format_f1_date_range(event),
        "start_date": _parse_f1_date(event["meetingStartDate"]).isoformat(),
        "end_date": _parse_f1_date(event["meetingEndDate"]).isoformat(),
        "circuit": event.get("circuitOfficialName") or event.get("circuitShortName", ""),
        "location": event.get("circuitLocation") or event.get("meetingLocation", ""),
        "country": event.get("meetingCountryName", ""),
        "timezone": event.get("meetingTimezone", ""),
        "status": event.get("status", ""),
        "round": event.get("roundText", ""),
        "url": url,
        "source": "Formula 1 official calendar",
    }


def _fetch_f1_validated_schedule(clock: dict, limit: int = 5) -> dict | None:
    today = date.fromisoformat(clock["date"])
    checked_sources: list[str] = []
    errors: list[str] = []

    for year in (today.year, today.year + 1):
        page_url = F1_RACING_URL.format(year=year)
        checked_sources.append(page_url)
        page_text = ""
        try:
            page_text = _request("GET", page_url).text
        except SearchToolError as exc:
            errors.append(str(exc))
        api_key = _extract_f1_api_key(page_text)
        if not api_key:
            errors.append(f"No Formula 1 public API key found for {year}")
            continue

        api_url = f"{F1_EVENTS_API_URL}?season={year}"
        checked_sources.append(api_url)
        try:
            payload = _request_json(
                "GET",
                F1_EVENTS_API_URL,
                headers={"apikey": api_key, "Accept": "application/json"},
                params={"season": year},
            )
        except SearchToolError as exc:
            errors.append(str(exc))
            continue

        raw_events = payload.get("events", [])
        if not isinstance(raw_events, list):
            errors.append(f"Formula 1 events payload for {year} was not a list")
            continue

        events: list[dict] = []
        for event in raw_events:
            if not isinstance(event, dict) or event.get("isTestEvent"):
                continue
            if not event.get("meetingStartDate") or not event.get("meetingEndDate"):
                continue
            try:
                if _parse_f1_date(event["meetingEndDate"]) < today:
                    continue
            except SearchToolError:
                continue
            events.append(event)

        events.sort(key=lambda item: (_parse_f1_date(item["meetingStartDate"]), str(item.get("meetingKey", ""))))
        if events:
            upcoming = [_normalise_f1_event(event) for event in events[: max(1, min(limit, MAX_RESULTS))]]
            return {
                "ok": True,
                "kind": "official_schedule_validation",
                "sport": "Formula 1",
                "checked_sources": checked_sources,
                "errors": errors,
                "rule": "All linked event fields come from the same official calendar row.",
                "next_event": upcoming[0],
                "upcoming_events": upcoming,
            }
    return None


def _balanced_news_results(api_key: str, search_query: str, query: str, count: int, freshness: str | None, clock: dict) -> tuple[list[dict], dict]:
    if count < 2:
        fallback = _brave_results(api_key, search_query, count * 3, freshness)
        filtered = [item for item in fallback if _should_keep_current_news_result(item, query, clock)]
        return _select_diverse_results(filtered, count), {
            "requested": "50/50 left/right",
            "balanced": False,
            "fallback_used": True,
            "reason": "At least two results are required for a left/right pair.",
            "left": 0,
            "right": 0,
        }

    target = count if count % 2 == 0 else count - 1
    side_count = target // 2
    left_raw = _brave_results(api_key, f"{search_query} {_site_query(LEFT_NEWS_DOMAINS)}", 20, freshness)
    right_raw = _brave_results(api_key, f"{search_query} {_site_query(RIGHT_NEWS_DOMAINS)}", 20, freshness)
    left = _select_diverse_results(
        [item for item in left_raw if _allsides_bias_for_url(item.get("url", ""))["rating"] == "left" and _should_keep_current_news_result(item, query, clock)],
        side_count,
    )
    right = _select_diverse_results(
        [item for item in right_raw if _allsides_bias_for_url(item.get("url", ""))["rating"] == "right" and _should_keep_current_news_result(item, query, clock)],
        side_count,
    )
    actual = min(len(left), len(right))
    if actual:
        output: list[dict] = []
        for index in range(actual):
            output.extend((left[index], right[index]))
        return output, {
            "requested": "50/50 left/right",
            "balanced": True,
            "fallback_used": False,
            "left": actual,
            "right": actual,
            "requested_count": count,
            "returned_count": len(output),
            "odd_count_reduced": count % 2 == 1,
        }

    fallback = _brave_results(api_key, search_query, max(count * 3, 8), freshness)
    filtered = [item for item in fallback if _should_keep_current_news_result(item, query, clock)]
    output = _select_diverse_results(filtered, count)
    return output, {
        "requested": "50/50 left/right",
        "balanced": False,
        "fallback_used": True,
        "reason": "No valid left/right pair survived freshness and citation checks; returned clearly labelled general results instead.",
        "left": 0,
        "right": 0,
        "returned_count": len(output),
    }


def _source_summary(
    primary_items: list[dict],
    additional_items: list[dict],
    upstream_items: list[dict] | None = None,
) -> dict:
    upstream_items = upstream_items or []
    all_items = [*primary_items, *additional_items]
    domains = [item.get("claim_label", {}).get("domain") for item in all_items]
    domains = [domain for domain in domains if domain]
    labels: dict[str, int] = {}
    bias: dict[str, int] = {}
    for item in all_items:
        claim_label = item.get("claim_label", {}).get("label", "unknown")
        labels[claim_label] = labels.get(claim_label, 0) + 1
        rating = item.get("political_bias", {}).get("rating", "unknown")
        bias[rating] = bias.get(rating, 0) + 1
    return {
        "primary_count": len(primary_items),
        "additional_count": len(additional_items),
        "total_count": len(all_items) + len(upstream_items),
        "upstream_primary_count": len(upstream_items),
        "unique_domain_count": len(set(domains) | {item.get("domain") for item in upstream_items if item.get("domain")}),
        "domains": list(dict.fromkeys(domains)),
        "claim_labels": labels,
        "political_bias_buckets": bias,
    }


def _response_policy(is_news: bool, is_main_news: bool) -> dict:
    policy = {
        "links": "Use the exact returned publisher URL in clickable Markdown; reject results marked unusable_as_final_citation.",
        "claims": "Keep confirmed, credibly_reported, rumour/speculation, and inference distinct.",
        "freshness": f"For current news, prefer sources no older than {NEWS_CURRENT_MAX_AGE_DAYS} days; label older material as background.",
        "dates": "Separate event date from publication date and recheck volatile values immediately before answering.",
        "custody": "Use custody_validation when present; otherwise do not imply continued detention.",
        "additional_sources": "Use additional_sources for corroboration, competing framing, official context, or a second receipt. They are not ranked above results.",
        "upstream_sources": (
            "When upstream_source_hints or upstream_sources are present, prefer the primary document for claims it directly covers. "
            "Use the reporting article for narrative, reaction, or facts absent from the primary record. An unresolved hint is not confirmation."
        ),
    }
    if is_news:
        policy["bias"] = "Political-bias ratings describe outlet perspective, not whether an individual claim is true."
    if is_main_news:
        policy["balance"] = "Use paired left/right results when news_balance.balanced is true; disclose fallback when false."
        policy["allsides"] = "AllSides results are comparison context, never the final receipt for a current-event claim."
    return policy


def _error_payload(message: str, *, clock: dict | None = None) -> str:
    payload: dict[str, object] = {"ok": False, "tool_version": TOOL_VERSION, "error": message}
    if clock:
        payload["searched_at"] = clock
    return json.dumps(payload, ensure_ascii=False, indent=2)


class Tools:
    # Markdown publisher links are more useful than Open WebUI's extracted-text citation overlay.
    citation = False

    def search_web(self, query: str, count: int = DEFAULT_RESULTS) -> str:
        """Search the public web using Brave, with news freshness and source checks."""
        try:
            safe_count = max(1, min(int(count or DEFAULT_RESULTS), MAX_RESULTS))
        except (TypeError, ValueError):
            safe_count = DEFAULT_RESULTS

        clock = _current_time_context()
        cleaned_query = _clean_query(query)
        if not cleaned_query:
            return _error_payload("query must not be empty", clock=clock)

        api_key = _read_brave_key()
        if not api_key:
            return _error_payload(
                "missing Brave Search API key; set BRAVE_SEARCH_API_KEY or configure Open WebUI/OpenClaw",
                clock=clock,
            )

        search_query = _build_search_query(cleaned_query, clock)
        freshness = _freshness_filter(cleaned_query)
        is_news = _looks_like_news_query(cleaned_query)
        is_main_news = _looks_like_main_news_query(cleaned_query)
        is_local_news = _looks_like_local_news_query(cleaned_query)
        is_active_event = _looks_like_active_event_query(cleaned_query)
        additional_target = _additional_source_target(safe_count, local_news=is_local_news)
        expanded_target = safe_count + additional_target
        schedule_validation = None
        warnings: list[str] = []

        if _looks_like_f1_schedule_query(cleaned_query):
            try:
                schedule_validation = _fetch_f1_validated_schedule(clock, limit=safe_count)
                if schedule_validation and schedule_validation.get("ok"):
                    event_year = schedule_validation["next_event"]["start_date"][:4]
                    search_query = f"site:formula1.com/en/racing/{event_year} Formula 1 official calendar next race"
                    freshness = None
            except SearchToolError as exc:
                schedule_validation = {
                    "ok": False,
                    "kind": "official_schedule_validation",
                    "sport": "Formula 1",
                    "error": str(exc),
                }

        balance_summary = None
        allsides_items: list[dict] = []
        raw_results: list[dict] = []
        additional_raw: list[dict] = []
        candidate_pool_size = 0
        upstream_lookup: dict[str, dict] = {}
        upstream_sources: list[dict] = []
        upstream_resolution: dict = {}
        try:
            if is_active_event:
                selected, candidate_pool_size, live_warnings = _active_event_results(
                    api_key,
                    search_query,
                    cleaned_query,
                    expanded_target,
                    clock,
                )
                warnings.extend(live_warnings)
                raw_results = selected[:safe_count]
                additional_raw = selected[safe_count:expanded_target]
            elif is_local_news:
                selected = _google_local_news_results(
                    api_key, cleaned_query, expanded_target, clock
                )
                raw_results = selected[:safe_count]
                additional_raw = selected[safe_count:expanded_target]
                candidate_pool_size = len(selected)
            elif is_main_news:
                raw_results, balance_summary = _balanced_news_results(
                    api_key, search_query, cleaned_query, safe_count, freshness, clock
                )

                # Keep the balanced set pristine, but also return centre, wire,
                # official, and otherwise useful receipts as supporting context.
                supporting_candidates = _brave_results(
                    api_key,
                    search_query,
                    max(MIN_CANDIDATE_POOL, expanded_target * 3),
                    freshness,
                )
                supporting_candidates = [
                    item
                    for item in supporting_candidates
                    if _should_keep_current_news_result(item, cleaned_query, clock)
                ]
                supporting_candidates = _exclude_seen_results(
                    supporting_candidates, raw_results
                )
                additional_raw = _select_diverse_results(
                    supporting_candidates, additional_target
                )
                candidate_pool_size = len(supporting_candidates) + len(raw_results)
            else:
                candidates = _brave_results(
                    api_key,
                    search_query,
                    max(MIN_CANDIDATE_POOL, expanded_target * 3),
                    freshness,
                )
                candidate_pool_size = len(candidates)
                if is_news or _wants_fresh_sources(cleaned_query):
                    candidates = [
                        item
                        for item in candidates
                        if _should_keep_current_news_result(item, cleaned_query, clock)
                    ]
                selected = _select_diverse_results(candidates, expanded_target)
                raw_results = selected[:safe_count]
                additional_raw = selected[safe_count:expanded_target]

            # AllSides is comparison context, so provide enough rows to be useful
            # without allowing it to crowd out publisher receipts.
            if is_main_news:
                allsides_raw = _brave_results(
                    api_key,
                    f"site:allsides.com {search_query}",
                    min(5, safe_count),
                    freshness,
                )
                allsides_items = [
                    _format_result(item, cleaned_query, clock)
                    for item in allsides_raw
                    if _domain_matches(
                        _domain_for_url(item.get("url", "")), ("allsides.com",)
                    )
                    and _should_keep_allsides_context(item, cleaned_query, clock)
                ]
        except SearchToolError as exc:
            return _error_payload(str(exc), clock=clock)
        except Exception as exc:
            return _error_payload(
                f"unexpected search-tool failure: {type(exc).__name__}: {exc}",
                clock=clock,
            )

        try:
            upstream_lookup, upstream_sources, upstream_resolution, upstream_warnings = _resolve_upstream_sources(
                api_key,
                [*raw_results, *additional_raw],
                cleaned_query,
                clock,
            )
            warnings.extend(upstream_warnings)
        except Exception as exc:
            upstream_resolution = {
                "policy": "Primary-source chasing failed; do not silently upgrade secondary reporting.",
                "error": f"{type(exc).__name__}: {exc}",
                "detected_hint_count": 0,
                "resolved_hint_count": 0,
                "primary_source_count": 0,
            }
            warnings.append(f"Upstream primary-source resolution failed: {type(exc).__name__}: {exc}")

        items: list[dict] = []
        custody_checks = 0
        custody_cache: dict[str, dict | None] = {}
        for result in _dedupe_results(raw_results)[:safe_count]:
            item = _format_result(result, cleaned_query, clock)
            result_key = _canonical_url(result.get("url", "")) or _normalised_title(result.get("title", ""))
            upstream_entry = upstream_lookup.get(result_key)
            if upstream_entry:
                item["upstream_source_hints"] = upstream_entry.get("hints", [])
                item["upstream_sources"] = upstream_entry.get("sources", [])
                item["upstream_resolution_status"] = (
                    "resolved" if upstream_entry.get("sources") else "unresolved"
                )
            if item["claim_discipline"]["source_age_unknown"] and is_news:
                warnings.append(
                    f"Publication age was unavailable for: {item['title']}"
                )
            if (
                item["claim_discipline"]["custody_state_required"]
                and custody_checks < MAX_CUSTODY_VALIDATIONS
            ):
                cache_key = _normalised_title(result.get("title", ""))
                if cache_key not in custody_cache:
                    custody_cache[cache_key] = _custody_validation(
                        api_key, result, cleaned_query, clock
                    )
                    custody_checks += 1
                if custody_cache[cache_key]:
                    item["custody_validation"] = custody_cache[cache_key]
            items.append(item)

        additional_items: list[dict] = []
        for result in _dedupe_results(
            _exclude_seen_results(additional_raw, raw_results)
        )[:additional_target]:
            item = _format_result(result, cleaned_query, clock)
            result_key = _canonical_url(result.get("url", "")) or _normalised_title(result.get("title", ""))
            upstream_entry = upstream_lookup.get(result_key)
            if upstream_entry:
                item["upstream_source_hints"] = upstream_entry.get("hints", [])
                item["upstream_sources"] = upstream_entry.get("sources", [])
                item["upstream_resolution_status"] = (
                    "resolved" if upstream_entry.get("sources") else "unresolved"
                )
            additional_items.append(item)

        if not items:
            warnings.append(
                "No primary results survived the citation-quality and freshness filters."
            )
        if len(items) < safe_count:
            warnings.append(
                f"Requested {safe_count} primary sources but only {len(items)} survived filtering."
            )
        if len(additional_items) < additional_target:
            warnings.append(
                f"Requested {additional_target} additional sources but only {len(additional_items)} survived filtering."
            )
        if balance_summary and balance_summary.get("fallback_used"):
            warnings.append(
                str(
                    balance_summary.get(
                        "reason", "Balanced-news fallback was used."
                    )
                )
            )

        payload = {
            "ok": True,
            "tool_version": TOOL_VERSION,
            "provider": "brave",
            "discovery_provider": (
                "Brave Search + Google News RSS live discovery"
                if is_active_event
                else "Google News RSS + Brave resolver"
                if is_local_news
                else "Brave Search"
            ),
            "searched_at": clock,
            "mode": (
                "active_event"
                if is_active_event
                else "local_news"
                if is_local_news
                else "balanced_news"
                if is_main_news
                else "news"
                if is_news
                else "web"
            ),
            "original_query": cleaned_query,
            "query": search_query,
            "freshness": freshness,
            "schedule_validation": schedule_validation,
            "news_balance": balance_summary,
            "allsides_results": allsides_items,
            "source_expansion": {
                "default_primary_count": DEFAULT_RESULTS,
                "requested_primary_count": safe_count,
                "requested_additional_count": additional_target,
                "candidate_pool_size": candidate_pool_size,
                "primary_results_are_ranked": True,
                "additional_sources_role": (
                    "Corroboration, alternative framing, centre/wire reporting, or official context."
                ),
            },
            "source_summary": _source_summary(items, additional_items, upstream_sources),
            "upstream_source_resolution": upstream_resolution,
            "query_upstream_source_hints": upstream_lookup.get("__query__", {}).get("hints", []),
            "upstream_sources": upstream_sources,
            "warnings": list(dict.fromkeys(warnings)),
            "response_policy": _response_policy(is_news, is_main_news),
            "results": items,
            "additional_sources": additional_items,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
