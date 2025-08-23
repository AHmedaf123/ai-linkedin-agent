import os
import time
import random
import base64
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

# Configure logging for the module
logger = logging.getLogger("linkedin-agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

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
                 storage_state_path: str = "storage_state.json",
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
        Prepares the storage state file for Playwright context.
        Always returns None to force fresh login and avoid storage state reuse.

        Returns:
            Always returns None to force fresh email/password login.
        """
        logger.info("Skipping storage state to force fresh login")
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
            # Allow overriding headless mode via env for easier debugging
            browser_args = self.DEFAULT_BROWSER_ARGS.copy()
            try:
                headless_env = os.getenv("LINKEDIN_HEADLESS")
                if headless_env is not None:
                    browser_args["headless"] = str(headless_env).lower() not in ("0", "false", "no")
            except Exception:
                pass
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
            # Increase default timeouts to reduce flaky timeouts on slower CI runners
            try:
                timeout_ms = int(os.getenv("LINKEDIN_DEFAULT_TIMEOUT_MS", "60000"))
                self.page.set_default_timeout(timeout_ms)
                self.page.set_default_navigation_timeout(timeout_ms)
            except Exception:
                pass

            # Add stealth JavaScript to avoid detection
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                
                // Override plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
                
                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            logger.info("Stealth scripts injected.")
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

        # Skip storage state and use fresh email/password login
        logger.info("Using fresh email/password login (skipping storage state).")
        
        # Attempt to use existing storage state by navigating directly to feed
        if False:  # self._prepare_storage_state():
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
                                  .find(n => /Sign in using another account/i.test(n.textContent || ''));
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
                            self.page.wait_for_url("**/feed/**", timeout=int(os.getenv("LINKEDIN_LOGIN_NAV_TIMEOUT_MS", "60000")))
                        except PlaywrightTimeoutError as e:
                            # Fallback: detect feed UI even if URL doesn't update promptly
                            try:
                                self.page.get_by_role("button", name="Start a post", exact=False).wait_for(timeout=20000)
                                logger.info("Feed UI detected despite URL not matching /feed/.")
                            except Exception:
                                _save_debug_info(self.page, "account_chooser_feed_timeout")
                                raise LinkedInAuthError(f"Timeout waiting for feed after account chooser: {e}") from e
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

            logger.warning("Storage state did not auto-login; falling back to email/password login.")

        # Fallback to email/password login
        if not self.email or not self.password:
            raise LinkedInAuthError("Storage state invalid and no email/password provided for login.")

        logger.info("Proceeding with email/password login.")
        # Load login page and wait for network to be idle to ensure all UI (e.g., cookie banners) is loaded
        self.page.goto("https://www.linkedin.com/login", wait_until="networkidle")
        _random_wait()

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

        # If the "Welcome Back" screen is shown, click "Sign in using another account"
        try:
            self.page.wait_for_selector(email_selector, timeout=5000)
        except PlaywrightTimeoutError:
            try:
                # Try multiple ways to hit the fallback CTA
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
                if clicked:
                    _random_wait(300, 700)
                # Wait again for the email field after switching to classic login form
                self.page.wait_for_selector(email_selector, timeout=30000)
            except PlaywrightTimeoutError as e:
                _save_debug_info(self.page, "login_welcome_back_no_email")
                raise LinkedInAuthError(
                    "Could not find email field or switch from 'Welcome Back' screen to classic login."
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
            try:
                self.page.wait_for_url("**/feed/**", timeout=int(os.getenv("LINKEDIN_LOGIN_NAV_TIMEOUT_MS", "60000")))
            except PlaywrightTimeoutError as e:
                # Fallback: wait for a key UI element that exists on the feed page
                try:
                    self.page.get_by_role("button", name="Start a post", exact=False).wait_for(timeout=20000)
                    logger.info("Feed UI detected despite URL not matching /feed/.")
                except Exception:
                    _save_debug_info(self.page, "login_submit_timeout")
                    raise LinkedInAuthError(f"Timeout waiting for feed page after login: {e}. Check credentials or network.") from e
            logger.info("Login form submitted, waiting for feed page.")
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
            except PlaywrightTimeoutError as e:
                _save_debug_info(self.page, "composer_button_timeout")
                raise LinkedInPostError(f"Failed to find or click 'Start a post' button: {e}") from e
            except Exception as e:
                _save_debug_info(self.page, "composer_button_error")
                raise LinkedInPostError(f"Error clicking 'Start a post' button (aria-label fallback): {e}") from e
        except Exception as e:
            _save_debug_info(self.page, "composer_button_error")
            raise LinkedInPostError(f"Error clicking 'Start a post' button (role-based): {e}") from e

        # Wait for the composer dialog to appear
        try:
            self.page.wait_for_selector('div[role="dialog"]', timeout=15000)
            logger.info("Post composer opened successfully.")
        except PlaywrightTimeoutError as e:
            _save_debug_info(self.page, "composer_dialog_timeout")
            raise LinkedInPostError(f"Timeout waiting for post composer dialog: {e}") from e
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
            post_button.click(timeout=10000)
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