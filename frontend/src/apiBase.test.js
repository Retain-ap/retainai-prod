import fs from "fs";
import path from "path";
import { API_BASE, apiUrl } from "./apiBase";

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(js|jsx)$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : [];
  });
}

test("defaults to the production API origin", () => {
  expect(API_BASE).toBe("https://api.retainai.ca");
  expect(apiUrl("session")).toBe("https://api.retainai.ca/api/session");
});

test("every file that reads an API env variable falls back to the shared API_BASE", () => {
  // A build without REACT_APP_API_BASE must still reach api.retainai.ca, never
  // the website origin or a literal "undefined".
  const root = __dirname;
  const offenders = sourceFiles(root)
    .filter((file) => path.basename(file) !== "apiBase.js")
    .filter((file) => {
      const text = fs.readFileSync(file, "utf8");
      return /process\.env\.REACT_APP_API_(BASE|URL)/.test(text) && !/import \{[^}]*API_BASE[^}]*\} from "\.\.?\/(apiBase|config)"/.test(text);
    })
    .map((file) => path.relative(root, file));
  expect(offenders).toEqual([]);
});
