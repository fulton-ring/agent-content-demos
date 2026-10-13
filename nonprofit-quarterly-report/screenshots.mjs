// Screenshots of the built pages at desktop (1280px) and phone (390px) width.
// Usage: node screenshots.mjs   (needs Playwright, installed locally or globally)
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright"); }
catch { playwright = require(path.join(execSync("npm root -g").toString().trim(), "playwright")); }
const { chromium } = playwright;

const here = path.dirname(fileURLToPath(import.meta.url));
const pages = [
  ["report", "output/report.html"],
  ["dashboard", "output/dashboard.html"],
  ["report-before-q2", "snapshots/before/report.html"],
  ["dashboard-before-q2", "snapshots/before/dashboard.html"],
];
const widths = [["desktop", 1280], ["phone", 390]];
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
for (const [name, file] of pages) {
  for (const [label, width] of widths) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.join(here, file)).href);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const out = `screenshots/${name}-${label}.png`;
    await page.screenshot({ path: path.join(here, out), fullPage: true });
    console.log(`${out}${overflow > 0 ? `  (page is ${overflow}px wider than the window)` : ""}`);
    await page.close();
  }
}
await browser.close();
