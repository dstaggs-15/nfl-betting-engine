"""Browser behavior against a real static build, including ranking and provider limits."""

import functools
import http.server
import os
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
server = http.server.ThreadingHTTPServer(
    ("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root / "dist"))
)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"
try:
    with sync_playwright() as p:
        executable = os.getenv("BROWSER_EXECUTABLE")
        browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.wait_for_selector(".provider")
        assert page.locator("h1").text_content() == "Line Watcher"
        assert page.locator("#error").is_hidden()
        assert page.locator("#tab-value").get_attribute("aria-selected") == "true"
        assert not page.locator(".advanced").get_attribute("open")
        page.locator("#tab-safest").click()
        assert page.locator("#tab-safest").get_attribute("aria-selected") == "true"
        assert "value and return checks" in page.locator("#ranking-status").inner_text()
        assert "first touchdown" not in page.locator("#pick-cards").inner_text().lower()
        page.locator("#tab-all").click()
        page.locator("#search").fill("Trevor")
        page.wait_for_selector("#player-suggestions [role=option]")
        assert page.locator("#search").get_attribute("aria-expanded") == "true"
        page.locator("#player-suggestions [role=option]").filter(has_text="Trevor Lawrence").click()
        page.locator(".advanced summary").click()
        page.locator("#fresh").uncheck()
        assert page.locator("#pick-cards .pick-card").count() > 0
        assert "Trevor Lawrence" in page.locator("#pick-cards").text_content()
        page.locator("#search").fill("")
        page.locator("#tab-parlays").click()
        assert page.locator("#parlay-panel").is_visible()
        assert page.locator("#line-panel").is_hidden()
        assert "No verified, positive-value ticket" in page.locator("#tickets").inner_text()
        page.locator("#legs").select_option("4")
        assert page.locator("#legs").input_value() == "4"
        page.locator("#tab-parlays").press("ArrowLeft")
        assert page.locator("#tab-all").get_attribute("aria-selected") == "true"
        page.locator("a[href='tracker.html']").first.click()
        page.wait_for_selector("#kpis .kpi")
        assert page.locator("#kpis .kpi").count() == 4
        assert page.locator("#advanced-kpis .kpi").count() == 4
        assert page.locator("#error").is_hidden()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
        page.goto(base)
        page.wait_for_selector(".provider")
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
        page.screenshot(path="/tmp/line-watcher-simple-mobile.png", full_page=False)
        assert not errors, errors
        browser.close()
    print(
        "Browser checks passed: clear ranking tabs, autocomplete, profit/payout limits, simplified tracker, mobile"
    )
finally:
    server.shutdown()
