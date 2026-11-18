# Frontend toolchain migration — validated candidate

This branch refreshes PR75's replacement of Create React App's build/test wrapper
with Vite 8.3.8 and Vitest 5.1.1. It does not change a product component, API contract, subscription,
route, public copy or runtime package version. Linux CI, isolated browser checks
and the screenshot review below passed for candidate `4318062`. PR75 is still
a draft at this checkpoint; merge and exact-deployment verification are separate.

The November 18 comparison baseline is `8377a5beea5a0f38306a52e68a28d56de47296b9`,
the recovery documentation update after deployed application source
`6319addfde19dd77cecafe32a5af31a2f417a4a2`. Its Windows CRA run passed all 333 cases
in 44 files. The inventory retains every semantic case name, including all 303
cases from PR75's previous baseline. New automation-builder, Calendly and owner
reminder-preference tests receive the same mechanical mock adapters as the
original draft. No product source or runtime package version is changed.

## Preserved contracts

- Node remains 24.19.0; the engine restriction, CI job names, backend checks and
  audit severity gates remain intact.
- `npm run build` still writes `frontend/build` and invokes the same CommonJS
  prerenderer. All 14 public/private initial HTML documents retain their DOM,
  text, metadata and JSON-LD. Render's existing publish directory and route
  rewrites do not change. Generated JavaScript/CSS hashes necessarily change;
  bundles still live under `/static`, and the existing service worker handles
  those paths. The unused CRA `asset-manifest.json` is no longer generated.
- `public/index.html` remains the sole editable HTML template; Vite's root
  `index.html` is only an entry placeholder. Every public static asset is copied
  as before. No public page is recreated as a new design.
- Public build configuration still uses `REACT_APP_` variables and the same
  dotenv file precedence. Guarded `typeof process` reads work in compiled
  browser code without a Node process global. The explicit `process.env`
  replacement is essential because Vite otherwise replaces that expression
  with its own empty object. Only public variables, `NODE_ENV` and root
  `PUBLIC_URL` are embedded; private build variables are excluded. Runtime
  `window.__ENV__` overrides continue to win in `apiBase.js`.
- The local API proxy remains `http://localhost:5000`, scoped to `/api`.
  Development startup is bound to loopback and port 3000. Production API URLs
  remain controlled by the existing source and environment contract.
- Existing `react-app` and `react-app/jest` lint rules are retained. Their
  transitive Babel dependencies are not used as the production bundler.
- CRA ignored the old external PostCSS config. The new explicit config matches
  CRA's real Tailwind pipeline: Tailwind, flexbug fixes, and stage-3 preset-env
  transforms with `flexbox: no-2009` prefixes.
- Browserslist and its data are pinned to the production baseline versions, so
  the query still resolves to the same browser list. Direct compiler targets
  include Chrome 109, Edge 149, Firefox 121, iOS Safari 15.6 and Safari 18.5.
  Oxc's target mapping has no independent Opera Mobile/Samsung targets; those
  Chromium-based browsers still require explicit browser acceptance. UC was
  not an independent target in CRA's Babel mapping either. No legacy browser
  polyfill has been removed from application source.
- The direct Babel transform-runtime dev pin resolves the current React plugin's
  optional peer range normally, without force/legacy-peer flags or overrides.
  The debug dev pin preserves the existing shared runtime dependency version.

## Test case mapping

`frontend/tooling/test-inventory.json` records every original test's source file
and full semantic name, including repeated parameterized names. The inventory
checker rejects a missing, skipped or failed original case; matching totals
alone are insufficient. No test or assertion is deleted to make Vitest pass.

The mechanical adapters are:

- `jest.fn`, spies, timers and module mocks become explicitly imported `vi`
  APIs. Vitest globals allow existing `test`, `expect`, and hook declarations.
- Default component mock factories return `{ default: component }`; the same
  mocked component and props are retained.
- `requireActual` becomes awaited `importActual`; the one synchronous enclosing
  test becomes async without changing its assertions.
