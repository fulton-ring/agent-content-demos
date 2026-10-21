import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

type KeyRow = { parcel: string; bbl: string | null; upstream: string; rank: number };
const key: KeyRow[] = JSON.parse(readFileSync(new URL("../../output/answer_key.json", import.meta.url), "utf8"));
const parcels = [...new Set(key.filter((row) => row.bbl).map((row) => row.parcel))];

function expected(parcel: string): string[] {
  return key
    .filter((row) => row.parcel === parcel)
    .sort((a, b) => a.rank - b.rank)
    .map((row) => row.upstream);
}

async function lookUp(page: Page, text: string): Promise<string[]> {
  await page.goto("/");
  await page.getByLabel("Address or BBL").fill(text);
  await page.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByTestId("facility").first()).toBeVisible();
  return page.getByTestId("facility").allInnerTexts();
}

for (const parcel of parcels) {
  test(`${parcel}: same upstream list as #62`, async ({ page }) => {
    const bbl = key.find((row) => row.parcel === parcel)?.bbl ?? "";
    expect(await lookUp(page, bbl)).toEqual(expected(parcel));
  });
}

test("an address finds the same lot as its BBL", async ({ page }) => {
  const brookdale = parcels.find((p) => p.startsWith("Brookdale")) ?? "";
  expect(await lookUp(page, "1275 Linden Blvd, Brooklyn")).toEqual(expected(brookdale));
  await expect(page.locator("[data-testid=map][data-ready=true]")).toBeVisible();
  await page.screenshot({ path: "../output/app.png", fullPage: true });
});

test("a lot outside Brooklyn is refused", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Address or BBL").fill("1000010010");
  await page.getByRole("button", { name: "Look up" }).click();
  await expect(page.getByTestId("error")).toContainText("outside Brooklyn");
});
