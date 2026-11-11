"""LLM access layer shared by all agents.

Responsibilities:

* provider-agnostic chat model factory (Groq by default, Ollama / Anthropic / OpenAI optional),
* token-aware rate limiting per model (free tiers are limited in tokens per minute),
* automatic back-off on HTTP 429,
* structured (Pydantic-validated) outputs with self-repair on invalid JSON,
* a deterministic on-disk cache: the same prompt on the same model is answered once,
  which makes re-runs free and reproducible,
* full tracing of every call (prompt, response, tokens, latency) into the run directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from .audit import AuditLog
from .config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """A call failed in a way the calling agent may handle (e.g. skip one record)."""


class QuotaExhausted(RuntimeError):
    """The provider's daily quota is used up.

    Deliberately not an LLMError: agents must not swallow it and carry on with
    degraded results. It stops the stage; the run is resumed later with
    `sysrev resume RUN_ID` and everything already done is served from the cache.
    """



def estimate_tokens(text: str) -> int:
    return int(len(text) / 3.6) + 8


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Sliding 60-second window on tokens and requests for one model."""

    def __init__(self, tokens_per_minute: int, requests_per_minute: int):
        self.tpm, self.rpm = tokens_per_minute, requests_per_minute
        self._events: list[tuple[float, int]] = []
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self, tokens: int) -> float:
        """Block until `tokens` fit in the window. Returns the seconds waited."""
        tokens = min(tokens, self.tpm)
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._events = [(t, n) for t, n in self._events if now - t < 60]
                used = sum(n for _, n in self._events)
                if now >= self._blocked_until and used + tokens <= self.tpm and len(self._events) < self.rpm:
                    self._events.append((now, tokens))
                    return waited
                pause = max(self._blocked_until - now, 0.5)
                if self._events and (used + tokens > self.tpm or len(self._events) >= self.rpm):
                    pause = max(pause, 60 - (now - self._events[0][0]) + 0.05)
            pause = min(pause, 20)
            time.sleep(pause)
            waited += pause

    def correct(self, estimated: int, actual: int) -> None:
        """Replace the estimate of the latest call by the real usage."""
        with self._lock:
            for i in range(len(self._events) - 1, -1, -1):
                if self._events[i][1] == min(estimated, self.tpm):
                    self._events[i] = (self._events[i][0], actual)
                    break

    def block(self, seconds: float) -> None:
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


class DiskCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute("CREATE TABLE IF NOT EXISTS llm (key TEXT PRIMARY KEY, model TEXT, response TEXT, created REAL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS usage (ts REAL, model TEXT, tokens INTEGER)")
        self._db.commit()

    def record_usage(self, model: str, tokens: int, ts: float | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT INTO usage VALUES (?, ?, ?)", (ts or time.time(), model, tokens))
            self._db.commit()

    def usage_last_24h(self) -> dict[str, dict[str, int]]:
        """Tokens and requests really sent to the provider over the last 24 hours, per model."""
        with self._lock:
            rows = self._db.execute(
                "SELECT model, COUNT(*), SUM(tokens) FROM usage WHERE ts > ? GROUP BY model", (time.time() - 86400,)
            ).fetchall()
        return {model: {"requests": n, "tokens": total or 0} for model, n, total in rows}

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT response FROM llm WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, model: str, response: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO llm VALUES (?, ?, ?, ?)", (key, model, response, time.time()))
            self._db.commit()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def scrub(text: str) -> str:
    """Remove account identifiers and key fragments that providers echo in error messages."""
    text = re.sub(r"\borg_[A-Za-z0-9]{12,}", "org_<redacted>", text)
    # API keys only: a provider prefix followed by a long run of letters AND digits, at a word start
    return re.sub(r"\b(?:gsk_|sk-(?:ant-|proj-)?)(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{16,}", "<redacted-key>", text)


def _retry_after(exc: Exception) -> float | None:
    """Seconds to wait if `exc` is a rate-limit error, else None."""
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    text = str(exc)
    if status != 429 and "rate limit" not in text.lower() and "429" not in text:
        return None
    headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
    value = headers.get("retry-after")
    if value:
        try:
            return float(value) + 0.5
        except ValueError:
            pass
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", text)
    if match:
        return int(match.group(1) or 0) * 60 + float(match.group(2)) + 0.5
    return 15.0


def extract_json(text: str) -> str:
    """Strip reasoning tags / code fences and return the outermost JSON object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def schema_text(schema: type[BaseModel]) -> str:
    """Compact, commented rendering of a Pydantic schema.

    A raw JSON Schema costs 2-3 times more prompt tokens for the same information,
    which matters when every call is counted against a daily token quota.
    """
    root = schema.model_json_schema()
    defs = root.get("$defs", {})

    def render(node: dict, depth: int) -> str:
        if "$ref" in node:
            node = defs[node["$ref"].rsplit("/", 1)[-1]]
        if "enum" in node:
            return " | ".join(json.dumps(value) for value in node["enum"])
        if "const" in node:
            return json.dumps(node["const"])
        if "anyOf" in node:
            return " | ".join(render(option, depth) for option in node["anyOf"])
        kind = node.get("type")
        if kind == "object":
            if "properties" not in node:
                return "{<key>: " + render(node.get("additionalProperties") or {"type": "string"}, depth) + "}"
            pad = "  " * (depth + 1)
            lines = []
            for name, prop in node["properties"].items():
                comment = prop.get("description", "")
                lines.append(f'{pad}"{name}": {render(prop, depth + 1)},' + (f"  // {comment}" if comment else ""))
            return "{\n" + "\n".join(lines) + "\n" + "  " * depth + "}"
        if kind == "array":
            return "[" + render(node.get("items", {}), depth) + ", ...]"
        return {"string": "string", "integer": "integer", "number": "number", "boolean": "true | false", "null": "null"}.get(kind, "any")

    return render(root, 0)


def _text_of(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #


class LLM:
    def __init__(self, settings: Settings, audit: AuditLog | None = None, trace_file: Path | None = None):
        self.settings = settings
        self.audit = audit
        self.trace_file = trace_file
        self.cache = DiskCache(settings.cache_dir / "llm_cache.sqlite")
        self._limiters: dict[str, RateLimiter] = {}
        self._models: dict[tuple, BaseChatModel] = {}
        self._lock = threading.Lock()
        self._trace_lock = threading.Lock()
        self.usage = {"calls": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0}

    # -- factory ------------------------------------------------------------ #
    def chat_model(self, role: str, temperature: float = 0.0, max_tokens: int = 1500, json_mode: bool = False) -> BaseChatModel:
        """LangChain chat model for a role ('primary' | 'secondary' | 'fast')."""
        name = self.settings.model_for(role)
        key = (name, temperature, max_tokens, json_mode)
        with self._lock:
            if key not in self._models:
                self._models[key] = self._build(name, temperature, max_tokens, json_mode)
            return self._models[key]

    def _build(self, name: str, temperature: float, max_tokens: int, json_mode: bool) -> BaseChatModel:
        provider = self.settings.llm_provider
        if provider == "groq":
            from langchain_groq import ChatGroq

            if not self.settings.groq_api_key:
                raise LLMError("GROQ_API_KEY is missing. Copy .env.example to .env and add your key.")
            kwargs: dict[str, Any] = {}
            if "gpt-oss" in name:
                kwargs["reasoning_effort"] = "low"
            model_kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
            return ChatGroq(
                model=name, temperature=temperature, max_tokens=max_tokens, max_retries=0,
                api_key=self.settings.groq_api_key, model_kwargs=model_kwargs, **kwargs,
            )
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=name, temperature=temperature, num_predict=max_tokens,
                base_url=self.settings.ollama_base_url, format="json" if json_mode else None,
            )
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic  # pip install langchain-anthropic

            return ChatAnthropic(model=name, temperature=temperature, max_tokens=max_tokens,
                                 api_key=self.settings.anthropic_api_key)
        if provider == "openai":
            from langchain_openai import ChatOpenAI  # pip install langchain-openai

            model_kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
            return ChatOpenAI(model=name, temperature=temperature, max_tokens=max_tokens,
                              api_key=self.settings.openai_api_key, model_kwargs=model_kwargs)
        raise LLMError(f"Unknown LLM_PROVIDER '{provider}'")

    def limiter(self, role: str) -> RateLimiter:
        name = self.settings.model_for(role)
        with self._lock:
            if name not in self._limiters:
                self._limiters[name] = RateLimiter(self.settings.tokens_per_minute, self.settings.requests_per_minute)
            return self._limiters[name]

    # -- low-level call with rate limiting and retries ------------------------ #
    def invoke(self, role: str, messages: list[BaseMessage], *, agent: str, model: BaseChatModel | None = None,
               max_tokens: int = 1500, temperature: float = 0.0, json_mode: bool = False) -> AIMessage:
        """Rate-limited call. `model` may be a tool-bound variant of the role's model."""
        model = model or self.chat_model(role, temperature, max_tokens, json_mode)
        limiter = self.limiter(role)
        prompt_text = "\n".join(_text_of(m) if isinstance(m, AIMessage) else str(m.content) for m in messages)
        estimate = estimate_tokens(prompt_text) + int(max_tokens * 0.6)
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_max_retries):
            limiter.acquire(estimate)
            started = time.perf_counter()
            try:
                reply = model.invoke(messages)
            except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
                last_error = exc
                wait = _retry_after(exc)
                if wait is not None:
                    self._audit(agent, "llm_rate_limited", role=role, wait_seconds=round(wait, 1), message=scrub(str(exc))[:300])
                    if wait > self.settings.llm_max_wait_seconds:
                        raise QuotaExhausted(
                            f"Quota exhausted for {self.settings.model_for(role)}: the provider asks to wait "
                            f"{wait / 60:.0f} min. Resume the run later; completed work is cached. ({scrub(str(exc))[:200]})"
                        ) from exc
                    limiter.block(wait)
                    continue
                if attempt + 1 < self.settings.llm_max_retries and _is_transient(exc):
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(scrub(f"{type(exc).__name__}: {exc}")) from exc
            seconds = time.perf_counter() - started
            usage = reply.usage_metadata or {}
            tokens_in = usage.get("input_tokens", estimate_tokens(prompt_text))
            tokens_out = usage.get("output_tokens", estimate_tokens(_text_of(reply)))
            limiter.correct(estimate, tokens_in + tokens_out)
            self.cache.record_usage(self.settings.model_for(role), tokens_in + tokens_out)
            with self._lock:
                self.usage["calls"] += 1
                self.usage["input_tokens"] += tokens_in
                self.usage["output_tokens"] += tokens_out
                self.usage["seconds"] += seconds
            self._trace(agent, role, prompt_text, reply, tokens_in, tokens_out, seconds, cached=False)
            return reply
        raise LLMError(f"Rate limit not cleared after {self.settings.llm_max_retries} attempts: {last_error}")

    # -- high-level helpers --------------------------------------------------- #
    def text(self, role: str, system: str, user: str, *, agent: str, max_tokens: int = 1500,
             temperature: float = 0.0, cache: bool = True) -> str:
        key = self._key(role, system, user, "text", temperature)
        if cache and (hit := self.cache.get(key)) is not None:
            self._cached(agent, role, system + "\n" + user, hit)
            return hit
        reply = self.invoke(role, [SystemMessage(system), HumanMessage(user)], agent=agent,
                            max_tokens=max_tokens, temperature=temperature)
        out = re.sub(r"<think>.*?</think>", "", _text_of(reply), flags=re.S).strip()
        if cache:
            self.cache.put(key, self.settings.model_for(role), out)
        return out

    def structured(self, role: str, system: str, user: str, schema: type[T], *, agent: str,
                   max_tokens: int = 1500, temperature: float = 0.0, cache: bool = True) -> T:
        """Return an instance of `schema`, validated. Invalid JSON is sent back for repair."""
        full_system = (
            f"{system}\n\nReply with ONE JSON object and nothing else, with exactly this structure "
            f"(comments describe the fields; do not output comments):\n{schema_text(schema)}"
        )
        key = self._key(role, full_system, user, schema.__name__, temperature)
        if cache and (hit := self.cache.get(key)) is not None:
            try:
                parsed = schema.model_validate_json(hit)
                self._cached(agent, role, full_system + "\n" + user, hit)
                return parsed
            except ValidationError:
                pass
        messages: list[BaseMessage] = [SystemMessage(full_system), HumanMessage(user)]
        error = ""
        json_mode = True
        for _ in range(4):
            try:
                reply = self.invoke(role, messages, agent=agent, max_tokens=max_tokens,
                                    temperature=temperature, json_mode=json_mode)
            except LLMError as exc:
                # The provider's JSON mode rejects a reply it cannot parse (often one cut off by the
                # token limit). Ask again without JSON mode and with more room; we parse it ourselves.
                if json_mode and ("generate JSON" in str(exc) or "json_validate_failed" in str(exc)):
                    self._audit(agent, "json_mode_fallback", role=role)
                    json_mode, max_tokens = False, int(max_tokens * 1.5)
                    error = str(exc)[:200]
                    continue
                raise
            raw = extract_json(_text_of(reply))
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as exc:
                error = str(exc)[:600]
                messages = messages[:2] + [
                    AIMessage(raw[:1500]),
                    HumanMessage(f"That JSON is invalid:\n{error}\nReturn the corrected JSON object only."),
                ]
                continue
            if cache:
                self.cache.put(key, self.settings.model_for(role), parsed.model_dump_json())
            return parsed
        raise LLMError(f"{schema.__name__}: model did not return valid JSON after 4 attempts. {error}")

    # -- bookkeeping ---------------------------------------------------------- #
    def _key(self, role: str, system: str, user: str, kind: str, temperature: float) -> str:
        payload = "\x1f".join([self.settings.model_for(role), kind, str(temperature), system, user])
        return hashlib.sha256(payload.encode()).hexdigest()

    def _audit(self, agent: str, action: str, **payload: Any) -> None:
        if self.audit:
            self.audit.log(agent, action, **payload)

    def _cached(self, agent: str, role: str, prompt: str, response: str) -> None:
        with self._lock:
            self.usage["calls"] += 1
            self.usage["cached"] += 1
        self._trace(agent, role, prompt, response, 0, 0, 0.0, cached=True)

    def _trace(self, agent: str, role: str, prompt: str, reply: AIMessage | str, tokens_in: int,
               tokens_out: int, seconds: float, cached: bool) -> None:
        if not self.trace_file:
            return
        response = reply if isinstance(reply, str) else _text_of(reply)
        tool_calls = [] if isinstance(reply, str) else (reply.tool_calls or [])
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": agent,
            "model": self.settings.model_for(role),
            "cached": cached,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "seconds": round(seconds, 2),
            "prompt": prompt,
            "response": response,
            "tool_calls": tool_calls,
        }
        with self._trace_lock, self.trace_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    return (isinstance(status, int) and status >= 500) or "timeout" in name or "connection" in name
