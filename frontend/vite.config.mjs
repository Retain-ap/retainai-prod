import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv, transformWithOxc } from "vite";
import react from "@vitejs/plugin-react";
import browserslistToEsbuild from "browserslist-to-esbuild";

const root = path.dirname(fileURLToPath(import.meta.url));
const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));

export function publicEnvironment(mode, envDir = root) {
  const env = loadEnv(mode, envDir, "REACT_APP_");
  return { ...env, NODE_ENV: mode === "test" ? "test" : mode === "development" ? "development" : "production", PUBLIC_URL: "" };
}

export default defineConfig(({ mode }) => ({
  root,
  base: "/",
  envPrefix: "REACT_APP_",
  // Keep CRA's guarded typeof-process reads working without exposing private
  // build variables or installing a runtime Node process polyfill.
  define: mode === "test" ? {} : {
    process: JSON.stringify({ env: publicEnvironment(mode) }),
    "process.env": JSON.stringify(publicEnvironment(mode)),
  },
  plugins: [
    {
      name: "retainai-public-template",
      transformIndexHtml: {
        order: "pre",
        handler: () => fs.readFileSync(path.join(root, "public/index.html"), "utf8")
          .replace("</head>", '<script type="module" src="/src/index.js"></script></head>'),
      },
    },
    {
      name: "retainai-existing-jsx-files",
      enforce: "pre",
      transform(code, id) {
        const file = id.split("?", 1)[0].replaceAll("\\", "/");
        if (file.startsWith(root.replaceAll("\\", "/") + "/src/") && file.endsWith(".js")) {
          return transformWithOxc(code, file + "x", { jsx: { runtime: "automatic" } });
        }
      },
    },
    react(),
  ],
  server: {
    host: "127.0.0.1",
    port: 3000,
    strictPort: true,
    proxy: { "/api": { target: packageJson.proxy, changeOrigin: true } },
  },
  build: {
    outDir: "build",
    assetsDir: "static",
    sourcemap: true,
    target: browserslistToEsbuild(packageJson.browserslist.production),
    rolldownOptions: {
      output: {
        entryFileNames: "static/js/[name].[hash].js",
        chunkFileNames: "static/js/[name].[hash].chunk.js",
        assetFileNames: ({ names }) => names?.some(name => name.endsWith(".css"))
          ? "static/css/[name].[hash][extname]" : "static/media/[name].[hash][extname]",
      },
    },
  },
}));
