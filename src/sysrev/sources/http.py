"""Polite HTTP client shared by all literature connectors.

* per-host minimum delay between calls (each API publishes its own etiquette),
* retry with exponential backoff on 429 / 5xx,
* optional on-disk cache so that a search can be replayed exactly (reproducibility)
  and so that free API budgets are not spent twice.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

USER_AGENT = "sysrev-agents/0.1 (systematic review research pipeline)"

# seconds between two calls to the same host
MIN_DELAY = {
    "eutils.ncbi.nlm.nih.gov": 0.4,
    "export.arxiv.org": 3.1,
    "api.semanticscholar.org": 1.2,
    "api.openalex.org": 0.15,
    "www.ebi.ac.uk": 0.15,
}

_last_call: dict[str, float] = {}
_lock = threading.Lock()


class SourceError(RuntimeError):
    pass


def _throttle(host: str) -> None:
    delay = MIN_DELAY.get(host, 0.1)
    with _lock:
        wait = _last_call.get(host, 0.0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def _cache_file(cache_dir: Path, url: str, params: dict | None) -> Path:
    # API keys must not influence the cache key, nor be written to disk.
    safe = {k: v for k, v in sorted((params or {}).items()) if k not in {"api_key", "email", "mailto"}}
    digest = hashlib.sha256((url + json.dumps(safe, sort_keys=True)).encode()).hexdigest()[:32]
    return cache_dir / "http" / f"{digest}.txt"


def get_text(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    cache_dir: Path | None = None,
    retries: int = 4,
    timeout: float = 45.0,
) -> str:
    if cache_dir is not None:
        cached = _cache_file(cache_dir, url, params)
        if cached.exists():
            return cached.read_text(encoding="utf-8")

    host = urlparse(url).netloc
    last_error = ""
    for attempt in range(retries):
        _throttle(host)
        try:
            response = httpx.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
                timeout=timeout,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2**attempt)
            continue
        if response.status_code == 200:
            if cache_dir is not None:
                cached = _cache_file(cache_dir, url, params)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(response.text, encoding="utf-8")
            return response.text
        last_error = f"HTTP {response.status_code}"
        if response.status_code in (429, 500, 502, 503, 504):
            retry_after = response.headers.get("retry-after")
            pause = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
            time.sleep(min(pause, 30))
            continue
        break
    raise SourceError(f"{host}: {last_error}")


def get_json(url: str, params: dict | None = None, **kwargs) -> dict:
    return json.loads(get_text(url, params, **kwargs))


def get_bytes(url: str, timeout: float = 60.0, max_bytes: int = 40_000_000) -> bytes | None:
    """Download a binary file (PDF). Returns None on any failure."""
    host = urlparse(url).netloc
    _throttle(host)
    try:
        with httpx.stream(
            "GET", url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
        ) as response:
            if response.status_code != 200:
                return None
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError:
        return None
