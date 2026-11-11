# HeyCatch signup changes — 11 November 2026

Source: the RetainAI website audit at `https://app.heycatch.ai/audit/hck_pk_qjz4tFpR_LvQkTRpBRn87x0WnOpJVrBJ?surface=website`.

- D2.4 (was 3/4): Replaced the nine-stage signup with email, password, name and trial review. Google signup skips the password stage. Business name/type, location, team size, photo and optional contact information move to the existing Settings profile and post-login setup checklist. Only the signed-in workspace owner can edit that business profile.
- D1.4 (was 2/3): Signup explains the full 14-day workspace, card required through Stripe, C$20 monthly charge after the trial, first-trial eligibility, and cancellation in Settings → Billing before expiry. Explicit Terms/Privacy acceptance remains required. Homepage FAQ changes are tracked separately.
- D2.5 (was 1/4): Reworked signup into one column on phones, with labeled 16px fields, email/name/password autocomplete, email keyboard, visible errors, keyboard focus when steps change, 44px or larger controls, and wrapping consent/review content. A real 375×812 browser pass remains part of release verification; unit tests do not prove layout.

## Identity and billing

The browser uses the Google token payload only to preview the selected name/email. The signup API verifies Google's signature, expiry, audience and issuer through the official verifier, then requires a verified email, nonempty subject and matching submitted email. Google-only accounts retain their provider subject; both checkout resumption and later Google sign-in must match it. Signup never links or overwrites an existing password account.

Signup retains pending-payment state, previous-trial detection, email verification for password accounts, server-side consent, rate limits and the existing checkout reuse path. No workspace is locally fabricated or unlocked by the browser. Optional business fields from older clients remain supported and bounded.

## Release order and validation

Deploy the backend change first. It accepts both the old full-profile request and the new minimal request. Wait for backend release checks and deployment verification before shipping the frontend, because the old backend still requires business fields and a password.

Validation before handoff:

- Seven frontend flow tests passed, covering four-stage email signup, validation, consent, Google credential submission, expired-token recovery, Back behavior and checkout failure.
- Frontend targeted ESLint passed with zero warnings; production bundle build passed.
- Eighteen new backend tests passed on Windows with an explicitly injected no-op `fcntl` import shim. These tests mock storage and exercise identity/consent/billing routing; they do **not** validate Linux file locking. The release must pass the full Linux GitHub backend suite before merging.
- No production signup, Google grant, email or charge was created by these tests.

The signed-in Google provider flow, checkout and post-login profile remain release acceptance checks; the implementation does not claim a new live payment test.
