// CI-only compiled-frontend acceptance. Synthetic accounts/API responses only.
// Run inside an isolated network namespace; it must have no external route.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

assert.equal(process.env.RETAIN_BROWSER_NETWORK_ISOLATED, '1');
assert.equal(execFileSync('ip', ['route', 'show', 'default'], { encoding: 'utf8' }).trim(), '', 'No external network route is permitted');
assert.equal(execFileSync('ip', ['-6', 'route', 'show', 'default'], { encoding: 'utf8' }).trim(), '', 'No IPv6 external route is permitted');
const { chromium, firefox, webkit } = await import(pathToFileURL(process.env.RETAIN_PLAYWRIGHT_MODULE));
const buildRoot = path.resolve('build');
const output = path.resolve('browser-acceptance');
await mkdir(output, { recursive: true });
const googleScriptUrl = 'https://accounts.google.com/gsi/client';
const googleFixturePath = '/__fixture_google_sdk.js';
const offlineGoogleScript = '/* Offline acceptance fixture: Google OAuth is not exercised. */';
const fixtureUser = { email: 'browser-fixture@example.test', name: 'Browser Fixture', role: 'owner', platformOwner: false, status: 'active', emailVerified: true, canEditBusiness: true, canManageBilling: true, canInviteTeam: true, businessName: 'Synthetic service business', businessType: 'Service business', orgOwnerEmail: 'browser-fixture@example.test' };
let signedIn = false;
let reminders = true;
const apiPaths = new Set();
const attemptedWrites = [];
const report = { source: process.env.GITHUB_SHA || null, mode: 'compiled frontend with synthetic API only', productionAccessed: false, realMessagesSent: false, externalNetworkRoute: false, runs: [], allPassed: false };
const json = (response, status, data) => {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(data));
};
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.txt': 'text/plain', '.webmanifest': 'application/manifest+json' };
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
    if (pathname.startsWith('/api/')) {
      apiPaths.add(pathname);
      if (request.method === 'POST') {
        attemptedWrites.push(pathname);
        let raw = '';
        for await (const chunk of request) { raw += chunk; if (raw.length > 4096) return json(response, 413, {}); }
        if (pathname === '/api/login') {
          assert.equal(JSON.parse(raw).email, fixtureUser.email);
          signedIn = true;
          return json(response, 200, { ok: true, user: fixtureUser });
        }
        if (pathname === '/api/email/preferences' && signedIn) {
          const body = JSON.parse(raw);
          assert.equal(typeof body.lead_reminder_emails, 'boolean');
          reminders = body.lead_reminder_emails;
          return json(response, 200, { preferences: { lead_reminder_emails: reminders } });
        }
        return json(response, 405, { error: 'Fixture rejects this mutation' });
      }
      if (request.method !== 'GET') return json(response, 405, {});
      if (pathname === '/api/session') return json(response, signedIn ? 200 : 401, { authenticated: signedIn, user: signedIn ? fixtureUser : null });
      if (pathname === '/api/owner/access') return json(response, 200, { allowed: false });
      if (pathname.startsWith('/api/user/')) return json(response, 200, fixtureUser);
      if (pathname === '/api/email/preferences') return json(response, 200, { preferences: { lead_reminder_emails: reminders } });
      // Empty read models exercise bundle loading/navigation, not backend correctness.
      return json(response, 200, { ok: true, leads: [], appointments: [], events: [], contacts: [], history: [], automations: [], workflows: [], items: [], messages: [], notifications: [], templates: [], rules: [], runs: [], revision: 'synthetic-0', connected: false, timezone: 'America/Toronto' });
    }
    if (request.method !== 'GET') { response.writeHead(405); return response.end(); }
    if (pathname === '/__fixture_boot') { response.writeHead(200, { 'Content-Type': 'text/html' }); return response.end('<!doctype html><title>Synthetic fixture</title>'); }
    if (pathname === googleFixturePath) { response.writeHead(200, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' }); return response.end(offlineGoogleScript); }
    let file = path.resolve(buildRoot, '.' + decodeURIComponent(pathname));
    if (file !== buildRoot && !file.startsWith(buildRoot + path.sep)) { response.writeHead(400); return response.end(); }
    try { if ((await stat(file)).isDirectory()) file = path.join(file, 'index.html'); }
    catch { if (path.extname(file)) { response.writeHead(404); return response.end(); } file = path.join(buildRoot, 'index.html'); }
    const bytes = await readFile(file);
    response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    response.end(bytes);
  } catch { if (!response.headersSent) response.writeHead(500); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const withinViewport = async page => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Page must not overflow horizontally');
let currentBrowser;
let expired = false;
const deadline = setTimeout(() => { expired = true; report.timedOut = true; process.exitCode = 1; currentBrowser?.close(); server.close(); }, 8 * 60 * 1000);
try {
  for (const [engine, browserType] of Object.entries({ chromium, firefox, webkit })) {
    assert.equal(expired, false, 'Acceptance deadline exceeded');
    currentBrowser = await browserType.launch({ headless: true });
    for (const [layout, viewport] of Object.entries({ desktop: { width: 1365, height: 900 }, mobile: { width: 390, height: 844 } })) {
      assert.equal(expired, false, 'Acceptance deadline exceeded');
      signedIn = false;
      reminders = true;
      const context = await currentBrowser.newContext({ viewport, locale: 'en-CA', timezoneId: 'America/Toronto', reducedMotion: 'reduce', serviceWorkers: 'allow' });
      // OAuth is outside this email-login fixture. WebKit's SW-owned requests
      // bypass routing, so redirect only the SDK's exact src assignment to
      // inert loopback JS before any request. App scripts and SW stay unchanged.
      await context.addInitScript(({ apiOrigin, googleUrl, fixtureUrl }) => {
        window.__ENV__ = { REACT_APP_API_BASE: apiOrigin };
        const descriptor = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'src');
        if (!descriptor?.set) throw new Error('Google SDK fixture could not install its exact-URL redirect');
        Object.defineProperty(HTMLScriptElement.prototype, 'src', {
          ...descriptor,
          set(value) { descriptor.set.call(this, String(value) === googleUrl ? fixtureUrl : value); },
        });
      }, { apiOrigin: origin, googleUrl: googleScriptUrl, fixtureUrl: origin + googleFixturePath });
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      const errors = [];
      const failedRequests = [];
      const pendingApi = new Set();
      let phase = 'initial fixture';
      const apiRequest = request => { const url = new URL(request.url()); return url.origin === origin && url.pathname.startsWith('/api/'); };
      page.on('request', request => { if (apiRequest(request)) pendingApi.add(request); });
      page.on('requestfinished', request => pendingApi.delete(request));
      page.on('pageerror', error => errors.push({ message: error.message, stack: error.stack, page: new URL(page.url()).pathname, phase }));
      page.on('requestfailed', request => { pendingApi.delete(request); const url = new URL(request.url()); failedRequests.push({ url: url.origin + url.pathname, type: request.resourceType(), error: request.failure()?.errorText, phase }); });
      const settleFixture = async () => {
        // Route headings can render before Settings' initial profile refresh.
        // This loopback-only fixture must finish loading before the test tears
        // down its document. Keep all errors, including cancellation errors.
        await page.waitForLoadState('networkidle', { timeout: 15000 });
        assert.equal(pendingApi.size, 0, 'Initial fixture API requests must finish before forced navigation');
      };
      const navigate = async (label, action) => {
        phase = 'settling before ' + label;
        await settleFixture();
        phase = label;
        await action();
      };
      const row = { engine, layout, checks: [], passed: false };
      report.runs.push(row);
      try {
        await page.goto(origin + '/__fixture_boot');
        await page.evaluate(async () => { await caches.open('retainai-v2-static'); });
        await page.goto(origin + '/', { waitUntil: 'domcontentloaded' });
        await page.locator('#root h1').first().waitFor();
        await withinViewport(page);
        await page.screenshot({ path: path.join(output, engine + '-' + layout + '-home.png'), fullPage: true });
        row.checks.push('public homepage and responsive compiled styles');
        await navigate('login route', () => page.goto(origin + '/login', { waitUntil: 'domcontentloaded' }));
        await page.getByRole('button', { name: 'Login', exact: true }).waitFor();
        await withinViewport(page);
        await page.screenshot({ path: path.join(output, engine + '-' + layout + '-login.png'), fullPage: true });
        await page.getByLabel('Email', { exact: true }).fill(fixtureUser.email);
        await page.getByLabel('Password', { exact: true }).fill('Synthetic-fixture-only-42');
        await page.getByRole('button', { name: 'Login', exact: true }).click();
        await page.waitForURL('**/app');
        await page.getByRole('heading', { name: 'Today’s priorities', exact: true }).waitFor();
        await withinViewport(page);
        row.checks.push('email login and compiled authenticated overview');
        await page.screenshot({ path: path.join(output, engine + '-' + layout + '-overview.png'), fullPage: true });
        await page.evaluate(async () => {
          await navigator.serviceWorker.ready;
          const cache = await caches.open('retainai-v3-html');
          await cache.put('/index.html', new Response('<!doctype html><h1>Obsolete shell fixture</h1>', { headers: { 'Content-Type': 'text/html' } }));
        });
        // ready proves an active registration, not control of this document.
        // Reload under that registration before requiring an active controller.
        await navigate('controlled app reload', () => page.reload());
        await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
        await page.getByRole('heading', { name: 'Today’s priorities', exact: true }).waitFor();
        assert.equal(await page.getByRole('heading', { name: 'Obsolete shell fixture' }).count(), 0);
        row.checks.push('active service worker replaces a stale cached HTML shell from the network');
        await navigate('imports route', () => page.goto(origin + '/app?tab=imports'));
        await page.getByRole('heading', { name: 'Import contacts', exact: true }).waitFor();
        await withinViewport(page);
        row.checks.push('direct import navigation and lazy chunk/style loading');
        await navigate('history back', () => page.goBack());
        await page.getByRole('heading', { name: 'Today’s priorities', exact: true }).waitFor();
        await navigate('history forward', () => page.goForward());
        await page.getByRole('heading', { name: 'Import contacts', exact: true }).waitFor();
        await navigate('imports reload', () => page.reload());
        await page.getByRole('heading', { name: 'Import contacts', exact: true }).waitFor();
        row.checks.push('Back/Forward/reload with verified synthetic session');
        await navigate('notification settings route', () => page.goto(origin + '/app?tab=notifications'));
        const toggle = page.getByRole('checkbox', { name: 'Email me when leads need attention', exact: true });
        await toggle.waitFor();
        // This server-confirmed control deliberately retains its checked state
        // until the save returns. Playwright's uncheck() asserts synchronously.
        await toggle.click();
        await page.getByText('Follow-up reminder emails turned off.', { exact: true }).waitFor();
        assert.equal(await toggle.isChecked(), false);
        await navigate('notification preference reload', () => page.reload());
        await toggle.waitFor();
        await page.waitForFunction(() => Array.from(document.querySelectorAll('label')).some(label => label.textContent.includes('Email me when leads need attention') && label.querySelector('input')?.disabled === false));
        assert.equal(await toggle.isChecked(), false);
        await withinViewport(page);
        row.checks.push('current reminder preference writes and reload against synthetic API');
        await navigate('automations route', () => page.goto(origin + '/app?section=automations'));
        await page.getByRole('button', { name: 'New Automation', exact: true }).waitFor();
        await page.getByRole('button', { name: 'New Automation', exact: true }).click();
        await page.getByRole('heading', { name: 'When it starts', exact: true }).waitFor();
        await page.getByRole('button', { name: 'Add step', exact: true }).click();
        await page.getByRole('heading', { name: 'Add a step', exact: true }).waitFor();
        await withinViewport(page);
        await page.screenshot({ path: path.join(output, engine + '-' + layout + '-workflow.png'), fullPage: true });
        row.checks.push('workflow editor opens trigger and step panels without publishing');
        await page.evaluate(async () => { await navigator.serviceWorker.ready; });
        assert.equal(await page.evaluate(async () => (await caches.keys()).includes('retainai-v2-static')), false);
        assert.equal(await page.evaluate(async () => {
          for (const name of await caches.keys()) {
            for (const request of await (await caches.open(name)).keys()) if (new URL(request.url).pathname.startsWith('/api/')) return true;
          }
          return false;
        }), false);
        row.checks.push('service worker activates, removes old cache and never caches fixture API');
        phase = 'final fixture settlement';
        await settleFixture();
        assert.deepEqual(errors, [], 'No unhandled browser error is permitted');
        row.passed = true;
      } catch (error) {
        row.error = String(error.message).slice(0, 1600);
        row.phase = phase;
        row.pendingApiPaths = [...pendingApi].map(request => new URL(request.url()).pathname);
        row.pageErrors = errors;
        row.failedRequests = failedRequests;
        await page.screenshot({ path: path.join(output, engine + '-' + layout + '-failure.png'), fullPage: true }).catch(() => {});
      } finally { await context.close(); }
    }
    await currentBrowser.close();
    currentBrowser = null;
  }
  report.allPassed = report.runs.length === 6 && report.runs.every(run => run.passed);
  assert.ok(report.allPassed, 'One or more isolated browser acceptance cases failed');
} finally {
  clearTimeout(deadline);
  await currentBrowser?.close();
  await new Promise(resolve => server.close(resolve));
  report.apiFixturePaths = [...apiPaths].sort();
  report.attemptedFixtureWrites = [...new Set(attemptedWrites)].sort();
  report.limitations = ['Synthetic backend only; no live provider, payment or customer acceptance', 'Only the exact Google SDK src assignment is redirected to inert loopback JS; Google OAuth and its rendered button are not tested', 'Desktop browser engines with narrow viewport, not physical iPhone/Android acceptance', 'Opera Mobile 80 and Samsung 30 were not executed'];
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ allPassed: report.allPassed, runs: report.runs.map(({ engine, layout, passed, error }) => ({ engine, layout, passed, error })) }));
}
