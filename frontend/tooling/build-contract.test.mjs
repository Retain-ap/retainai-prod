import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { build } from "vite";
import viteConfig, { publicEnvironment } from "../vite.config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("public env retains CRA precedence and never includes private build settings", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "retain-public-env-"));
  const original = process.env.REACT_APP_API_BASE;
  try {
    fs.writeFileSync(path.join(fixture, ".env"), "REACT_APP_API_BASE=https://base.example\nPRIVATE_FIXTURE=not-public\n");
    fs.writeFileSync(path.join(fixture, ".env.local"), "REACT_APP_API_BASE=https://local.example\n");
    fs.writeFileSync(path.join(fixture, ".env.production"), "REACT_APP_API_BASE=https://production.example\n");
    fs.writeFileSync(path.join(fixture, ".env.production.local"), "REACT_APP_API_BASE=https://production-local.example\n");
    delete process.env.REACT_APP_API_BASE;
    assert.equal(publicEnvironment("production", fixture).REACT_APP_API_BASE, "https://production-local.example");
    process.env.REACT_APP_API_BASE = "https://host.example";
    const env = publicEnvironment("production", fixture);
    assert.equal(env.REACT_APP_API_BASE, "https://host.example");
    assert.equal(env.NODE_ENV, "production");
    assert.equal(env.PUBLIC_URL, "");
    assert.equal(env.PRIVATE_FIXTURE, undefined);
  } finally {
    if (original === undefined) delete process.env.REACT_APP_API_BASE;
    else process.env.REACT_APP_API_BASE = original;
    // This fixture contains only synthetic .env values created above.
    for (const name of [".env", ".env.local", ".env.production", ".env.production.local"]) fs.unlinkSync(path.join(fixture, name));
    fs.rmdirSync(fixture);
  }
});

test("the compiled browser bundle honors guarded public env and runtime override, without a Node process or private secret", async () => {
  const keys = ["REACT_APP_API_BASE", "REACT_APP_VAPID_PUBLIC_KEY", "SERVER_PRIVATE_FIXTURE"];
  const original = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  try {
    process.env.REACT_APP_API_BASE = "https://compiled.example/api/";
    process.env.REACT_APP_VAPID_PUBLIC_KEY = "public-key-fixture";
    process.env.SERVER_PRIVATE_FIXTURE = "private-do-not-bundle-fixture-8a2385";
    const config = viteConfig({ command: "build", mode: "production" });
    const virtual = "\0retain-build-contract";
    const output = await build({
      ...config,
      configFile: false,
      logLevel: "error",
      plugins: [...config.plugins, {
        name: "synthetic-build-contract",
        resolveId(id) { if (id === "retain-build-contract") return virtual; },
        load(id) {
          if (id !== virtual) return;
          return `export { API_BASE, apiUrl } from ${JSON.stringify(path.join(root, "src/apiBase.js").replaceAll("\\", "/"))};
            export const pushKey = typeof process !== "undefined" && process.env && process.env.REACT_APP_VAPID_PUBLIC_KEY;
            export const privateValue = process.env.SERVER_PRIVATE_FIXTURE;`;
        },
      }],
      build: {
        ...config.build,
        write: false,
        sourcemap: false,
        rolldownOptions: { input: "retain-build-contract", preserveEntrySignatures: "strict", output: { format: "iife", name: "RetainBuildContract" } },
      },
    });
    const code = output.output.filter(item => item.type === "chunk").map(item => item.code).join("\n");
    assert.ok(!code.includes(process.env.SERVER_PRIVATE_FIXTURE));
    const browser = {};
    vm.runInNewContext(code, browser);
    assert.equal(browser.RetainBuildContract.API_BASE, "https://compiled.example");
    assert.equal(browser.RetainBuildContract.apiUrl("session"), "https://compiled.example/api/session");
    assert.equal(browser.RetainBuildContract.pushKey, "public-key-fixture");
    assert.equal(browser.RetainBuildContract.privateValue, undefined);
    const runtime = { window: { __ENV__: { REACT_APP_API_BASE: "https://runtime.example/api/" } } };
    vm.runInNewContext(code, runtime);
    assert.equal(runtime.RetainBuildContract.API_BASE, "https://runtime.example");
  } finally {
    for (const key of keys) {
      if (original[key] === undefined) delete process.env[key];
      else process.env[key] = original[key];
    }
  }
});
