"""Screenshot the FalkorDB Browser running a graph query.

Opens http://localhost:3000, connects to FalkorDB (host localhost, port 6379,
empty username and password), selects the "repo" graph, runs:

    MATCH (p:Person)-[:AUTHORED]->(r:PR)-[:TOUCHES]->(f:File)
    RETURN p, r, f LIMIT 50

and saves docs/graph.png.

Run:  python scripts/screenshot_graph.py
Needs: FalkorDB running (http://localhost:3000 UI + port 6379) with the
       "repo" graph loaded (python load.py), and a Chromium executable.
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

QUERY = """MATCH (p:Person)-[:AUTHORED]->(r:PR)-[:TOUCHES]->(f:File)
RETURN p, r, f LIMIT 50"""

UI_URL = "http://localhost:3000"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "graph.png"

# Chromium revisions cached locally vary by environment; try the default
# launch first, then fall back to common Playwright cache locations.
CHROMIUM_CANDIDATES = [
    None,
    "/home/shantanu/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
]

OVERLAY = '[data-tutorial-overlay]'


def dismiss_tutorial(page):
    """Dismiss the FalkorDB Browser tutorial overlay if it is showing."""
    overlay = page.locator(OVERLAY).first
    for _ in range(15):
        if not overlay.is_visible():
            return
        clicked = False
        for label in ("Skip Tutorial", "Next"):
            try:
                page.click(f'button:has-text("{label}")', timeout=1500, force=True)
                clicked = True
                break
            except Exception:
                pass
        if not clicked:
            try:
                overlay.click(timeout=1500, force=True)
            except Exception:
                pass
        page.wait_for_timeout(600)


def ready_click(page, selector, timeout=8000):
    """Dismiss any tutorial overlay, then click *selector*."""
    deadline = time.time() + timeout / 1000
    last_error = None
    while time.time() < deadline:
        dismiss_tutorial(page)
        try:
            page.click(selector, timeout=1500)
            return
        except Exception as exc:
            last_error = exc
            page.wait_for_timeout(300)
    raise last_error


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        last_error = None
        browser = None
        for executable_path in CHROMIUM_CANDIDATES:
            try:
                browser = p.chromium.launch(
                    executable_path=executable_path,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                break
            except Exception as exc:
                last_error = exc
        if browser is None:
            raise last_error

        try:
            page = browser.new_page()
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(UI_URL, timeout=15000)
            dismiss_tutorial(page)

            # Connect to FalkorDB: host, port, empty username and password.
            page.fill("#Host", "localhost")
            page.fill("#Port", "6379")
            page.fill("#Username", "")
            page.fill("#Password", "")
            ready_click(page, "#submit-button")
            dismiss_tutorial(page)
            page.wait_for_timeout(1000)

            # Select the "repo" graph.
            ready_click(page, 'button:has-text("Select Graph")')
            page.wait_for_selector('button:has-text("repo")', timeout=5000)
            ready_click(page, 'button:has-text("repo")')
            page.wait_for_timeout(1200)

            # Run the graph query (CodeMirror editor behind [data-testid="editor"]).
            ready_click(page, '[data-testid="editor"]')
            page.keyboard.type(QUERY, delay=10)
            page.wait_for_timeout(500)
            ready_click(page, 'button:has-text("RUN")')

            # Wait for results to render before screenshotting.
            page.wait_for_timeout(4000)
            dismiss_tutorial(page)

            page.screenshot(path=str(OUTPUT), full_page=True)
            print(f"saved {OUTPUT}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
