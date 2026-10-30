"""Capture the README screenshots of the review report with Playwright (headless Chromium).

    python -m orderline demo && python scripts/screenshots.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "out" / "erp-import" / "review.html"
SHOTS = ROOT / "docs" / "screenshots"


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1320, "height": 1000}, device_scale_factor=2)
        page.goto(REPORT.as_uri())
        page.wait_for_timeout(1200)  # web font
        page.screenshot(path=str(SHOTS / "review.png"), clip={"x": 0, "y": 0, "width": 1320, "height": 1000})
        # the handwritten order without a PO number: flags in context
        card = page.locator("article.order", has_text="St. Brigid").first
        card.screenshot(path=str(SHOTS / "flags.png"))
        browser.close()
    print(f"wrote {SHOTS / 'review.png'} and {SHOTS / 'flags.png'}")


if __name__ == "__main__":
    main()
