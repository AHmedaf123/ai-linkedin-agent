#!/usr/bin/env python3
"""
Generate a Playwright storage state for LinkedIn and output a base64 string
suitable for use as a CI secret (LINKEDIN_STORAGE_B64).

Usage examples:
  # Automatic login (fills credentials) with visible browser
  python scripts/generate_linkedin_storage.py --email you@example.com --password 'yourpass'

  # Manual login (you log in yourself), then the script saves the session
  python scripts/generate_linkedin_storage.py --manual

  # Headless auto-login (not recommended for debugging)
  python scripts/generate_linkedin_storage.py --email you@example.com --password 'yourpass' --headless

Outputs:
  - storage_state.json
  - storage_state.b64.txt (base64 of the storage state)
  - Prints the LINKEDIN_STORAGE_B64 line you can copy into CI secrets
"""

import argparse
import base64
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def robust_fill_login(page, email: str, password: str) -> None:
    """Fill LinkedIn login form using robust selectors and dismiss cookies if present."""
    page.goto("https://www.linkedin.com/login", wait_until="networkidle")

    # Best-effort cookie dismiss
    for label in [
        "Accept",
        "Accept cookies",
        "Allow all",
        "Agree",
        "I accept",
        "Allow essential and optional cookies",
    ]:
        try:
            page.get_by_role("button", name=label, exact=False).click(timeout=1500)
            break
        except Exception:
            pass

    email_selector = ':is(input#username, input[name="session_key"], input#session_key, input[name="email"])'
    password_selector = ':is(input#password, input[name="session_password"], input#session_password)'

    page.wait_for_selector(email_selector, timeout=30000)
    page.locator(email_selector).fill(email)
    page.wait_for_selector(password_selector, timeout=30000)
    page.locator(password_selector).fill(password)
    page.locator('button[type="submit"]').click()
    page.wait_for_url("**/feed/**", timeout=60000)


def main():
    parser = argparse.ArgumentParser(description="Generate LinkedIn storage state (base64)")
    parser.add_argument("--email", help="LinkedIn email (optional if --manual)")
    parser.add_argument("--password", help="LinkedIn password (optional if --manual)")
    parser.add_argument("--output", default="storage_state.json", help="Output storage state path")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--manual", action="store_true", help="Manual login (you perform the login)")
    args = parser.parse_args()

    email = args.email or os.getenv("LINKEDIN_EMAIL")
    password = args.password or os.getenv("LINKEDIN_PASSWORD")

    if not args.manual and not (email and password):
        raise SystemExit("Provide --email and --password, or use --manual mode.")

    output_path = Path(args.output)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()

        if args.manual:
            page.goto("https://www.linkedin.com/login", wait_until="networkidle")
            print("Please complete login manually in the opened browser window.")
            print("After you see your feed, return here and press ENTER to continue...")
            input()
        else:
            robust_fill_login(page, email, password)

        # Ensure we are on feed before saving
        page.wait_for_url("**/feed/**", timeout=60000)
        context.storage_state(path=str(output_path))
        browser.close()

    b64 = base64.b64encode(output_path.read_bytes()).decode("utf-8")
    b64_path = output_path.with_suffix(".b64.txt")
    b64_path.write_text(b64, encoding="utf-8")

    print("Saved:", output_path)
    print("Saved:", b64_path)
    print("\nAdd this to your CI secrets (GitHub → Settings → Secrets and variables → Actions):\n")
    print("LINKEDIN_STORAGE_B64=", b64, sep="")


if __name__ == "__main__":
    main()