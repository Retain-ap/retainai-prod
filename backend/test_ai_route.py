"""Every AI request uses the one fixed route: openai/gpt-4.1-mini, OpenAI only,
no provider or model fallback, no data collection, a price ceiling, and an
answer accepted only from that route."""

import importlib
import json
import logging
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_ROOT", _TEST_DATA.name)
os.environ.setdefault("USE_SQLITE", "false")
os.environ.setdefault("SESSION_SECRET", "test-only-session-secret-with-adequate-length")
os.environ.setdefault("DATA_ENCRYPTION_KEY", "different-test-data-encryption-key-with-adequate-length")
os.environ.setdefault("RUN_SCHEDULER", "0")

import ai_route  # noqa: E402
import app as retainai  # noqa: E402

FIXED_PROVIDER = {
    "only": ["openai"],
    "order": ["openai"],
    "allow_fallbacks": False,
    "require_parameters": True,
    "data_collection": "deny",
    "max_price": {"prompt": 0.4, "completion": 1.6},
}
MESSAGES = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Draft a thank-you."}]
SECRET_NOTE = "Customer note: gate code 4417"


class Reply:
    def __init__(self, status, body=None, headers=None, raw=False):
        self.status_code = status
        self._body = body
        self.headers = {"content-type": "text/html" if raw else "application/json", **(headers or {})}

    def json(self):
        if self._body is ValueError:
            raise ValueError("not json")
        return self._body


def ok_body(model="openai/gpt-4.1-mini-2025-04-14", provider="OpenAI", content="Thanks for visiting!"):
    body = {"id": "gen-1", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}
    if provider is not ...:
        body["provider"] = provider
    return body


class Recorder:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        reply = self.replies.pop(0) if self.replies else Reply(500, {})
        if isinstance(reply, Exception):
            raise reply
        return reply


def run(post, messages=MESSAGES, key="test-key", **kwargs):
    sleeps = []
    result = ai_route.complete(messages, api_key=key, max_tokens=kwargs.get("max_tokens", 150),
                               temperature=kwargs.get("temperature", 0.3), timeout=5, post=post, sleep=sleeps.append)
    return result, sleeps


