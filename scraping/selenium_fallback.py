"""Selenium fallback for JS-rendered pages.

Most of our sources (State Dept, CDC) are static HTML and never need this. It
exists as a reusable helper the other scrapers call ONLY when a plain
``requests`` fetch comes back mostly empty. Selenium + Chrome are heavy, so we
import them lazily inside the function - the rest of the pipeline runs fine
without a browser installed.
"""

from __future__ import annotations

from typing import Optional

from config import settings


def fetch_rendered_html(url: str, *, wait_seconds: int = 3) -> Optional[str]:
    """Return fully rendered HTML for ``url`` using headless Chrome, or None.

    Requires Chrome/Chromium installed locally. ``webdriver-manager`` fetches a
    matching chromedriver automatically. Returns None (and prints a warning)
    rather than crashing if Selenium/Chrome aren't available.
    """
    try:
        import time

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        print(f"[selenium_fallback] Selenium not available: {exc}")
        return None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={settings.USER_AGENT}")
    # Root cause of the "Timed out receiving message from renderer" hang: the
    # default 'normal' strategy blocks driver.get() until the page fully loads,
    # but tourism SPAs keep long-lived connections (analytics, sockets) open and
    # never reach 'complete'. 'eager' returns at DOMContentLoaded; we then sleep
    # so client-side JS can fetch + paint the real content.
    options.page_load_strategy = "eager"

    driver = None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(settings.REQUEST_TIMEOUT)
        try:
            driver.get(url)
        except Exception as nav_exc:  # eager load can still time out on slow SPAs
            print(f"[selenium_fallback] get() slow on {url}, using partial DOM: {nav_exc}")
        time.sleep(wait_seconds)  # let client-side JS paint the content
        return driver.page_source
    except Exception as exc:  # driver setup failure
        print(f"[selenium_fallback] Failed to render {url}: {exc}")
        return None
    finally:
        if driver is not None:
            driver.quit()
