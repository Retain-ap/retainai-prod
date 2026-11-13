# Frontend toolchain migration — draft, not approved for deployment

This branch replaces Create React App's build/test wrapper with Vite 8 and
Vitest 5. It does not change a product component, API contract, subscription,
route, public copy or runtime package version. Do not merge it on the strength
of a clean dependency audit alone. The production app remains on CRA until the
checks below and visual acceptance are complete.

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
- Filesystem tests derive their directory from `import.meta.url` instead of
  Jest's CommonJS `__dirname`.
- jest-dom uses its supported Vitest entry point. Existing cleanup behavior is
  retained, hooks run in list order, and CRA's resetMocks setting is retained as
  Vitest's mockReset. Vitest resets a mock to its initial implementation whereas
  Jest resets it to a no-op; the existing cases set their request implementations
  in per-test setup. The original test/spec and __tests__ filename globs remain.
- One Settings shortcut selector matches its full title and description while
  accepting either whitespace or no whitespace at the inline element boundary.
  jsdom 31 computes that boundary differently; the navigation and Back/Forward
  assertions remain unchanged.

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

No persistent preview server was started. An earlier local preview action was
rejected by automatic approval review; this branch does not retry or bypass it.
Visual acceptance remains an explicit release blocker. Draft results and full
transcripts are kept in the task's `outputs/night-20261113` directory.

The decision follows the official [CRA sunset guidance](https://react.dev/blog/2025/02/14/sunsetting-create-react-app),
[Vite environment contract](https://vite.dev/guide/env-and-mode),
[Vite build configuration](https://vite.dev/config/build-options), and
[Vitest's Jest migration guide](https://vitest.dev/guide/migration/jest).
