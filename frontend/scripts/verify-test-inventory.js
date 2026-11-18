// Compare semantic case names, not aggregate counts: migration must retain every
// original regression case. Duplicate names are kept as separate occurrences.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const [resultPath] = process.argv.slice(2);
if (!resultPath) throw new Error("Usage: node scripts/verify-test-inventory.js test-results.json");
const inventory = JSON.parse(fs.readFileSync(path.join(__dirname, "../tooling/test-inventory.json"), "utf8"));
const result = JSON.parse(fs.readFileSync(resultPath, "utf8"));
assert.equal(result.success, true, "The candidate test run must succeed");
const actual = result.testResults.flatMap((suite) => {
  const file = suite.name.replaceAll("\\", "/").split("/frontend/").pop();
  return suite.assertionResults.map((test) => ({ file, name: test.fullName, status: test.status }));
});
const counts = new Map();
for (const test of actual) {
  assert.equal(test.status, "passed", `${test.file}: ${test.name}`);
  const key = JSON.stringify([test.file, test.name]);
  counts.set(key, (counts.get(key) || 0) + 1);
}
for (const test of inventory.tests) {
  const key = JSON.stringify([test.file, test.name]);
  assert.ok(counts.get(key), `Missing baseline test: ${test.file}: ${test.name}`);
  counts.set(key, counts.get(key) - 1);
}
console.log(`Preserved all ${inventory.tests.length} baseline tests across ${new Set(inventory.tests.map(test => test.file)).size} suites; candidate has ${actual.length} passing cases.`);