- Testing Library 10/16 detects fake clocks by checking a global Jest timer API.
  A test-only bridge exposes only `advanceTimersByTime` from Vitest so existing
  `findBy`/`waitFor` calls drain their fake-clock microtasks. Other Jest APIs are
  deliberately not aliased, and the original race-test clock/assertions remain.
- Filesystem tests derive their directory from `import.meta.url` instead of
  Jest's CommonJS `__dirname`.
- jest-dom uses its supported Vitest entry point. Existing cleanup behavior is
  retained, hooks run in list order, and CRA's resetMocks setting is retained as
  Vitest's mockReset. Vitest resets a mock to its initial implementation whereas
  Jest resets it to a no-op; the existing cases set their request implementations
  in per-test setup. The original test/spec and __tests__ filename globs remain.
- Settings shortcut and Automation action selectors match their full titles
  and descriptions while accepting either whitespace or no whitespace at the
  inline element boundary. jsdom 31 computes that boundary differently; the
  navigation, Back/Forward and workflow publication/editing assertions remain
  unchanged.

## November 18 local validation

On Windows with Node 24.19.0, both the original CRA baseline and the refreshed
candidate passed all 333 application cases across 44 files, with zero skips.
The semantic inventory check, full lint, both compiled environment-contract
tests and production build passed. A fresh CRA build and the Vite build retain
the same 14 route DOMs and JSON-LD payloads, and all 25 copied public assets are
byte-identical. Every generated asset reference exists. All 105 runtime package
versions and every product source file remain unchanged.

The production audit has zero findings. The full audit reports 22 affected
development packages, all inherited from the one unpatched picomatch advisory
below (22 high, zero critical); the original CRA full audit reported 79 affected
packages on the same date. Both existing severity gates pass. These package
counts are not counts of distinct advisories. The later hosted results below
complete the candidate's Linux and bounded browser checks; no production
deployment is claimed.

## November 18 final hosted validation and visual review

Candidate `4318062c6383e56ccad8c76f4e5865b55d4a5ff1` was tested through GitHub's
PR merge commit `85e4e88fafe2e41d75efef70faa9b16a2a953e51`, combining that exact
head with baseline `8377a5beea5a0f38306a52e68a28d56de47296b9`.