class FixedRequestTests(unittest.TestCase):
    def test_the_request_is_exactly_the_fixed_route(self):
        payload = ai_route.build_request(MESSAGES, max_tokens=150, temperature=0.3)
        self.assertEqual(payload, {"model": "openai/gpt-4.1-mini", "messages": MESSAGES, "max_tokens": 150,
                                   "temperature": 0.3, "provider": FIXED_PROVIDER})
        text = json.dumps(payload)
        for forbidden in ("openrouter/auto", '"models"', '"route"', '"plugins"', '"transforms"', "azure", '"zdr"'):
            self.assertNotIn(forbidden, text)

    def test_max_price_is_openai_list_price_in_usd_per_million_tokens(self):
        # OpenRouter lists OpenAI's price per token: 0.0000004 prompt, 0.0000016 completion.
        prices = ai_route.provider_preferences()["max_price"]
        self.assertAlmostEqual(prices["prompt"], 0.0000004 * 1_000_000)
        self.assertAlmostEqual(prices["completion"], 0.0000016 * 1_000_000)

    def test_shared_preferences_cannot_be_mutated_into_a_fallback(self):
        first = ai_route.provider_preferences()
        first["allow_fallbacks"] = True
        first["only"].append("azure")
        first["max_price"]["prompt"] = 99
        self.assertEqual(ai_route.provider_preferences(), FIXED_PROVIDER)

    def test_configuration_cannot_change_the_route(self):
        hostile = {"OPENROUTER_MODEL": "openrouter/auto", "AI_MODEL": "anthropic/claude-3-opus", "OPENROUTER_PROVIDER": "azure",
                   "OPENROUTER_ALLOW_FALLBACKS": "true", "OPENROUTER_BASE_URL": "https://evil.example/v1", "AI_MODEL_ORDER_PROMPT": "openrouter/auto"}
        with patch.dict(os.environ, hostile):
            module = importlib.reload(ai_route)
            payload = module.build_request(MESSAGES, max_tokens=150, temperature=0.3)
            self.assertEqual((payload["model"], payload["provider"], module.ENDPOINT),
                             ("openai/gpt-4.1-mini", FIXED_PROVIDER, "https://openrouter.ai/api/v1/chat/completions"))
        importlib.reload(ai_route)
        self.assertFalse(hasattr(retainai, "AI_MODEL_ORDER_PROMPT"))

    def test_caller_supplied_extras_never_reach_the_request(self):
        sneaky = [{"role": "user", "content": "hi", "models": ["openrouter/auto"], "provider": {"allow_fallbacks": True}}]
        payload = ai_route.build_request(sneaky, max_tokens=10_000, temperature=7)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual((payload["max_tokens"], payload["temperature"]), (600, 1.0))
        self.assertEqual(payload["provider"], FIXED_PROVIDER)

    def test_invalid_input_is_refused_before_anything_is_sent(self):
        cases = [
            [], [{"role": "tool", "content": "x"}], [{"role": "user", "content": 5}], [{"role": "user", "content": "  "}],
            [{"role": "user", "content": "x" * (ai_route.MAX_PROMPT_CHARS + 1)}], [{"role": "user", "content": "x"}] * 5, "not a list",
        ]
        for messages in cases:
            post = Recorder()
            (ok, text, meta), _ = run(post, messages=messages)
            self.assertFalse(ok)
            self.assertEqual(post.calls, [], messages)
        post = Recorder()
        (ok, _, meta), _ = run(post, temperature=float("nan"))
        self.assertEqual((ok, meta["error"], post.calls), (False, "invalid_parameters", []))

    def test_a_tampered_payload_is_refused(self):
        good = ai_route.build_request(MESSAGES, max_tokens=150, temperature=0.3)
        for change in ({"models": ["openrouter/auto"]}, {"model": "openrouter/auto"}, {"route": "fallback"},
                       {"provider": {**FIXED_PROVIDER, "allow_fallbacks": True}},
                       {"provider": {**FIXED_PROVIDER, "only": ["openai", "azure"]}},
                       {"provider": {k: v for k, v in FIXED_PROVIDER.items() if k != "max_price"}}):
            with self.assertRaises(ai_route.RouteError):
                ai_route.assert_fixed({**good, **change})

    def test_no_key_means_no_request(self):
        post = Recorder()
        (ok, _, meta), _ = run(post, key="")
        self.assertEqual((ok, meta, post.calls), (False, {"error": "ai_not_configured"}, []))


