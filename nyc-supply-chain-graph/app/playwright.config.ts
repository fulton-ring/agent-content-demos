import { defineConfig } from "@playwright/test";

// The browser check: the app must list the same upstream facilities, in the same order, as spike #62's notebook.
export default defineConfig({
  testDir: "tests",
  timeout: 90_000,
  // Lookups wait on NYC GeoSearch or PLUTO, which can take several seconds.
  expect: { timeout: 30_000 },
  use: {
    baseURL: "http://localhost:4173",
    // CHROMIUM_PATH points at an existing Chromium; without it, run `npx playwright install chromium` once.
    launchOptions: { executablePath: process.env.CHROMIUM_PATH || undefined },
  },
  webServer: {
    command: "npx vite preview --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: true,
  },
});
