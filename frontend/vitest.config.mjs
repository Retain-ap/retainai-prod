import { defineConfig } from "vitest/config";
import viteConfig from "./vite.config.mjs";

export default defineConfig({
  ...viteConfig({ command: "serve", mode: "test" }),
  test: {
    globals: true,
    environment: "jsdom",
    environmentOptions: { jsdom: { url: "http://localhost/" } },
    setupFiles: ["./src/setupTests.js"],
    include: ["src/**/__tests__/**/*.{js,jsx,ts,tsx}", "src/**/*.{spec,test}.{js,jsx,ts,tsx}"],
    clearMocks: false,
    mockReset: true,
    sequence: { hooks: "list" },
    fileParallelism: false,
  },
});