- [Release gate 44287131961](https://github.com/Retain-ap/retainai-prod/actions/runs/44287131961)
  passed: 436 backend tests, all 333 frontend cases in 44 files, semantic test
  inventory, both compiled environment-contract tests, lint, production build,
  secret scan and the unchanged dependency audit gates. The frontend production
  audit reported zero findings; the full audit still reported 22 high development
  package entries and zero critical findings, deriving from picomatch below.
- [Isolated browser acceptance 44287131863](https://github.com/Retain-ap/retainai-prod/actions/runs/44287131863)
  passed all eight checks in each of six combinations: Chromium, Firefox and
  WebKit at 1365 x 900 and 390 x 844. It covered homepage styling, email login,
  authenticated overview, stale HTML-shell replacement, direct imports/lazy
  assets, Back/Forward/reload, persisted reminder-email preference and opening
  the workflow editor. The active service worker removed the obsolete cache
  and never cached fixture API responses. Every run retained the assertion
  rejecting any unhandled page error.
- All 24 downloaded homepage, login, overview and workflow screenshots were
  inspected across those six combinations. Visible text and controls remain
  readable against the dark surfaces, with no observed horizontal clipping;
  mobile cards and the workflow editor stack within the viewport. Earlier live
  homepage, mobile navigation and desktop workflow captures retain the same
  visual structure. These are qualitative comparisons, not pixel-matched CRA
  snapshots: platform fonts, viewport sizes, account data and scroll positions
  differ. The existing floating setup badge overlays the lower content in some
  captures; full-page screenshots do not expose every nested scroll position.

The downloaded report and screenshots are in the private workspace's
`outputs/retain-browser-acceptance-4318062-20261118/`; its `report.json` records
the tested merge SHA, six passing runs, synthetic API paths and limitations.
The earlier Windows comparison receipt is
`outputs/retain-toolchain-refresh-receipt-20261118.json`. Its then-pending Linux
and browser fields are historical and superseded by the linked hosted runs.

The browser job uses a kernel network namespace with loopback only and synthetic
accounts/API responses. Only the exact Google SDK `src` assignment is redirected
to inert loopback JavaScript; Google OAuth and its rendered sign-in button are
explicitly untested. No provider, payment, live Calendly sync, real import,
message delivery or customer acceptance is established by this fixture. It also
does not establish exhaustive keyboard navigation, manual touch/scroll gestures,
physical iPhone/Android acceptance, or Opera Mobile 80/Samsung 30 engine results.
The final diff keeps product source, service-worker source and runtime versions
unchanged; test edits are the documented runner/mock and selector adapters.

## Required evidence before merge

1. Clean `npm ci` on Windows and Linux with Node 24.19.0.
2. Full application test JSON compared by `scripts/verify-test-inventory.js`,
   including concurrent product fixes rebased from deploy.
3. `npm run test:tooling`: dotenv precedence, real compiled API/VAPID behavior,
   runtime override and private-variable nonexposure.
4. Existing full lint, production build and both dependency audit gates.
5. `node scripts/compare-prerender.mjs <baseline-build> build`: all route DOMs,
   JSON-LD and generated asset references. The comparison only ignores generated
   bundle tags, insignificant HTML whitespace/comments and comma whitespace in
   the viewport directive list.
6. Confirm runtime package versions match the baseline and public files remain
   byte-identical, apart from generated route HTML.
7. Independent browser acceptance on the public routes and signed-in CRM:
   responsive styling, lazy route/CSS load, reload/Back, imported contacts,
   sign-in/session, Calendly, keyboard operation, and service-worker update.
   Existing automated tests are necessary but do not replace this review.

No PC-local preview server was started. The historical receipt records that
automatic approval review rejected a loopback preview-server start as
"blocked by policy"; it records no more specific reason. This candidate does
not retry that action. The isolated hosted checks above now provide bounded
browser evidence; they do not fill the explicitly untested interaction/provider
scope or establish older Opera Mobile 80/Samsung 30 results. The earlier PR75
evidence remains historical evidence, not acceptance of this refreshed source.

## Remaining dependency risk

The default branch is `deploy`; these were not alerts on an abandoned branch.
The live frontend is a Render static site built with `npm ci && npm run build`.
It does not expose CRA's development server. The six high Dependabot alerts
against the old CRA chain cover webpack-dev-middleware 5.3.4, SVGO 1.3.2,
PostCSS 7.0.39 and serialize-javascript 6.0.2/4.0.0. Their patched major versions
fall outside CRA 5.0.1's supported dependency ranges; this migration removes
those chains without forced overrides or changing application dependencies.

The November 18 registry check also identifies
[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf), a high
severity ReDoS advisory affecting picomatch through 4.0.7. At that check 4.0.7
was the newest published version, the advisory was not withdrawn, and no
patched version was listed. Both installed development versions (2.3.2 and
4.0.7) are affected. These tools process repository-controlled build/test globs;
the runtime dependency inventory has no picomatch. This is residual development
risk, not a clean full audit. Do not accept untrusted glob patterns or disable
the checks to hide it. The production moderate-or-higher and development
critical audit gates remain unchanged. CRA-derived ESLint 8/config packages
also remain deprecated; preserving their existing lint rules is intentional
and a later lint-tool migration must retain those rules.

The decision follows the official [CRA sunset guidance](https://react.dev/blog/2025/02/14/sunsetting-create-react-app),
[Vite environment contract](https://vite.dev/guide/env-and-mode),
[Vite build configuration](https://vite.dev/config/build-options), and
[Vitest's Jest migration guide](https://vitest.dev/guide/migration/jest).
