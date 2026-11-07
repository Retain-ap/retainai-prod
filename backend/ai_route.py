"""The one AI route RetainAI uses: a fixed model at a fixed provider.

Every AI request goes to OpenRouter's chat completions endpoint for
``openai/gpt-4.1-mini`` and may be served only by OpenAI (provider slug
``openai``). Nothing in configuration, the environment or a caller can change
the model, the provider, or turn fallbacks on: the request is built here from
constants and checked again before it is sent.

Routing constraints (OpenRouter provider-selection docs, read November 7, 2026):

* ``only: ["openai"]`` and ``order: ["openai"]`` with ``allow_fallbacks: false``:
  OpenRouter may not use any other provider (Azure also serves this model; it is
  excluded) and returns the upstream error instead of falling back.
* No ``models`` list and no ``openrouter/auto``: no model fallback.
* ``data_collection: "deny"``: only providers that don't collect request data.
* ``require_parameters: true``: the provider must support every parameter sent.
  OpenAI's endpoint lists ``max_tokens`` and ``temperature``.
* ``max_price`` in USD per million tokens: prompt 0.40, completion 1.60, OpenAI's
  listed price for this model (0.0000004 / 0.0000016 USD per token). A price
  rise means no eligible route, and the request fails instead of costing more.

If no endpoint meets all of this, OpenRouter answers with an error (503 "no
available model provider that meets your routing requirements") and RetainAI
reports that AI drafting is unavailable. Manual messages keep working.

Zero data retention is NOT requested or claimed: OpenRouter lists first-party
OpenAI endpoints as outside ZDR, and its ``zdr`` flag can admit "Safety
Retention" endpoints for self-serve accounts. The guarantee here is the fixed
recipient and the no-collection routing filter.

Nothing in this module logs prompts, responses or keys.
"""

from __future__ import annotations

import math
import re

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-4.1-mini"
PROVIDER_SLUG = "openai"
PROVIDER_NAME = "OpenAI"
# OpenRouter's max_price unit is USD per million tokens.
MAX_PRICE_PER_MILLION_TOKENS = (("prompt", 0.4), ("completion", 1.6))

MIN_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS = 16, 600
MAX_MESSAGES = 4
MAX_PROMPT_CHARS = 24000
ROLES = ("system", "user", "assistant")
MAX_ATTEMPTS = 2
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_WAIT_SECONDS = 2.0
REQUEST_KEYS = frozenset({"model", "messages", "max_tokens", "temperature", "provider"})
# OpenRouter may report the dated snapshot it served, e.g. openai/gpt-4.1-mini-2025-04-14.
_RESPONSE_MODEL = re.compile(r"openai/gpt-4\.1-mini(?:-\d{4}-\d{2}-\d{2})?")


class RouteError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def provider_preferences():
    """A fresh copy every time, so nothing can mutate a shared default."""
    return {
        "only": [PROVIDER_SLUG],
        "order": [PROVIDER_SLUG],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "max_price": dict(MAX_PRICE_PER_MILLION_TOKENS),
    }


def _messages(messages):
    if not isinstance(messages, (list, tuple)) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise RouteError("invalid_messages")
    cleaned, total = [], 0
    for message in messages:
        if not isinstance(message, dict):
            raise RouteError("invalid_messages")
        role, content = message.get("role"), message.get("content")
        if role not in ROLES or not isinstance(content, str) or not content.strip():
            raise RouteError("invalid_messages")
        total += len(content)
        # Only role and content are forwarded; any other key a caller adds is dropped.
        cleaned.append({"role": role, "content": content})
    if total > MAX_PROMPT_CHARS:
        raise RouteError("prompt_too_long")
    return cleaned


def build_request(messages, *, max_tokens, temperature):
    try:
        tokens = int(max_tokens)
        temp = float(temperature)
    except (TypeError, ValueError):
        raise RouteError("invalid_parameters") from None
    if not math.isfinite(temp):
        raise RouteError("invalid_parameters")
    payload = {
        "model": MODEL,
        "messages": _messages(messages),
        "max_tokens": max(MIN_OUTPUT_TOKENS, min(tokens, MAX_OUTPUT_TOKENS)),
        "temperature": max(0.0, min(temp, 1.0)),
        "provider": provider_preferences(),
    }
    assert_fixed(payload)
    return payload


def assert_fixed(payload):
    """The last check before anything is sent: exactly the fixed route, no extras."""
    if (not isinstance(payload, dict) or set(payload) != REQUEST_KEYS or payload.get("model") != MODEL
            or payload.get("provider") != provider_preferences()):
        raise RouteError("route_not_fixed")


def response_text(body):
    """The draft text, only if the answer came from the fixed model and provider."""
    if not isinstance(body, dict):
        raise RouteError("invalid_response")
    model = body.get("model")
    if not isinstance(model, str) or not _RESPONSE_MODEL.fullmatch(model.strip()):
        raise RouteError("unexpected_model")
    provider = body.get("provider")
    # OpenRouter's response schema doesn't require ``provider``; when it is
    # present it must be OpenAI.
    if provider is not None and (not isinstance(provider, str) or provider.strip().lower() != PROVIDER_NAME.lower()):
        raise RouteError("unexpected_provider")
    if body.get("error"):
        raise RouteError("provider_error")
    choices = body.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if choice.get("finish_reason") == "error" or not isinstance(content, str) or not content.strip():
        raise RouteError("empty_response")
    return content


def _error_summary(status, body):
    summary = {"error": "ai_route_unavailable", "status": int(status)}
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        if isinstance(code, (str, int)) and not isinstance(code, bool):
            summary["code"] = str(code)[:80]
    return summary


def _retry_wait(response):
    try:
        value = float((getattr(response, "headers", None) or {}).get("Retry-After"))
    except (TypeError, ValueError):
        value = 0.7
    return max(0.0, min(value if math.isfinite(value) else 0.7, MAX_RETRY_WAIT_SECONDS))


def _json(response):
    try:
        content_type = str((response.headers or {}).get("content-type", "")).lower()
        return response.json() if "application/json" in content_type else None
    except Exception:  # unreadable body: treated as no answer
        return None


def complete(messages, *, api_key, max_tokens, temperature, timeout, post, sleep):
    """Send one fixed-route request (one retry for 429/5xx/network errors).

    Returns ``(ok, text, meta)``. ``meta`` never contains prompts, responses or keys.
    """
    if not api_key:
        return False, "", {"error": "ai_not_configured"}
    try:
        payload = build_request(messages, max_tokens=max_tokens, temperature=temperature)
    except RouteError as exc:
        return False, "", {"error": exc.code}
    last = {"error": "ai_route_unavailable"}
    for attempt in range(MAX_ATTEMPTS):
        assert_fixed(payload)  # the retry sends the identical fixed request
        try:
            response = post(ENDPOINT, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                            json=payload, timeout=timeout)
        except Exception as exc:  # network failure, bad header value, ...
            last = {"error": "ai_route_unavailable", "kind": type(exc).__name__}
            if attempt < MAX_ATTEMPTS - 1:
                sleep(0.5)
            continue
        status = int(getattr(response, "status_code", 0) or 0)
        body = _json(response)
        if 200 <= status < 300:
            try:
                text = response_text(body)
            except RouteError as exc:
                # An answer from anything but the fixed route is discarded, never retried elsewhere.
                return False, "", {"error": exc.code, "status": status}
            return True, text, {"model": MODEL, "provider": PROVIDER_NAME, "status": status}
        last = _error_summary(status, body)
        if status in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
            sleep(_retry_wait(response))
            continue
        break
    return False, "", last
