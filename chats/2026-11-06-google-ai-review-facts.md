# RetainAI Google review: AI-service facts — November 6, 2026

Read-only follow-up by Claude, independently checked and corrected by Codex.
No provider/model/privacy setting changed, no AI request was made, and no message
was sent to Google. A final reply remains pending dedicated reviewer access.

## Verified account configuration

The signed-in `owner@retainai.ca` OpenRouter Personal account shows a pay-as-you-go
balance. On November 6 its four switches for paid training, free training, public
free prompts and data-sharing discount were all off. All model-group ZDR switches
were off. No provider or model-author allowlist was selected.

This confirms configuration, not independent enforcement or zero retention.
Do not describe the earlier observed OpenAI request as a fixed provider list.
OpenRouter's [provider policy documentation](https://openrouter.ai/docs/guides/privacy/provider-logging)
distinguishes training controls from [ZDR](https://openrouter.ai/docs/guides/features/zdr).
Its [privacy policy](https://openrouter.ai/privacy) also applies. Provider policies
can change; recheck them before a later submission or configuration change.

## Deployed source facts

References use `004ac88`; backend source is unchanged from live backend `7c96ded`.

- `backend/app.py:1789`: only `openrouter/auto` in `AI_MODEL_ORDER_PROMPT`.
- `backend/app.py:1886`: `_complete_openrouter_prompt` sends to
  `https://openrouter.ai/api/v1/chat/completions`, allowing provider fallbacks and
  requesting `data_collection: "deny"`. There is no `zdr:true` or fixed provider list.
- `backend/app.py:6481` and `:8083`: selected contact name/tags/notes and recent
  conversation data can enter user-requested message drafts (notes bounded to 800
  characters; up to eight conversation items of 500 characters).
- `backend/app.py:7968`: AI Studio playbooks add relationship status, last-contact
  date, derived birthday timing and user context. **This route allows 1,600 note
  characters**, not 800. Do not repeat the initial audit's mistaken uniform limit.
- `backend/app.py:8994`: unattended `ai_draft_message` can send the customer's
  first-name value, business name, booking link and trigger type. This can run
  without a contemporaneous user click when the automation is enabled.
- `backend/app_imports.py:287`: imported biography becomes notes. Imported name
  falls back to primary email if no display name exists. Re-import can merge notes.

Consequences: Google-derived names/notes and birthday timing can reach inference.
Email/phone details are not categorically excluded: email can become the name,
and free text can contain them. Photos/organizations are not separately attached
by the reviewed builders. No builder automatically attaches Google Calendar
events; users can still include information themselves in free-text context.

## Remaining reply/disclosure work

- The current privacy page mentions AI features but does not name OpenRouter or
  clearly explain imported Google Contacts entering drafting. Codex prepared a
  factual clarification locally for review; no published legal statement changed.
- Dedicated reviewer account `owner+google-review-20261102@retainai.ca` remains
  deferred until the owner completes sign-in/MFA. Do not share owner credentials.
- The pending reply must honestly describe dynamic routing. A demand for a closed
  provider/model list cannot be met by guessing one; it would require an intentional
  routing change, compatibility/cost review and testing before deployment.
- Keep the existing replacement video and verification request. Do not restart the
  review or send another partial update without a concrete reason.

Local owner-facing drafts (outside Git) are `retainai-google-ai-reply-draft.txt`
and `retainai-ai-disclosure-draft.txt` in this Codex task's `outputs` directory.
They contain no credentials and have not been sent or published.
