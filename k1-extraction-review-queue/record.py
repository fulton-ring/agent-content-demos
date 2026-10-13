"""Click through output/index.html, saving screenshots and a screen recording.

Follows the steps in SCRIPT.md so a founder can record the voice-over on top,
or re-record the screen themselves. Writes screenshots/*.png and
recording/walkthrough.webm (plus .mp4 when ffmpeg is installed).
"""

import os
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
REC = HERE / "recording"
SIZE = {"width": 1440, "height": 900}


def main():
    SHOTS.mkdir(exist_ok=True)
    REC.mkdir(exist_ok=True)
    url = (HERE / "output" / "index.html").resolve().as_uri()
    launch = {}
    if os.environ.get("CHROMIUM_PATH"):
        launch["executable_path"] = os.environ["CHROMIUM_PATH"]
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(REC), record_video_size=SIZE)
        page = ctx.new_page()
        page.goto(url)
        page.evaluate("localStorage.clear()")
        page.reload()
        wait = page.wait_for_timeout

        def doc(file):
            page.click(f".docs a:has(small:text-matches('^{file}'))")
            wait(900)

        def box(key):
            page.click(f"tr.v:has(td:text-is('{key}'))")
            wait(1600)

        wait(2500)
        # 1. A real K-1 as the issuer published it: every value points at its box.
        doc("02-enviva-2021-k1.pdf")
        box("1")
        page.screenshot(path=SHOTS / "1-value-linked-to-box.png")
        box("19 C*")
        box("20 *")
        page.screenshot(path=SHOTS / "2-statement-sent-to-review.png")
        page.click("#otherpage")
        wait(2200)
        page.screenshot(path=SHOTS / "3-attached-statement.png")
        page.click("#otherpage")
        wait(1200)
        # 2. The same K-1 after a print and scan.
        doc("02-enviva-2021-k1-scan1a.pdf")
        box("1")
        box("17 B")
        page.screenshot(path=SHOTS / "4-scanned-copy.png")
        # 3. The review queue.
        page.click("#t-queue")
        wait(2500)
        page.screenshot(path=SHOTS / "5-review-queue.png")
        def item(title):
            return page.locator(".item", has=page.locator("h3", has_text=title))

        misread = item("Blackstone 2019, office scan · box 6b")
        misread.scroll_into_view_if_needed()
        wait(1500)
        misread.locator("input").fill("535")
        wait(800)
        misread.locator("button[data-fix]").click()
        wait(1200)
        right = item("Enviva Partners 2021, office scan · box 1").first
        right.scroll_into_view_if_needed()
        wait(1200)
        right.locator("button[data-ok]").click()
        wait(1500)
        page.screenshot(path=SHOTS / "6-corrected.png")
        # 4. How it scored against the answer key.
        page.check("#showkey")
        page.click("#t-values")
        wait(600)
        doc("03-blackstone-2019-k1-scan1a.pdf")
        box("6b")
        page.screenshot(path=SHOTS / "7-answer-key.png")
        wait(1500)
        video = page.video.path()
        ctx.close()
        browser.close()
    out = REC / "walkthrough.webm"
    Path(video).replace(out)
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "28", "-movflags", "+faststart", str(REC / "walkthrough.mp4")], check=True)
    print(f"wrote {SHOTS.relative_to(HERE)}/ and {REC.relative_to(HERE)}/")


if __name__ == "__main__":
    main()
