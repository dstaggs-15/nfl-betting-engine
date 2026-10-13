"""Real browser smoke tests against the built static artifact; no fabricated site history."""

import functools
import http.server
import os
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root / "dist"))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
try:
    with sync_playwright() as playwright:
        executable = os.getenv("BROWSER_EXECUTABLE")
        browser = playwright.chromium.launch(
            headless=True, **({"executable_path": executable} if executable else {})
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        page.wait_for_selector(".provider")
        assert page.locator("#error").is_hidden()
        assert page.locator("a[href='tracker.html']").count() == 1
        import json

        schedule = json.loads((root / "site/data/schedule.json").read_text())
        assert page.locator(".game-card").count() == len(schedule)
        if schedule:
            page.locator(".game-card button").first.click()
            assert page.locator("#selected-game").inner_text() != "All games"
        assert page.locator("h1").text_content() == "Line Watcher"
        assert "More evidence" not in page.locator("body").inner_text()
        # Search suggestions use real current lines and clear a previously selected game.
        predictions = json.loads((root / "site/data/current_predictions.json").read_text())
        if predictions:
            page.locator("#fresh").uncheck()
            name = predictions[0]["line"]["player_name"]
            page.locator("#search").fill(name[:4])
            page.wait_for_selector("#player-suggestions [role=option]")
            assert page.locator("#search").get_attribute("aria-expanded") == "true"
            page.locator("#player-suggestions [role=option]").filter(has_text=name).first.click()
            assert page.locator("#search").input_value() == name
            assert page.locator("#selected-game").text_content() == "All games"
            assert page.locator("#props tr").count() > 0
            assert name in page.locator("#props").inner_text()
            page.locator("#search").fill(name[:4])
            page.locator("#search").press("ArrowDown")
            assert page.locator("#search").get_attribute("aria-activedescendant")
            page.locator("#search").press("Enter")
            assert page.locator("#player-suggestions").is_hidden()
            page.locator("#search").fill("")
        assert "0 props" not in page.locator("#games").inner_text()
        page.locator("button[data-legs='4']").click()
        assert page.locator("#legs").input_value() == "4"
        page.locator("button[data-ranking='ev']").click()
        assert page.locator("#ranking").input_value() == "ev"
        assert "Verified payout economics" in page.locator("#tickets").inner_text()
        page.locator("a[href='tracker.html']").click()
        page.wait_for_selector(".kpi")
        assert page.locator("#error").is_hidden()
        assert page.locator(".kpi").count() == 8
        history = json.loads((root / "site/data/tracker.json").read_text())
        if not history["records"]:
            assert page.locator("#ledger-empty").is_visible()
        else:
            assert page.locator("#ledger tr").count() == len(history["records"])
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.goto(base)
        page.wait_for_selector(".provider")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        # Broken images degrade to team text.
        page.locator(".team-logo").first.evaluate("el=>el.dispatchEvent(new Event('error'))")
        assert page.locator(".game-card .badge").count() > 0
        # A stale provider state must render without hiding the application.
        page.route(
            "**/site/data/status.json",
            lambda route: route.fulfill(
                json={
                    "generated_at": "2026-10-13T20:00:00Z",
                    "current_week": 6,
                    "model_version": "fixture",
                    "model_status": "test",
                    "providers": {
                        "underdog": {
                            "status": "STALE",
                            "message": "Last-known-good lines are stale",
                            "last_success": "2026-10-12T20:00:00Z",
                        }
                    },
                }
            ),
        )
        page.reload()
        page.wait_for_selector(".provider .STALE")
        assert "STALE" in page.locator(".provider").inner_text()
        assert not errors, errors
        page.screenshot(path="/tmp/nfl-dashboard-mobile.png", full_page=False)
        browser.close()
    print(
        "Browser checks passed: pages, data fetches, games, controls, navigation, mobile, logo fallback, stale status"
    )
finally:
    server.shutdown()
