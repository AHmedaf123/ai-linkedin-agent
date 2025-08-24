import os
import time
import random
import base64
import json
import logging
import sys
import playwright
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

# Optional stealth import with graceful fallback
try:
    from playwright_stealth import stealth_sync as _stealth_sync
    def apply_stealth(page: Page) -> None:
        _stealth_sync(page)
except Exception:
    def apply_stealth(page: Page) -> None:
        # Minimal stealth fallback: hide webdriver flag
        try:
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        except Exception:
            pass

# Configure logging for the module
logger = logging.getLogger("linkedin-agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Diagnostic: versions
try:
    logger.info(f"Python Version: {sys.version}")
except Exception:
    pass
try:
    logger.info(f"Playwright Version: {playwright.__version__}")
except Exception:
    pass

# --- Custom Exceptions ---
class LinkedInError(Exception):
    """Base exception for LinkedIn operations."""
    pass

class LinkedInAuthError(LinkedInError):
    """Raised when authentication to LinkedIn fails."""
    pass

class LinkedInPostError(LinkedInError):
    """Raised when posting content to LinkedIn fails."""
    pass

# --- Helper Functions (moved outside class for general utility if needed, but primarily used by the class) ---
def _human_type(page: Page, text: str, min_delay: int = 50, max_delay: int = 150):
    """
    Simulates human-like typing with random delays between characters.

    Args:
        page: The Playwright page object.
        text: The text string to type.
        min_delay: Minimum delay between keystrokes in milliseconds.
        max_delay: Maximum delay between keystrokes in milliseconds.
    """
    for char in text:
        page.keyboard.type(char)
        time.sleep(random.randint(min_delay, max_delay) / 1000)

def _random_wait(min_ms: int = 500, max_ms: int = 2000):
    """
    Pauses execution for a random duration within a specified range.

    Args:
        min_ms: Minimum wait time in milliseconds.
        max_ms: Maximum wait time in milliseconds.
    """
    time.sleep(random.randint(min_ms, max_ms) / 1000)

def _save_debug_info(page: Page, prefix: str = "error") -> tuple[Optional[str], Optional[str]]:
    """
    Captures a screenshot and HTML content of the page for debugging purposes.

    Args:
        page: The Playwright page object.
        prefix: A string prefix for the saved file names.

    Returns:
        A tuple containing paths to the screenshot and HTML file, or (None, None) if saving fails.
    """
    try:
        screenshot_path = f"{prefix}_screenshot.png"
        page.screenshot(path=screenshot_path)
        logger.info(f"Saved screenshot to {screenshot_path}")

        html_path = f"{prefix}_page.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.info(f"Saved HTML content to {html_path}")
        return screenshot_path, html_path
    except Exception as e:
        logger.error(f"Failed to save debug info: {e}", exc_info=True)
        return None, None

# --- LinkedInPoster Class ---
class LinkedInPoster:
    """
    A class to programmatically post content to LinkedIn using Playwright.

    This class handles browser setup, authentication, and content publishing
    with enhanced robustness and error handling.
    """

    DEFAULT_BROWSER_ARGS: Dict[str, Any] = {
        "headless": True, # Set to False for visual debugging
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions-file-access-check",
            "--disable-extensions",
            "--disable-plugins-discovery",
            "--disable-default-apps",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=TranslateUI",
            "--disable-ipc-flooding-protection",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]
    }

    DEFAULT_CONTEXT_ARGS: Dict[str, Any] = {
        "viewport": {"width": 1366, "height": 768},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "locale": "en-US",
        "timezone_id": "America/New_York"
    }

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None,
                 storage_state_path: str = "linkedin_cookies.json",
                 storage_b64: Optional[str] = None):
        """
        Initializes the LinkedInPoster with credentials and configuration.

        Args:
            email: LinkedIn account email.
            password: LinkedIn account password.
            storage_state_path: Path to save/load Playwright storage state.
            storage_b64: Base64 encoded storage state content.
        """
        self.email = email
        self.password = password
        self.storage_state_path = Path(storage_state_path)
        self.storage_b64 = storage_b64
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def _prepare_storage_state(self) -> Optional[str]:
        """
        Prepare storage state for persistent sessions.
        - If base64 storage is provided via env/arg, write it to file and use it.
        - Else if a local storage file exists, use it.
        - Else return None (first run will log in and save it).
        """
        # 1) Base64 provided
        if self.storage_b64:
            try:
                raw = base64.b64decode(self.storage_b64)
                self.storage_state_path.write_bytes(raw)
                logger.info(f"Wrote storage state from base64 to {self.storage_state_path}")
                return str(self.storage_state_path)
            except Exception as e:
                logger.warning(f"Failed to decode/write storage_b64: {e}")
        # 2) File exists locally
        if self.storage_state_path.exists():
            logger.info(f"Using existing storage state at {self.storage_state_path}")
            return str(self.storage_state_path)
        # 3) Nothing available yet
        logger.info("No storage state available; will log in and save it after success.")
        return None

    def _setup_browser_context(self) -> Page:
        """
        Sets up the Playwright browser and context, applying stealth scripts.

        Returns:
            The Playwright Page object.

        Raises:
            LinkedInError: If Playwright fails to launch or context cannot be created.
        """
        try:
            p = sync_playwright().start()
            # Configure browser launch arguments
            browser_args = self.DEFAULT_BROWSER_ARGS.copy()
            # Respect HEADLESS env for local debugging
            headless_env = os.getenv("HEADLESS", "true").lower() == "true"
            browser_args["headless"] = headless_env

            # Optional proxy support
            proxy_server = os.getenv("PROXY") or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
            if proxy_server:
                proxy_cfg = {"server": f"http://{proxy_server}" if not proxy_server.startswith(("http://", "https://", "socks5://")) else proxy_server}
                proxy_user = os.getenv("PROXY_USER")
                proxy_pass = os.getenv("PROXY_PASS")
                if proxy_user and proxy_pass:
                    proxy_cfg["username"] = proxy_user
                    proxy_cfg["password"] = proxy_pass
                browser_args["proxy"] = proxy_cfg
                logger.info("Proxy configured for browser launch.")

            logger.info(f"Final browser launch arguments: {browser_args}")
            self.browser = p.chromium.launch(**browser_args)

            context_args = self.DEFAULT_CONTEXT_ARGS.copy()
            # Optional: allow timezone override via env
            tz = os.getenv("POSTING_TIMEZONE") or os.getenv("TZ")
            if tz:
                context_args["timezone_id"] = tz
            initial_storage_state_path = self._prepare_storage_state()
            if initial_storage_state_path:
                context_args["storage_state"] = initial_storage_state_path
                logger.info("Context initialized with provided storage state.")
            else:
                logger.info("Context initialized without storage state (will attempt login).")

            self.context = self.browser.new_context(**context_args)
            self.page = self.context.new_page()

            # Enable stealth mode (playwright-stealth or fallback)
            try:
                apply_stealth(self.page)
                logger.info("stealth applied.")
            except Exception as e:
                logger.warning(f"Failed to apply stealth: {e}")

            # Increase default timeouts to reduce flaky timeouts on slower CI runners
            try:
                timeout_ms = int(os.getenv("LINKEDIN_DEFAULT_TIMEOUT_MS", "120000"))
                self.page.set_default_timeout(timeout_ms)
                self.page.set_default_navigation_timeout(timeout_ms)
                logger.info(f"Default Playwright timeouts set to {timeout_ms} ms")
            except Exception:
                pass

            # Add minimal fallback stealth JavaScript only if needed (stealth plugin applied above)
            try:
                self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)
            except Exception:
                pass
            logger.info("Stealth setup complete.")
            return self.page
        except Exception as e:
            self._close_browser() # Ensure cleanup on setup failure
            raise LinkedInError(f"Failed to set up browser or context: {e}") from e

    def _login(self) -> None:
        """
        Handles the login process to LinkedIn.
        Attempts direct feed navigation with storage state first, then falls back to credentials.

        Raises:
            LinkedInAuthError: If authentication fails after all attempts.
            PlaywrightTimeoutError: If Playwright operations time out during login.
        """
        if not self.page:
            raise LinkedInError("Page not initialized for login.")

        # Decide login strategy based on env
        storage_only = os.getenv("LINKEDIN_STORAGE_ONLY", "false").lower() == "true"
        if storage_only:
            logger.info("Login strategy: storage-first with password fallback DISABLED (storage-only mode).")
        else:
            logger.info("Login strategy: storage-first with password fallback enabled.")

        # Centralize login navigation timeout
        try:
            login_nav_timeout_ms = int(os.getenv("LINKEDIN_LOGIN_NAV_TIMEOUT_MS", "300000"))
        except Exception:
            login_nav_timeout_ms = 300000
        logger.info(f"Login navigation timeout set to {login_nav_timeout_ms} ms")
        
        # Attempt to use existing storage state by navigating directly to feed
        if self.storage_state_path.exists() or bool(self.storage_b64):
            logger.info("Attempting direct feed navigation using storage state.")
            self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            _random_wait(1000, 2000)

            if "login" not in self.page.url and "checkpoint" not in self.page.url:
                logger.info("Successfully navigated to feed (logged in via storage state).")
                return # Successfully logged in via storage state

            # If storage leads to a 'Welcome Back' / account chooser, try to continue with the existing session
            try:
                welcome_seen = False
                try:
                    self.page.get_by_text("Welcome Back", exact=False).wait_for(timeout=2000)
                    welcome_seen = True
                except Exception:
                    # Some locales/pages may not show this text; still try continue buttons if on a login-like URL
                    welcome_seen = "login" in self.page.url or "checkpoint" in self.page.url

                if welcome_seen:
                    logger.info("Detected account chooser. Attempting to continue with saved session.")
                    clicked = False

                    # Strategy 1: Known account-card CSS patterns (first card)
                    for sel in [
                        'ul li button.profile-chooser__account',
                        'ul li .profile-chooser__account button',
                        'ul.profile-chooser__list li:first-child button',
                        'ul li:first-child button',
                        'ul li:first-child a',
                    ]:
                        try:
                            self.page.locator(sel).first.click(timeout=2000)
                            clicked = True
                            break
                        except Exception:
                            continue

                    # Strategy 2: Use text anchor near "Sign in using another account" to click the previous item
                    if not clicked:
                        try:
                            self.page.get_by_text("Sign in using another account", exact=False).wait_for(timeout=2000)
                            success = self.page.evaluate("""
                            () => {
                              const want = Array.from(document.querySelectorAll('button, a, [role="button"], li, div'))
                                  .find(n => /(Sign in using|Sign in to) another account/i.test(n.textContent || ''));
                              if (!want) return false;
                              const container = want.closest('li, div');
                              if (!container) return false;
                              let prev = container.previousElementSibling;
                              // If prev has no interactive element, climb to parent and try previous sibling
                              if (!prev && container.parentElement) prev = container.parentElement.firstElementChild;
                              if (!prev) return false;
                              const clickable = prev.querySelector('button, a, [role="button"]') || prev;
                              clickable.click();
                              return true;
                            }
                            """)
                            if success:
                                clicked = True
                        except Exception:
                            pass

                    # Strategy 2.5: Explicit 'Continue as ...' text
                    if not clicked:
                        try:
                            self.page.get_by_text("Continue as", exact=False).click(timeout=2000)
                            clicked = True
                        except Exception:
                            pass

                    # Strategy 3: Generic 'Continue' / 'Sign in' buttons (fallback)
                    if not clicked:
                        for sel in [
                            'button:has-text("Continue")',
                            'a:has-text("Continue")',
                            'button:has-text("Sign in")',
                            'a:has-text("Sign in")',
                        ]:
                            try:
                                self.page.locator(sel).first.click(timeout=2000)
                                clicked = True
                                break
                            except Exception:
                                continue

                    if clicked:
                        try:
                            self.page.wait_for_url("**/feed/**", timeout=login_nav_timeout_ms)
                            # Ensure the feed UI is interactive
                            self.page.get_by_role("button", name="Start a post", exact=False).wait_for(state="visible", timeout=login_nav_timeout_ms)
                        except PlaywrightTimeoutError as e:
                            # Fallback: detect feed UI even if URL doesn't update promptly
                            try:
                                self.page.get_by_role("button", name="Start a post", exact=False).wait_for(state="visible", timeout=login_nav_timeout_ms)
                                logger.info("Feed UI detected despite URL not matching /feed/.")
                            except Exception:
                                _save_debug_info(self.page, "account_chooser_feed_timeout")
                                raise LinkedInAuthError(f"Failed to detect feed UI after account chooser within {login_nav_timeout_ms} ms: {e}") from e
                        logger.info("Continued via account chooser and reached feed.")
                        return
                    else:
                        logger.warning("Could not click account card on account chooser; will fall back to form login.")
            except PlaywrightTimeoutError:
                # Will fall back to email/password login
                pass
            except Exception:
                # Non-fatal; fall back to email/password login
                pass

            logger.warning("Storage state did not auto-login.")
            if storage_only:
                _save_debug_info(self.page, "storage_login_failed")
                raise LinkedInAuthError("Storage-only mode enabled and storage session is invalid or requires verification.")

        # Fallback to email/password login (only if storage_only is False)
        if storage_only:
            raise LinkedInAuthError("Storage-only mode enabled but storage did not authenticate.")
        if not self.email or not self.password:
            raise LinkedInAuthError("Storage state invalid and no email/password provided for login.")

        logger.info("Proceeding with email/password login.")
        # Load login page and wait for network to be idle to ensure all UI (e.g., cookie banners) is loaded
        # Increase navigation timeout for login page load
        self.page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=login_nav_timeout_ms)
        _random_wait()

        # Detect possible security challenges and bail with diagnostics
        try:
            challenge_selectors = [
                '#security-check-challenge',
                'input[name="captcha"]',
                'iframe[title*="captcha"]',
                'text=/Verify your identity/i',
                'text=/unusual activity/i',
                'text=/are you a robot/i',
            ]
            for sel in challenge_selectors:
                if self.page.locator(sel).first.count() > 0:
                    _save_debug_info(self.page, "security_challenge_detected")
                    raise LinkedInAuthError("LinkedIn security challenge detected; cannot proceed automatically.")
        except Exception:
            # Non-fatal — continue; we still handle timeouts later
            pass

        # Dismiss common cookie banners if present (best-effort, non-fatal)
        for label in ["Accept", "Accept cookies", "Allow all", "Agree", "I accept", "Allow essential and optional cookies"]:
            try:
                self.page.get_by_role("button", name=label, exact=False).click(timeout=1500)
                _random_wait(200, 400)
                break
            except Exception:
                pass

        # Robust selectors for email/password across LinkedIn variants
        email_selector = ':is(input#username, input[name="session_key"], input#session_key, input[name="email"])'
        password_selector = ':is(input#password, input[name="session_password"], input#session_password)'

        # If the "Welcome Back" screen is shown, or guest homepage is shown, route to classic email login
        try:
            self.page.wait_for_selector(email_selector, timeout=5000)
        except PlaywrightTimeoutError:
            try:
                # First, handle guest homepage variant by clicking Sign in entry points
                clicked_any = False
                for sel in [
                    'button:has-text("Sign in with email")',
                    'a:has-text("Sign in")',
                    'button:has-text("Sign in")',
                    'a[href*="/login"]',
                    'a[href*="uas/login"]',
                ]:
                    try:
                        self.page.locator(sel).first.click(timeout=2500)
                        clicked_any = True
                        _random_wait(300, 700)
                        break
                    except Exception:
                        continue
                if not clicked_any:
                    try:
                        self.page.get_by_role("link", name="Sign in", exact=False).first.click(timeout=2500)
                        clicked_any = True
                        _random_wait(300, 700)
                    except Exception:
                        pass

                # Also try account-chooser fallback CTA
                clicked = False
                try:
                    self.page.get_by_role("button", name="Sign in using another account", exact=False).click(timeout=3000)
                    clicked = True
                except Exception:
                    pass
                if not clicked:
                    try:
                        self.page.get_by_text("Sign in using another account", exact=False).click(timeout=3000)
                        clicked = True
                    except Exception:
                        pass

                if clicked or clicked_any:
                    _random_wait(300, 700)

                # Wait again for the email field after switching to classic login form
                self.page.wait_for_selector(email_selector, timeout=30000)
            except PlaywrightTimeoutError as e:
                _save_debug_info(self.page, "login_welcome_back_no_email")
                raise LinkedInAuthError(
                    "Could not find email field or switch to classic login (guest or welcome-back variants)."
                ) from e

        # Fill email
        try:
            self.page.locator(email_selector).fill(self.email)
            logger.debug("Email field filled.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "login_email_fill_timeout")
            raise LinkedInAuthError(f"Timeout locating/filling email field during login: {e}") from e

        _random_wait(300, 800)

        # Fill password
        try:
            self.page.wait_for_selector(password_selector, timeout=30000)
            self.page.locator(password_selector).fill(self.password)
            logger.debug("Password field filled.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "login_password_fill_timeout")
            raise LinkedInAuthError(f"Timeout locating/filling password field during login: {e}") from e

        _random_wait(300, 800)

        # Click submit
        try:
            self.page.locator('button[type="submit"]').click()

            # Two-stage wait: first 120s (configurable), then apply fallbacks (refresh/new tab), then wait remaining time
            try:
                first_wait_ms = int(os.getenv("LINKEDIN_FEED_FIRST_WAIT_MS", "120000"))
            except Exception:
                first_wait_ms = 120000
            remaining_ms = max(10000, login_nav_timeout_ms - first_wait_ms)

            try:
                # Initial wait for feed URL
                self.page.wait_for_url("**/feed/**", timeout=first_wait_ms)
            except PlaywrightTimeoutError as e:
                logger.warning(f"Did not reach feed within first {first_wait_ms} ms after login, applying fallbacks (refresh/direct feed/new tab). Error: {e}")
                # Fallback A: Refresh current page
                try:
                    self.page.reload(wait_until="networkidle")
                except Exception:
                    pass
                _random_wait(500, 1500)

                # Fallback B: Try direct navigation to feed in the same tab
                try:
                    self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                _random_wait(500, 1500)

                # If still not on feed, try opening feed in a new tab
                try:
                    if ("/feed" not in self.page.url) or (self.page.get_by_role("button", name="Start a post", exact=False).count() == 0):
                        new_page = self.context.new_page()
                        try:
                            # Apply stealth to the new page as well
                            apply_stealth(new_page)
                        except Exception:
                            pass
                        try:
                            timeout_ms = int(os.getenv("LINKEDIN_DEFAULT_TIMEOUT_MS", "120000"))
                        except Exception:
                            timeout_ms = 120000
                        try:
                            new_page.set_default_timeout(timeout_ms)
                            new_page.set_default_navigation_timeout(timeout_ms)
                        except Exception:
                            pass
                        new_page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                        # If feed UI is present on new tab, switch to it
                        try:
                            new_page.get_by_role("button", name="Start a post", exact=False).wait_for(timeout=15000)
                            self.page = new_page
                            logger.info("Switched to new tab with LinkedIn feed.")
                        except Exception:
                            try:
                                new_page.close()
                            except Exception:
                                pass
                except Exception:
                    pass

                # Final attempt: wait for feed UI with remaining time
                try:
                    self.page.get_by_role("button", name="Start a post", exact=False).wait_for(timeout=remaining_ms)
                    logger.info("Feed UI detected after applying fallbacks.")
                except Exception as final_e:
                    _save_debug_info(self.page, "login_submit_timeout")
                    raise LinkedInAuthError(
                        f"Failed to reach feed after login and fallbacks within {login_nav_timeout_ms} ms: {final_e}"
                    ) from e

            logger.info("Login form submitted; feed detected or fallbacks applied successfully.")
        except Exception as e:
            _save_debug_info(self.page, "login_submit_error")
            raise LinkedInAuthError(f"Error clicking login submit button: {e}") from e


        if "feed" not in self.page.url:
            _save_debug_info(self.page, "login_failed_final")
            raise LinkedInAuthError(f"Login failed: Did not reach LinkedIn feed page. Current URL: {self.page.url}")

        logger.info("Successfully logged in to LinkedIn.")
        _random_wait(1000, 3000)

        # Skip saving storage state to avoid "new device" notifications
        logger.info("Skipping storage state save to avoid 'new device' notifications.")


    def _open_post_composer(self) -> None:
        """
        Attempts to open the LinkedIn post composer.

        Raises:
            LinkedInPostError: If the post composer cannot be opened.
            PlaywrightTimeoutError: If operations time out.
        """
        if not self.page:
            raise LinkedInError("Page not initialized.")

        logger.info("Attempting to open post composer.")
        # Robustly find and click the 'Start a post' button
        try:
            # Prioritize role-based locator
            self.page.get_by_role("button", name="Start a post", exact=False).click(timeout=10000)
        except PlaywrightTimeoutError:
            try:
                # Fallback to aria-label
                self.page.locator('button[aria-label*="Start a post"]').click(timeout=10000)
            except PlaywrightTimeoutError:
                try:
                    # Fallback: click the share-box trigger container
                    self.page.locator(':is(div.share-box-feed-entry__trigger, button.share-box-feed-entry__trigger)').first.click(timeout=10000)
                except PlaywrightTimeoutError as e:
                    _save_debug_info(self.page, "composer_button_timeout")
                    raise LinkedInPostError(f"Failed to find or click 'Start a post' button: {e}") from e
                except Exception as e:
                    _save_debug_info(self.page, "composer_button_error")
                    raise LinkedInPostError(f"Error clicking share box trigger: {e}") from e
            except Exception as e:
                _save_debug_info(self.page, "composer_button_error")
                raise LinkedInPostError(f"Error clicking 'Start a post' button (aria-label fallback): {e}") from e
        except Exception as e:
            _save_debug_info(self.page, "composer_button_error")
            raise LinkedInPostError(f"Error clicking 'Start a post' button (role-based): {e}") from e

        # Wait for the composer UI to appear and an editable textbox to be visible
        try:
            # First try the classic dialog overlay
            dialog_visible = False
            try:
                self.page.wait_for_selector('div[role="dialog"]', timeout=20000)
                dialog_visible = True
            except PlaywrightTimeoutError:
                dialog_visible = False

            # Fallback: some accounts open a full-page composer (lithograph). Detect via URL or editor presence.
            if not dialog_visible:
                composer_like = (
                    "lithograph" in (self.page.url or "")
                    or self.page.locator('div[contenteditable="true"][role="textbox"]').first.count() > 0
                    or self.page.locator('div[aria-label*="Add to your post"]').first.count() > 0
                )
                if not composer_like:
                    # Give it a bit more time before failing
                    self.page.wait_for_timeout(5000)

            # Now, robustly wait for any reasonable editor target
            editor_locators = [
                # Dialog editor
                'div[role="dialog"] div[contenteditable="true"][role="textbox"]',
                'div[role="dialog"] [aria-label*="Text editor"]',
                'div[role="dialog"] [aria-label*="What do you want"]',
                'div[role="dialog"] [aria-label*="Add to your post"]',
                # Full-page composer fallbacks
                'div[contenteditable="true"][role="textbox"]',
                '[aria-label*="Text editor for creating content"]',
                '[aria-label*="What do you want"]',
                '[aria-label*="Add to your post"]',
            ]

            editor_found = False
            for sel in editor_locators:
                loc = self.page.locator(sel).first
                try:
                    loc.wait_for(state="visible", timeout=15000)
                    editor_found = True
                    break
                except Exception:
                    continue

            if not editor_found:
                raise PlaywrightTimeoutError("Editor textbox not found via known selectors")

            logger.info("Post composer opened successfully and editor is visible.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "composer_dialog_timeout")
            raise LinkedInPostError(f"Timeout waiting for post composer dialog/editor: {e}") from e
        _random_wait(500, 1500)

    def _enter_post_content(self, text: str) -> None:
        """
        Enters the post content into the composer's editable area.

        Args:
            text: The text content to post.

        Raises:
            LinkedInPostError: If the text area cannot be found or filled.
            PlaywrightTimeoutError: If operations time out.
        """
        if not self.page:
            raise LinkedInError("Page not initialized.")

        logger.info("Entering content into composer.")
        try:
            # *** FIX: Use a more specific locator to target the actual textbox ***
            # The error message indicated: <div role="textbox" ... aria-label="Text editor for creating content">
            editable_area = self.page.get_by_role("textbox", name="Text editor for creating content")
            editable_area.click(timeout=10000)
            _human_type(self.page, text, min_delay=30, max_delay=100)
            logger.info("Content entered in composer.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "content_editable_timeout")
            raise LinkedInPostError(f"Timeout interacting with content editable area: {e}") from e
        except Exception as e:
            _save_debug_info(self.page, "content_editable_error")
            raise LinkedInPostError(f"Error entering content into composer: {e}") from e
        _random_wait(1000, 2000)

    def _publish_post(self) -> None:
        """
        Clicks the 'Post' button and waits for the post to be published.

        Raises:
            LinkedInPostError: If the 'Post' button cannot be found or the post fails to publish.
            PlaywrightTimeoutError: If operations time out.
        """
        if not self.page:
            raise LinkedInError("Page not initialized.")

        logger.info("Attempting to publish post.")
        _save_debug_info(self.page, "before_post_click") # Debug screenshot before click

        try:
            # Find and click the 'Post' button
            post_button = self.page.get_by_role("button", name="Post", exact=True)
            post_button.click(timeout=login_nav_timeout_ms if 'login_nav_timeout_ms' in locals() else 30000)
            logger.info("Clicked Post button, waiting for post confirmation/redirection.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "post_button_click_timeout")
            raise LinkedInPostError(f"Timeout clicking 'Post' button: {e}") from e
        except Exception as e:
            _save_debug_info(self.page, "post_button_click_error")
            raise LinkedInPostError(f"Error clicking 'Post' button: {e}") from e

        # Wait for the URL to change back to feed or for a success message (more robust approach needed here)
        # For now, a generous random wait and checking the URL is a start.
        _random_wait(5000, 10000) # Give time for the post to process and page to update

        _save_debug_info(self.page, "after_post_click") # Debug screenshot after click

        if "feed" in self.page.url:
            logger.info("Post appears to be published successfully (returned to feed).")
        else:
            _save_debug_info(self.page, "post_status_unknown")
            raise LinkedInPostError(f"Post status uncertain: Did not return to feed page. Current URL: {self.page.url}")

    def _close_browser(self) -> None:
        """Closes the Playwright browser and context if they are open."""
        if self.context:
            try:
                self.context.close()
                logger.info("Playwright context closed.")
            except Exception as e:
                logger.warning(f"Error closing Playwright context: {e}")
        if self.browser:
            try:
                self.browser.close()
                logger.info("Playwright browser closed.")
            except Exception as e:
                logger.warning(f"Error closing Playwright browser: {e}")

    def post_content(self, text: str) -> bool:
        """
        Main entry point to post content to LinkedIn.

        Args:
            text: The text content to post.

        Returns:
            True if posting was successful and verified.

        Raises:
            LinkedInError: For any general errors during the posting process.
            LinkedInAuthError: If authentication fails.
            LinkedInPostError: If the post creation or publishing fails or cannot be verified.
        """
        try:
            self._setup_browser_context()
            self._login()
            self._open_post_composer()
            self._enter_post_content(text)
            self._publish_post()

            # Verify the post appears in the feed by searching for a unique snippet
            try:
                # Use first non-empty line without hashtags as snippet
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                base_line = next((l for l in lines if not l.strip().startswith('#')), lines[0] if lines else text)
                snippet = base_line[:80]
                if len(snippet) < 10:
                    # Fall back to longer body slice if the first line is too short
                    snippet = text[:120]
                # Wait up to 30s for the snippet to appear in the feed after posting
                self.page.wait_for_selector(f"text={snippet}", timeout=30000)
                logger.info("Verified post content visible in feed.")
            except PlaywrightTimeoutError:
                # Could not confirm presence — treat as failure to avoid false positives
                _save_debug_info(self.page, "verification_timeout")
                raise LinkedInPostError("Post verification failed: content not found in feed within timeout.")

            return True
        except (LinkedInAuthError, LinkedInPostError, LinkedInError, PlaywrightTimeoutError) as e:
            logger.error(f"Failed to post to LinkedIn: {e}", exc_info=True)
            if self.page:
                _save_debug_info(self.page, "final_error_state")
            raise # Re-raise the specific exception
        finally:
            self._close_browser()

# --- Example Usage (similar to original function signature) ---
def post_to_linkedin(text: str) -> bool:
    """
    High-level function to post content to LinkedIn.

    Retrieves credentials from environment variables and uses the LinkedInPoster class.

    Args:
        text: The text content to post.

    Returns:
        True if posting was successful, False otherwise.

    Raises:
        RuntimeError: If authentication details are missing or posting fails.
    """
    email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
    password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
    storage_b64 = os.getenv("LINKEDIN_STORAGE_B64")

    if not any([email and password, Path("storage_state.json").exists(), Path("new_storage_state.json").exists(), storage_b64]):
        raise RuntimeError(
            "Missing authentication: Need either existing storage state file (storage_state.json/new_storage_state.json), "
            "LINKEDIN_STORAGE_B64 environment variable, or both LINKEDIN_EMAIL and LINKEDIN_PASSWORD environment variables."
        )

    poster = LinkedInPoster(email=email, password=password, storage_b64=storage_b64)
    try:
        return poster.post_content(text)
    except (LinkedInAuthError, LinkedInPostError, LinkedInError) as e:
        raise RuntimeError(f"LinkedIn posting failed: {e}") from e
    except PlaywrightTimeoutError as e:
        raise RuntimeError(f"A Playwright operation timed out during LinkedIn posting: {e}") from e