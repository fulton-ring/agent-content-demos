"""Screenshots of a run's review screen, for the README and for prospects.

    python screenshots.py [output/gemini-3.8-flash-alone]

Opens the run's index.html in Chromium at 1440x900 and saves screenshots/*.png:
a value on a real K-1 highlighted on its box, an amount the issuer put on a
statement, the statement page, a scanned copy, the review queue with the
statement lines the model read, and the values checked against the answer key.
Set CHROMIUM_PATH to use a Chromium you already have.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
SIZE = {"width": 1440, "height": 900}


def main():
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "output" / "gemini-3.8-flash-alone"
    SHOTS.mkdir(exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()
    launch = {"executable_path": os.environ["CHROMIUM_PATH"]} if os.environ.get("CHROMIUM_PATH") else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport=SIZE)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((run / "index.html").resolve().as_uri())
        page.evaluate("localStorage.clear()")
        page.reload()
        wait = page.wait_for_timeout

        def doc(file):
            page.click(f".docs a:has(small:text-matches('^{file}'))")
            wait(700)

        def box(key):
            page.click(f"tr.v:has(td:text-is('{key}'))")
            wait(900)

        def shot(name):
            page.screenshot(path=SHOTS / name)

        wait(1500)
        # A real K-1 as the issuer published it: every value points at its box.
        doc("02-enviva-2021-k1.pdf")
        box("1")
        shot("1-value-linked-to-box.png")
        # An amount the issuer moved to a statement goes to review, with the statement one click away.
        box("20 *")
        shot("2-statement-sent-to-review.png")
        page.click("#otherpage")
        wait(1200)
        shot("3-attached-statement.png")
        # The same kind of K-1 printed and scanned.
        doc("03-blackstone-2019-k1-scan1a.pdf")
        box("16 B")
        shot("4-scanned-copy.png")
        # The queue: each item cropped from the page, with the reason, and the statement lines the model read.
        page.click("#t-queue")
        wait(1200)
        item = page.locator(".item", has=page.locator(".stmt")).first
        item.scroll_into_view_if_needed()
        wait(800)
        shot("5-review-queue.png")
        # Every value against the hand-keyed answer key, on a bad scan.
        page.check("#showkey")
        page.click("#t-values")
        wait(500)
        doc("03-blackstone-2019-k1-scan2b.pdf")
        box("6b")
        shot("6-answer-key.png")
        browser.close()
    if errors:
        sys.exit(f"the review screen raised errors: {errors}")
    print(f"wrote {len(list(SHOTS.glob('*.png')))} screenshots to {SHOTS.relative_to(HERE)}/ from {run}")


if __name__ == "__main__":
    main()
