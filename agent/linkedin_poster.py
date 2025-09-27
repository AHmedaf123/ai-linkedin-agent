import os
import time
import random
import logging
import sys
import re
from typing import Optional, Dict, Any

import playwright
from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

# Stealth mode (graceful fallback)
try:
    from playwright_stealth import stealth_sync as _stealth_sync
    def apply_stealth(page: Page) -> None:
        _stealth_sync(page)
except Exception:
    def apply_stealth(page: Page) -> None:
        try:
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        except Exception:
            pass

# Logging
logger = logging.getLogger("linkedin-agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
try:
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Playwright Version: {playwright.__version__}")
except Exception:
    pass

# Exceptions
class LinkedInError(Exception):
    pass

class LinkedInAuthError(LinkedInError):
    pass

class LinkedInPostError(LinkedInError):
    pass

# Small helpers

def _random_wait(min_ms: int = 300, max_ms: int = 900) -> None:
    time.sleep(random.randint(min_ms, max_ms) / 1000)

def _save_debug_info(page: Page, prefix: str) -> None:
    try:
        page.screenshot(path=f"{prefix}_screenshot.png")
        with open(f"{prefix}_page.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.info(f"Saved debug: {prefix}_screenshot.png, {prefix}_page.html")
    except Exception as e:
        logger.warning(f"Failed to save debug info: {e}")

class LinkedInPoster:
    """Minimal, readable OOP LinkedIn poster with strict email/password login only."""

    DEFAULT_BROWSER_ARGS: Dict[str, Any] = {
        "headless": os.getenv("HEADLESS", "false").lower() == "true",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-web-security",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ],
    }

    DEFAULT_CONTEXT_ARGS: Dict[str, Any] = {
        "viewport": {"width": 1366, "height": 768},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "locale": "en-US",
        "timezone_id": os.getenv("POSTING_TIMEZONE", os.getenv("TZ", "America/New_York")),
    }

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None, storage_state_path: Optional[str] = None):
        # Allow either credentials or an existing storage state file
        self.email = email
        self.password = password
        self.storage_state_path = storage_state_path or os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage.json")
        if not (self.email and self.password) and not os.path.exists(self.storage_state_path):
            raise LinkedInAuthError("Provide LinkedIn credentials or an existing storage state file.")
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # --- Browser lifecycle ---
    def _setup(self) -> None:
        try:
            p = sync_playwright().start()
            logger.info(f"Launching Chromium (headless={self.DEFAULT_BROWSER_ARGS['headless']})")
            self.browser = p.chromium.launch(**self.DEFAULT_BROWSER_ARGS)

            # Reuse session if storage state exists
            context_args = dict(self.DEFAULT_CONTEXT_ARGS)
            if os.path.exists(self.storage_state_path):
                context_args["storage_state"] = self.storage_state_path
                logger.info(f"Using existing LinkedIn session from {self.storage_state_path}")
            self.context = self.browser.new_context(**context_args)

            self.page = self.context.new_page()
            apply_stealth(self.page)
            timeout_ms = int(os.getenv("LINKEDIN_DEFAULT_TIMEOUT_MS", "90000"))
            self.page.set_default_timeout(timeout_ms)
            self.page.set_default_navigation_timeout(timeout_ms)
            # Hide webdriver quickly as extra fallback
            try:
                self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            except Exception:
                pass
        except Exception as e:
            self._teardown()
            raise LinkedInError(f"Failed to setup browser: {e}")

    def _teardown(self) -> None:
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

    # --- Navigation helpers ---
    def _dismiss_banners(self) -> None:
        if not self.page:
            return
        for label in ["Accept", "Accept cookies", "Allow all", "Agree", "Continue", "Got it", "Close", "Not now", "Skip"]:
            try:
                self.page.get_by_role("button", name=label, exact=False).click(timeout=800)
                _random_wait(150, 300)
            except Exception:
                pass

    def _wait_for_feed_ui(self, timeout_ms: int = 120000) -> None:
        assert self.page
        end = time.time() + timeout_ms / 1000
        last_err = None
        selectors = [
            'button[aria-label*="Start a post" i]',
            'button:has-text("Start a post")',
            'button:has-text("Create a post")',
            'section.scaffold-layout__main',
            'div.scaffold-finite-scroll__content',
            'a[href*="/feed/"]',
        ]
        while time.time() < end:
            for sel in selectors:
                try:
                    if self.page.locator(sel).first.count() > 0:
                        return
                except Exception as e:
                    last_err = e
            try:
                self.page.get_by_role("button", name=re.compile("post|share", re.I)).first.wait_for(timeout=1000)
                return
            except Exception as e:
                last_err = e
            self.page.wait_for_timeout(300)
        raise PlaywrightTimeoutError(f"Feed UI not detected within {timeout_ms} ms: {last_err}")

    # --- Login (email/password only) ---
    def _go_to_login_form(self, login_timeout_ms: int) -> None:
        assert self.page
        self.page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=login_timeout_ms)
        self._dismiss_banners()
        email_sel = ':is(input#username, input[name="session_key"], input#session_key, input[name="email"])'
        pass_sel = ':is(input#password, input[name="session_password"], input#session_password)'
        try:
            self.page.wait_for_selector(email_sel, timeout=6000)
            self.page.wait_for_selector(pass_sel, timeout=6000)
            return
        except PlaywrightTimeoutError:
            # Route to the explicit alternate account page
            self.page.goto("https://www.linkedin.com/checkpoint/lg/sign-in-another-account", wait_until="domcontentloaded", timeout=login_timeout_ms)
            self._dismiss_banners()
            self.page.wait_for_selector(email_sel, timeout=15000)
            self.page.wait_for_selector(pass_sel, timeout=15000)

    def _fail_if_security_check(self) -> None:
        assert self.page
        challenge_markers = [
            '#security-check-challenge',
            'iframe[title*="captcha"]',
            'text=/Verify your identity/i',
            'text=/unusual activity/i',
            'text=/are you a robot/i',
            'text=/quick security check/i',
            'text=/solve this puzzle/i',
        ]
        for sel in challenge_markers:
            try:
                if self.page.locator(sel).first.count() > 0:
                    _save_debug_info(self.page, "security_challenge")
                    logger.warning("Security challenge detected. Waiting for manual completion...")
                    # Allow time for manual puzzle completion, while keeping stealth
                    try:
                        apply_stealth(self.page)
                    except Exception:
                        pass
                    end = time.time() + int(os.getenv("LINKEDIN_SECURITY_WAIT_SECS", "240"))
                    last_err = None
                    while time.time() < end:
                        try:
                            # If feed is reached or challenge disappears, proceed
                            if "linkedin.com/feed" in (self.page.url or ""):
                                return
                            still_challenged = False
                            for marker in challenge_markers:
                                try:
                                    if self.page.locator(marker).first.count() > 0:
                                        still_challenged = True
                                        break
                                except Exception:
                                    pass
                            if not still_challenged:
                                return
                        except Exception as e:
                            last_err = e
                        self.page.wait_for_timeout(1000)
                    raise LinkedInAuthError(f"Security challenge did not resolve within wait window: {last_err}")
            except LinkedInAuthError:
                raise
            except Exception:
                pass

    def _login(self) -> None:
        assert self.page
        login_nav_timeout_ms = int(os.getenv("LINKEDIN_LOGIN_NAV_TIMEOUT_MS", "180000"))

        # If storage state already logged-in, go straight to feed and verify
        try:
            self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
            self._dismiss_banners()
            self._wait_for_feed_ui(timeout_ms=30000)
            logger.info("Using existing session (no login required)")
            return
        except Exception:
            pass

        # Otherwise perform fresh login with credentials
        if not (self.email and self.password):
            raise LinkedInAuthError("No valid session and no credentials provided for login.")

        self._go_to_login_form(login_nav_timeout_ms)

        email_sel = ':is(input#username, input[name="session_key"], input#session_key, input[name="email"])'
        pass_sel = ':is(input#password, input[name="session_password"], input#session_password)'

        self.page.locator(email_sel).fill(self.email)
        _random_wait()
        self.page.locator(pass_sel).fill(self.password)
        _random_wait()

        # Submit (re-apply stealth before clicking Sign in)
        try:
            apply_stealth(self.page)
        except Exception:
            pass
        clicked = False
        for sel in ['button[type="submit"]', 'form button:has-text("Sign in")', 'button:has-text("Sign in")']:
            try:
                self.page.locator(sel).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                pass
        if not clicked:
            _save_debug_info(self.page, "login_submit_error")
            raise LinkedInAuthError("Could not find the Sign in button.")

        # Detect puzzle/captcha early
        _random_wait(600, 1200)
        self._fail_if_security_check()

        # Wait to reach feed then verify UI
        try:
            self.page.wait_for_url("**/feed/**", timeout=min(90000, login_nav_timeout_ms))
        except PlaywrightTimeoutError:
            try:
                self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
        self._fail_if_security_check()
        self._wait_for_feed_ui(timeout_ms=login_nav_timeout_ms)
        _random_wait(800, 1600)

        # Save storage state for future automated runs
        try:
            self.context.storage_state(path=self.storage_state_path)
            logger.info(f"Saved LinkedIn session to {self.storage_state_path}")
        except Exception as e:
            logger.warning(f"Failed to save storage state: {e}")

    # --- Posting ---
    def _open_post_composer(self) -> None:
        assert self.page
        labels = ["Start a post", "Create a post", "Post", "Share", "Start post"]
        for label in labels:
            try:
                self.page.get_by_role("button", name=label, exact=False).first.click(timeout=2000)
                return
            except Exception:
                pass
        try:
            self.page.locator('button[aria-label*="post" i], button[aria-label*="share" i]').first.click(timeout=3000)
            return
        except Exception as e:
            _save_debug_info(self.page, "composer_button_error")
            raise LinkedInPostError(f"Could not open post composer: {e}")

    def _enter_post_content(self, text: str) -> None:
        assert self.page
        # Target the editable textbox inside dialog or full-page composer
        editor_selectors = [
            'div[role="dialog"] div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"][role="textbox"]',
        ]
        editor = None
        for sel in editor_selectors:
            try:
                loc = self.page.locator(sel).first
                if loc and loc.count() > 0:
                    editor = loc
                    break
            except Exception:
                pass
        if not editor:
            _save_debug_info(self.page, "composer_editor_missing")
            raise LinkedInPostError("Post editor not found.")
        editor.click()
        editor.fill("")
        editor.type(text, delay=random.randint(20, 60))
        _random_wait(400, 900)

    def _publish_post(self) -> None:
        assert self.page
        # Click Post button in dialog or full composer
        clicked = False
        for sel in [
            'div[role="dialog"] button:has-text("Post")',
            'button:has-text("Post")',
            'div[role="dialog"] button[aria-label*="Post" i]',
        ]:
            try:
                self.page.locator(sel).first.click(timeout=4000)
                clicked = True
                break
            except Exception:
                pass
        if not clicked:
            _save_debug_info(self.page, "composer_publish_button_missing")
            raise LinkedInPostError("Post button not found.")
        # Wait for composer to close or feed to be visible
        try:
            self.page.wait_for_selector('div[role="dialog"]', state='detached', timeout=30000)
        except Exception:
            pass
        self._wait_for_feed_ui(timeout_ms=60000)

    # --- Public API ---
    def post_content(self, text: str) -> bool:
        # Ensure content is generated before any login attempt
        if not text or not text.strip():
            raise LinkedInPostError("Post text is empty. Generate content before logging in.")
        try:
            self._setup()
            self._login()
            self._open_post_composer()
            self._enter_post_content(text)
            self._publish_post()
            # Verify text snippet appears in feed (best-effort)
            try:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                base_line = next((l for l in lines if not l.startswith('#')), lines[0] if lines else text)
                snippet = (base_line or text)[:80]
                self.page.wait_for_selector(f"text={snippet}", timeout=25000)
            except Exception:
                logger.warning("Could not verify post snippet in feed within timeout.")
            return True
        except Exception as e:
            logger.error(f"Failed to post to LinkedIn: {e}", exc_info=True)
            if self.page:
                _save_debug_info(self.page, "final_error_state")
            raise
        finally:
            self._teardown()
# Entry point compatible with existing imports
def post_to_linkedin(text: str) -> bool:
    email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
    password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
    storage_state = os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage.json")
    # Allow running with storage state only (after a one-time manual solve)
    if not (email and password) and not os.path.exists(storage_state):
        raise RuntimeError("Provide LinkedIn credentials or set LINKEDIN_STORAGE_STATE to an existing session file.")
    poster = LinkedInPoster(email=email, password=password, storage_state_path=storage_state)
    try:
        return poster.post_content(text)
    except (LinkedInAuthError, LinkedInPostError, LinkedInError) as e:
        raise RuntimeError(f"LinkedIn posting failed: {e}") from e
    except PlaywrightTimeoutError as e:
        raise RuntimeError(f"Playwright timed out during LinkedIn posting: {e}") from e