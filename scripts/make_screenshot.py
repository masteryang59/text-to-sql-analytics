"""Capture docs/screenshot.png from a running app (needs: pip install playwright).

Start the app first (`docker compose up`, or `python -m sqlchat serve`), then:

    python scripts/make_screenshot.py --url http://127.0.0.1:8000

It asks a question and a follow-up in the UI, waits for the chart and takes the
shot. `--variants` also writes dark-mode, table, error-repair and phone-width shots
next to it, for checking the layout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs"


def ask(page, question: str) -> None:
    n = page.locator(".answer-card, .note-card, .error-card").count()
    page.fill(".composer textarea", question)
    page.keyboard.press("Enter")
    page.wait_for_function(
        f"document.querySelectorAll('.answer-card, .note-card, .error-card').length > {n}", timeout=90_000)
    page.wait_for_timeout(400)


def shoot(page, url: str, questions: list[str], path: Path, *, hover: bool = True) -> None:
    page.goto(url)
    page.wait_for_selector(".suggestions button")
    for q in questions:
        ask(page, q)
    if hover:
        # hover the last chart so the tooltip shows
        plot = page.locator(".plot svg").last
        if plot.count():
            box = plot.bounding_box()
            page.mouse.move(box["x"] + box["width"] * 0.72, box["y"] + box["height"] * 0.5)
            page.wait_for_timeout(250)
    page.screenshot(path=str(path))
    print(f"wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--question", action="append",
                    help="questions to ask in order (default: a monthly trend and a follow-up)")
    ap.add_argument("--variants", action="store_true")
    args = ap.parse_args()
    questions = args.question or ["Monthly revenue by category since January 2025"]
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        shoot(page, args.url, questions, OUT / "screenshot.png")
        if args.variants:
            dark = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="dark")
            shoot(dark, args.url, questions, OUT / "screenshot-dark.png")
            phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
            shoot(phone, args.url, questions[:1], OUT / "screenshot-phone.png", hover=False)
            for name, qs in (("bars", ["Revenue by region and channel this year"]),
                             ("ranking", ["Top 10 products by units sold in 2025"]),
                             ("more", ["Which category had the highest gross margin?",
                                       "How many customers bought both a laptop and a monitor?"])):
                extra = browser.new_page(viewport={"width": 1440, "height": 1000})
                shoot(extra, args.url, qs, OUT / f"screenshot-{name}.png")
        browser.close()


if __name__ == "__main__":
    main()

def emit_event(data=None):
    if data is None:
        return None
    return data

def emit_event(data=None):
    if data is None:
        return None
    return data