# AI routing: one fixed model and provider

Status, November 7, 2026: implemented in code and tests. **Not validated with a
live request.** No AI generation was run, and no credits or credentials were
used, when this was written.

## The route

Every RetainAI AI request goes through `backend/ai_route.py`. That includes
message drafts, AI Studio prompts, `/api/ai-prompt` and automation drafts:
`app._complete_openrouter_prompt` is the only caller of
`ai_route.complete`.

| Field sent to `https://openrouter.ai/api/v1/chat/completions` | Value |
| - | - |
| `model` | `openai/gpt-4.1-mini` (no `models` list, no `openrouter/auto`) |
| `provider.only` / `provider.order` | `["openai"]` |
| `provider.allow_fallbacks` | `false` |
| `provider.require_parameters` | `true` (only `max_tokens` and `temperature` are sent) |
| `provider.data_collection` | `"deny"` |
| `provider.max_price` | `{"prompt": 0.4, "completion": 1.6}`, in USD per million tokens |

- **Nothing can change the route.** The model, provider, endpoint and
  preferences are constants. No environment variable is read for them.
- **Caller input is filtered.** Callers can pass only messages (role and
  content only), `max_tokens` (clamped to 16-600) and `temperature` (0-1).
  Anything else is dropped.
- **The payload is re-checked before every send.** It must be exactly the
  fixed route; otherwise nothing is sent.
- **Only answers from the fixed route are used:**
  - The response `model` must be `openai/gpt-4.1-mini`, or a dated snapshot
    such as `openai/gpt-4.1-mini-2025-04-14`.
  - When the response names a `provider`, it must be OpenAI.
  - Any other answer is discarded, not shown and not retried elsewhere.
- **Retries:** one retry of the identical request for 429, 5xx and network
  errors. The wait is at most 2 seconds, even if `Retry-After` asks for more.
- **When no eligible route exists**, OpenRouter returns 503 ("no available
  model provider that meets your routing requirements"):
  - The AI features return their existing safe 502 message.
  - Automations use their fixed non-AI template.
  - Writing and sending messages by hand is unaffected.
- **Nothing is logged:** no prompts, responses or keys. Errors are reduced to
  status, a short code and an exception class name.

## Evidence (public sources, November 7, 2026)

- **Model page** <https://openrouter.ai/openai/gpt-4.1-mini>: providers are
  OpenAI at $0.40 / $1.60 per million tokens, and Azure at the same price
  plus an EU in-region variant at $0.44 / $1.76.
- **Endpoints metadata**, public and unauthenticated,
  `GET https://openrouter.ai/api/v1/models/openai/gpt-4.1-mini/endpoints`. The
  OpenAI endpoint shows:
  - provider tag `openai`;
  - pricing `prompt 0.0000004`, `completion 0.0000016` USD per token;
  - context 1,047,576 tokens; max completion 32,768 tokens;
  - supported parameters including `max_tokens` and `temperature`, but **not
    `max_completion_tokens`**, so RetainAI sends `max_tokens`.

  The Azure endpoints have tags `azure` and `azure/swedencentral`. `only` and
  `order` exclude them.
- **Provider selection docs**
  <https://openrouter.ai/docs/guides/routing/provider-selection>:
  - `max_price` is "USD price per million tokens" and is a hard filter.
  - `allow_fallbacks: false` "return[s] the upstream error if it's
    unavailable".
  - `data_collection: "deny"` means "use only providers which do not collect
    user data".
- **Errors** <https://openrouter.ai/docs/api_reference/errors-and-debugging>:
  503 = "no available model provider that meets your routing requirements".
- **ZDR** <https://openrouter.ai/docs/guides/features/zdr>:
  - Enforcing ZDR for OpenAI "removes first-party OpenAI endpoints (Azure
    remains available)".
  - For self-serve accounts, `zdr: true` also allows "Safety Retention"
    endpoints.
  - RetainAI therefore does **not** request or claim ZDR.

## Open compatibility point (check in the live validation)

The public docs do not say whether OpenAI's first-party endpoint counts as a
"provider which does not collect user data" for `data_collection: "deny"`.
If it doesn't, the fixed route matches nothing, every AI request gets a 503,
and the features say AI is unavailable. That is safe, but AI drafting would
not work.

Account-level OpenRouter settings can also remove the route:
- an allowed-providers list that excludes OpenAI;
- ZDR enforcement for OpenAI;
- a guardrail.

Check those settings on RetainAI's OpenRouter account. Turning training or
data sharing on is not needed.

**Synthetic live validation** (owner, one request with synthetic text, a fraction
of a cent):
1. Send the exact payload from `ai_route.build_request(...)` with a made-up
   prompt such as "Say hello in five words".
2. Expect HTTP 200 with `provider: "OpenAI"` and a `model` of
   `openai/gpt-4.1-mini...`.
3. Check the activity log entry on the OpenRouter dashboard: provider OpenAI,
   no fallback.

If the result is a 503 with a data-policy message, decide whether to drop
`data_collection: "deny"`. With `only: ["openai"]` the recipient stays fixed
either way, but the disclosure must then change too.

## Google review

The public privacy policy (`/privacy-policy`, section 4 and "AI Features") now
names the one fixed model and provider and says fallback is off. It still
says zero-data-retention routing is not enabled. **No reply has been sent to
Google from this work.**
