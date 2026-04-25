import os
import re
import sqlite3
import datetime
import requests
import vault
from config import get_logger, MEMORY_ARCHIVE_PATH, SEARCH_DAILY_LIMITS
from errors import Result

log = get_logger("search")

def _init_usage_db():
    try:
        conn = sqlite3.connect(MEMORY_ARCHIVE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                provider TEXT PRIMARY KEY,
                date TEXT,
                call_count INTEGER
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to init usage DB: {e}")

_init_usage_db()

_daily_search_calls = {}

def _reset_daily_if_needed():
    global _daily_search_calls
    today = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(MEMORY_ARCHIVE_PATH)
        cursor = conn.cursor()
        
        for provider in SEARCH_DAILY_LIMITS:
            cursor.execute("SELECT date, call_count FROM api_usage WHERE provider = ?", (provider,))
            row = cursor.fetchone()
            if not row or row[0] != today:
                cursor.execute("""
                    INSERT OR REPLACE INTO api_usage (provider, date, call_count)
                    VALUES (?, ?, ?)
                """, (provider, today, 0))
                _daily_search_calls[provider] = 0
            else:
                _daily_search_calls[provider] = row[1]
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to check usage DB: {e}")

def _check_quota(provider: str) -> bool:
    _reset_daily_if_needed()
    used = _daily_search_calls.get(provider, 0)
    limit = SEARCH_DAILY_LIMITS.get(provider, 9999)
    return used < limit

def _track_usage(provider: str):
    _reset_daily_if_needed()
    _daily_search_calls[provider] = _daily_search_calls.get(provider, 0) + 1
    today = datetime.date.today().isoformat()
    try:
        conn = sqlite3.connect(MEMORY_ARCHIVE_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE api_usage SET call_count = ? WHERE provider = ? AND date = ?
        """, (_daily_search_calls[provider], provider, today))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to update search usage DB: {e}")

def classify_search_query(query: str) -> str:
    query_lower = query.lower()
    
    news_pattern = r"\b(latest|breaking|today|yesterday|current|now|2026|price of|score|match|election|stock|weather|happened|announced|released)\b"
    research_pattern = r"\b(how does|explain|what is|why does|difference between|compare|history of|paper|study|research|deep dive|analysis|tutorial|guide|learn)\b"
    
    if re.search(news_pattern, query_lower):
        return "news"
    elif re.search(research_pattern, query_lower):
        return "research"
    else:
        return "general"

def _search_serper(query, num_results=5):
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": vault.get_secret("SERPER_API_KEY", "") or os.getenv("SERPER_API_KEY", ""),
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": num_results}
        response = requests.post(url, headers=headers, json=payload, timeout=8)
        response.raise_for_status()
        data = response.json()
        
        normalized = []
        for r in data.get("organic", [])[:num_results]:
            normalized.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", "")
            })
        return normalized if normalized else None
    except Exception as e:
        log.error(f"Serper search failed: {e}")
        return None

def _search_exa(query, num_results=5):
    try:
        url = "https://api.exa.ai/search"
        headers = {
            "x-api-key": vault.get_secret("EXA_API_KEY", "") or os.getenv("EXA_API_KEY", ""),
            "Content-Type": "application/json"
        }
        payload = {"query": query, "numResults": num_results, "useAutoprompt": True}
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        normalized = []
        for r in data.get("results", [])[:num_results]:
            normalized.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("text", "") or r.get("snippet", "") or r.get("url", "")
            })
        return normalized if normalized else None
    except Exception as e:
        log.error(f"Exa search failed: {e}")
        return None

def _search_tavily(query, num_results=5):
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": vault.get_secret("TAVILY_API_KEY", "") or os.getenv("TAVILY_API_KEY", ""),
            "query": query,
            "max_results": num_results,
            "search_depth": "basic"
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        normalized = []
        for r in data.get("results", [])[:num_results]:
            normalized.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")
            })
        return normalized if normalized else None
    except Exception as e:
        log.error(f"Tavily search failed: {e}")
        return None

def _search_searxng(query, num_results=5):
    """Search via local SearXNG instance."""
    from config import SEARXNG_URL
    try:
        params = {"q": query, "format": "json", "engines": "google,bing,duckduckgo"}
        response = requests.get(SEARXNG_URL, params=params, timeout=10, headers={
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1"
        })
        if response.status_code != 200:
            log.warning(f"SearXNG returned {response.status_code}")
            return None
        data = response.json()
        results = []
        for r in data.get("results", [])[:num_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")
            })
        return results if results else None
    except Exception as e:
        log.error(f"SearXNG search failed: {e}")
        return None

def _search_duckduckgo(query, num_results=5):
    """Search via official ddgs package for robust results."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            # Return standard web results (up to num_results)
            web_results = list(ddgs.text(query, max_results=max(num_results, 5)))
            results = []
            for r in web_results:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
            
            if results:
                return results[:num_results]
        
        return None
    except Exception as e:
        log.error(f"DuckDuckGo search failed: {e}")
        return None

def format_results(results):
    if not results:
        return "No results found."
    output = ""
    for i, r in enumerate(results, 1):
        if "error" in r:
            return f"Search error: {r['error']}"
        output += f"{i}. {r['title']}\n   {r['snippet']}\n   {r['url']}\n\n"
    return output.strip()

def get_search_status() -> dict:
    _reset_daily_if_needed()
    status = {}
    for provider, limit in SEARCH_DAILY_LIMITS.items():
        used = _daily_search_calls.get(provider, 0)
        status[provider] = {
            "used": used,
            "limit": limit,
            "ok": used < limit
        }
    return status

def web_search(query, num_results=5) -> Result:
    """Search the web. Returns Result[list] with normalized result dicts."""
    try:
        query_type = classify_search_query(query)

        if query_type == "news":
            primary, secondary = "serper", "tavily"
        elif query_type == "research":
            primary, secondary = "exa", "tavily"
        else:
            primary, secondary = "tavily", "serper"

        for provider in (primary, secondary):
            if _check_quota(provider):
                func = globals().get(f"_search_{provider}")
                if func:
                    results = func(query, num_results)
                    if results:
                        _track_usage(provider)
                        log.info(f"Search via {provider} [{query_type}]: {query[:50]}")
                        return Result.success(results)

        log.warning("All paid providers failed/quota, using SearXNG")
        results = _search_searxng(query, num_results)
        if results:
            return Result.success(results)

        results = _search_duckduckgo(query, num_results)
        if results:
            return Result.success(results)

        return Result.failure("All search providers exhausted with no results.", error_type="connection")
    except Exception as e:
        log.error(f"web_search failed: {e}")
        return Result.from_exception(e)
