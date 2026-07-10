"""One-time LinkedIn session capture.

Opens a real (headful) Chromium window. You log in to LinkedIn manually — solve
any captcha / 2FA — and once you reach the feed, the session cookies are saved
to linkedin_storage.json. After this, `python run.py --force` reuses the session
and posts without needing to log in again (until the session expires).

Run:  python scripts/capture_session.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

STORAGE = os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage.json")
WAIT_SECONDS = int(os.getenv("CAPTURE_WAIT_SECONDS", "300"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        ctx = browser.new_context(no_viewport=True, user_agent=UA, locale="en-US")
        page = ctx.new_page()
        try:
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
        except Exception:
            pass

        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        print("\n" + "=" * 60)
        print(" LOG IN TO LINKEDIN IN THE OPENED WINDOW")
        print(" Solve any captcha / 2FA. Wait until your feed loads.")
        print(f" I'll auto-save the session once you reach the feed (up to {WAIT_SECONDS}s).")
        print("=" * 60 + "\n")

        deadline = time.time() + WAIT_SECONDS
        saved = False
        while time.time() < deadline:
            # `li_at` is LinkedIn's auth cookie — its presence means we're logged in,
            # regardless of which page the user is currently viewing.
            try:
                cookies = ctx.cookies()
            except Exception:
                cookies = []
            if any(c.get("name") == "li_at" and c.get("value") for c in cookies):
                # Small settle delay so all session cookies are set, then save.
                time.sleep(2)
                ctx.storage_state(path=STORAGE)
                print(f"\n[OK] SESSION SAVED to {STORAGE}")
                saved = True
                break
            time.sleep(2)

        if not saved:
            print("\n⏱️  Timed out waiting for login. Re-run and finish logging in faster.")
        browser.close()
        return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