class ResponseTests(unittest.TestCase):
    def test_an_answer_from_the_fixed_route_is_accepted(self):
        post = Recorder(Reply(200, ok_body()))
        (ok, text, meta), _ = run(post)
        self.assertEqual((ok, text), (True, "Thanks for visiting!"))
        self.assertEqual(meta, {"model": "openai/gpt-4.1-mini", "provider": "OpenAI", "status": 200})
        call = post.calls[0]
        self.assertEqual(call["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(call["json"]["provider"], FIXED_PROVIDER)
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        for undated in ("openai/gpt-4.1-mini", " openai/gpt-4.1-mini "):
            (ok, _, _), _ = run(Recorder(Reply(200, ok_body(model=undated))))
            self.assertTrue(ok)
        (ok, _, _), _ = run(Recorder(Reply(200, ok_body(provider=...))))  # provider field is optional in the schema
        self.assertTrue(ok)

    def test_answers_from_anything_else_are_discarded_and_not_retried(self):
        cases = {
            "unexpected_provider": [ok_body(provider="Azure"), ok_body(provider="openai-compatible"), ok_body(provider=["OpenAI"])],
            "unexpected_model": [ok_body(model="openrouter/auto"), ok_body(model="openai/gpt-4.1"), ok_body(model="openai/gpt-4.1-mini:free"),
                                 ok_body(model="anthropic/claude-3-haiku"), ok_body(model=None), ok_body(model="openai/gpt-4.1-mini-latest")],
            "empty_response": [ok_body(content=""), ok_body(content=None), {**ok_body(), "choices": []},
                               {**ok_body(), "choices": [{"finish_reason": "error", "message": {"content": "partial"}}]}],
            "provider_error": [{**ok_body(), "error": {"code": 502, "message": "upstream"}}],
            "invalid_response": [["not", "a", "dict"]],
        }
        for code, bodies in cases.items():
            for body in bodies:
                post = Recorder(Reply(200, body), Reply(200, ok_body()))
                (ok, text, meta), _ = run(post)
                self.assertEqual((ok, text, meta["error"]), (False, "", code), body)
                self.assertEqual(len(post.calls), 1)

    def test_non_json_success_is_not_accepted(self):
        (ok, _, meta), _ = run(Recorder(Reply(200, ValueError), Reply(200, ok_body())))
        self.assertEqual((ok, meta["error"]), (False, "invalid_response"))
        (ok, _, meta), _ = run(Recorder(Reply(200, ok_body(), raw=True)))
        self.assertEqual((ok, meta["error"]), (False, "invalid_response"))


class UnavailableRouteTests(unittest.TestCase):
    def test_no_eligible_route_retries_the_identical_request_once_then_fails_closed(self):
        no_route = Reply(503, {"error": {"code": 503, "message": f"No endpoints found matching your data policy. {SECRET_NOTE}"}},
                         {"Retry-After": "120"})
        post = Recorder(no_route, no_route, Reply(200, ok_body()))
        (ok, text, meta), sleeps = run(post)
        self.assertEqual((ok, text), (False, ""))
        self.assertEqual(meta, {"error": "ai_route_unavailable", "status": 503, "code": "503"})
        self.assertEqual(len(post.calls), 2)
        self.assertEqual(post.calls[0]["json"], post.calls[1]["json"])
        self.assertEqual(post.calls[1]["json"]["provider"], FIXED_PROVIDER)
        self.assertEqual(sleeps, [2.0])  # Retry-After is capped; no long waits
        self.assertNotIn("gate code", json.dumps(meta))

    def test_a_transient_failure_then_success_uses_the_same_fixed_request(self):
        post = Recorder(Reply(429, {"error": {"code": 429}}, {"Retry-After": "0.2"}), Reply(200, ok_body()))
        (ok, _, _), sleeps = run(post)
        self.assertTrue(ok)
        self.assertEqual(post.calls[0]["json"], post.calls[1]["json"])
        self.assertEqual(sleeps, [0.2])

    def test_client_errors_are_not_retried(self):
        for status in (400, 401, 402, 403, 404):
            post = Recorder(Reply(status, {"error": {"code": status, "message": "nope"}}), Reply(200, ok_body()))
            (ok, _, meta), _ = run(post)
            self.assertEqual((ok, meta["status"], len(post.calls)), (False, status, 1))

    def test_network_errors_retry_once_and_reveal_nothing(self):
        boom = ConnectionError(f"connect failed for {SECRET_NOTE} with key test-key")
        post = Recorder(boom, boom)
        (ok, _, meta), sleeps = run(post)
        self.assertEqual((ok, meta), (False, {"error": "ai_route_unavailable", "kind": "ConnectionError"}))
        self.assertEqual((len(post.calls), sleeps), (2, [0.5]))

    def test_hostile_error_bodies_are_reduced_to_a_short_code(self):
        post = Recorder(Reply(400, {"error": {"code": {"nested": SECRET_NOTE}, "message": SECRET_NOTE}}))
        (_, _, meta), _ = run(post)
        self.assertEqual(meta, {"error": "ai_route_unavailable", "status": 400})


class EveryCallerUsesTheFixedRouteTests(unittest.TestCase):
    owner = "owner@example.com"

    def setUp(self):
        user = {"email": self.owner, "org_id": self.owner, "role": "owner", "status": "active", "security_version": 0,
                "name": "Morgan", "business": "North Star Studio"}
        lead = {"id": "lead-1", "name": "Jordan Lee", "notes": SECRET_NOTE, "tags": ["Consultation"], "email": "jordan@example.com"}
        patchers = [patch.object(retainai, "OPENROUTER_API_KEY", "test-key"),
                    patch.object(retainai, "load_users", side_effect=lambda: {self.owner: user}),
                    patch.object(retainai, "load_leads", side_effect=lambda: {self.owner: [lead]}),
                    patch.object(retainai, "load_chats", side_effect=lambda: {})]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self):
        client = retainai.app.test_client()
        with client.session_transaction() as signed:
            signed["user_email"] = signed["org_email"] = self.owner
            signed["security_version"] = 0
        return client

    def callers(self):
        return {
            "generate-message": lambda: self.client().post("/api/generate-message", json={"lead": {"id": "lead-1"}}),
            "generate_prompt": lambda: self.client().post("/api/generate_prompt", json={"leadId": "lead-1", "promptType": "followup"}),
            "ai-prompt": lambda: self.client().post("/api/ai-prompt", json={"lead_id": "lead-1"}),
            "automation": lambda: retainai.ai_draft_message({"business_name": "North Star Studio", "booking_link": "https://book.example/owner",
                                                            "lead": {"name": "Jordan", "notes": SECRET_NOTE}, "flow": {"trigger": {"type": "no_reply"}}}),
        }

    def test_all_four_ai_features_send_only_the_fixed_route(self):
        for name, call in self.callers().items():
            post = Recorder(Reply(200, ok_body(content="Hi Jordan, book again at https://book.example/owner")))
            with patch.object(retainai.pyrequests, "post", side_effect=post), patch.object(retainai.time, "sleep"):
                call()
            self.assertEqual(len(post.calls), 1, name)
            sent = post.calls[0]
            self.assertEqual(sent["url"], ai_route.ENDPOINT, name)
            self.assertEqual(set(sent["json"]), ai_route.REQUEST_KEYS, name)
            self.assertEqual((sent["json"]["model"], sent["json"]["provider"]), ("openai/gpt-4.1-mini", FIXED_PROVIDER), name)

    def test_an_unavailable_route_gives_safe_errors_and_keeps_manual_paths(self):
        unavailable = Reply(503, {"error": {"code": 503, "message": "no endpoints"}})
        with self.assertLogs(retainai.app.logger, level=logging.WARNING) as logs, \
                patch.object(retainai.pyrequests, "post", side_effect=Recorder(*[unavailable] * 8)), patch.object(retainai.time, "sleep"):
            responses = {name: call() for name, call in self.callers().items()}
        for name in ("generate-message", "generate_prompt", "ai-prompt"):
            self.assertEqual(responses[name].status_code, 502, name)
            body = json.dumps(responses[name].get_json())
            self.assertIn("RetainAI could not create", body)
            self.assertNotIn("gate code", body)
        # Automations fall back to their fixed, non-AI template instead of failing.
        self.assertIn("https://book.example/owner", responses["automation"])
        self.assertNotIn("gate code", "\n".join(logs.output))

    def test_an_answer_from_another_provider_is_never_shown(self):
        with patch.object(retainai.pyrequests, "post", side_effect=Recorder(Reply(200, ok_body(provider="Azure", content="Injected text")))):
            response = self.client().post("/api/generate-message", json={"lead": {"id": "lead-1"}})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("Injected text", json.dumps(response.get_json()))

    def test_no_other_backend_code_calls_an_ai_endpoint(self):
        backend = pathlib.Path(__file__).resolve().parent
        hits = sorted(path.name for path in backend.glob("*.py") if not path.name.startswith("test_")
                      and any(marker in path.read_text(encoding="utf-8", errors="ignore")
                              for marker in ("openrouter.ai/api", "chat/completions", "api.openai.com")))
        self.assertEqual(hits, ["ai_route.py"])
        app_source = (backend / "app.py").read_text(encoding="utf-8", errors="ignore")
        self.assertEqual(app_source.count("ai_route.complete("), 1)
        self.assertNotIn("openrouter/auto", app_source)
        self.assertNotIn('"allow_fallbacks": True', app_source)


if __name__ == "__main__":
    unittest.main()
