# downloader_selenium.py  —  safe dedupe + slower pacing
import os
import re
import time
import random
import logging
import requests
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --------------------
# CONFIG
# --------------------
USERNAME = "it@proleadersco.com"
PASSWORD = "P@ss2022"
LOGIN_URL = "https://onmeeting.co/login"

VIDEO_PAGES = [
    "https://onmeeting.co/dashbord/recordings/18016307035",
    "https://onmeeting.co/dashbord/recordings/26290648768",
    "https://onmeeting.co/dashbord/recordings/28449434290",
    "https://onmeeting.co/dashbord/recordings/34936951505",
    "https://onmeeting.co/dashbord/recordings/45260422857",
    "https://onmeeting.co/dashbord/recordings/80419386778",
    "https://onmeeting.co/dashbord/recordings/86064245273",
    "https://onmeeting.co/dashbord/recordings/92616174648",
    "https://onmeeting.co/dashbord/recordings/96567313216",
    "https://onmeeting.co/dashbord/recordings/16421949030",
    "https://onmeeting.co/dashbord/recordings/39295435586",
]

# Root downloads dir
DOWNLOAD_ROOT = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

# Per-run subfolder (timestamp)
RUN_STAMP = time.strftime("%Y%m%d_%H%M%S")
RUN_DIR = os.path.join(DOWNLOAD_ROOT, RUN_STAMP)
os.makedirs(RUN_DIR, exist_ok=True)

# We will read/write BOTH names so older setups keep working
LOG_FILES = [
    os.path.join(DOWNLOAD_ROOT, "downloaded"),        # matches your screenshot name
    os.path.join(DOWNLOAD_ROOT, "downloaded.txt"),    # also keep .txt variant
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("onmeeting-downloader")

# --------------------
# Throttle / polite browsing settings (SLOWER now)
# --------------------
THROTTLE = {
    "between_actions": (1.2, 2),        # was ~0.8-1.7
    "between_page_loads": (10.0, 15.0),   # was ~6-10
    "post_login": 10.0,                    # was 3
    "post_download": (15.0, 20.0),        # was 8-15
    "backoff_initial": 50,                # was 30
    "backoff_max": 180,                   # was 180
}

ALLOWED_EXTS = (".mp4", ".mkv", ".webm", ".mov")

# --------------------
# Helpers
# --------------------

def _sleep(lo, hi=None):
    time.sleep(float(lo) if hi is None else random.uniform(lo, hi))

def save_debug(driver, tag="error"):
    ts = int(time.time())
    ss = os.path.join(RUN_DIR, f"debug_{tag}_{ts}.png")
    html = os.path.join(RUN_DIR, f"debug_{tag}_{ts}.html")
    try:
        driver.save_screenshot(ss)
        with open(html, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info("Saved debug files: %s, %s", ss, html)
    except Exception as e:
        logger.exception("Failed to save debug files: %s", e)

def _possible_download_dirs():
    dirs = {os.path.abspath(RUN_DIR)}
    try:
        home = os.path.expanduser("~")
        dirs.add(os.path.join(home, "Downloads"))
    except Exception:
        pass
    return [d for d in dirs if d and os.path.isdir(d)]

def _any_crdownload_present():
    for d in _possible_download_dirs():
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith(".crdownload"):
                    return True
        except Exception:
            continue
    return False

def _wait_for_downloads_completion(timeout_sec=900, poll_sec=2):
    start = time.time()
    time.sleep(2)
    while True:
        if not _any_crdownload_present():
            return
        if (time.time() - start) > timeout_sec:
            return
        time.sleep(poll_sec)

def _pick_new_file(since_ts):
    newest_path = None
    newest_mtime = -1
    for d in _possible_download_dirs():
        try:
            for fn in os.listdir(d):
                if not fn.lower().endswith(ALLOWED_EXTS):
                    continue
                p = os.path.join(d, fn)
                try:
                    mt = os.path.getmtime(p)
                except Exception:
                    continue
                if mt >= since_ts - 1 and mt > newest_mtime:
                    newest_mtime = mt
                    newest_path = p
        except Exception:
            continue
    return newest_path

def _looks_like_block_page(html_lower):
    needles = ("too many requests","429","rate limit","ddos","just a moment","access denied","captcha","cf-chl-bypass")
    return any(n in html_lower for n in needles)

def polite_get(driver, url):
    _sleep(*THROTTLE["between_page_loads"])
    driver.get(url)
    try:
        html_lower = driver.page_source.lower()
    except Exception:
        html_lower = ""
    if _looks_like_block_page(html_lower):
        backoff = THROTTLE["backoff_initial"]
        attempt = 1
        while attempt <= 4:
            logger.warning("Possible block page detected. Backing off %ss (attempt %d/4).", backoff, attempt)
            time.sleep(backoff + random.uniform(0, 5))
            driver.get("about:blank")
            _sleep(1.0)
            driver.get(url)
            try:
                html_lower = driver.page_source.lower()
            except Exception:
                html_lower = ""
            if not _looks_like_block_page(html_lower):
                break
            attempt += 1
            backoff = min(backoff * 2, THROTTLE["backoff_max"])

def detect_recaptcha(driver):
    for f in driver.find_elements(By.TAG_NAME, "iframe"):
        src = (f.get_attribute("src") or "").lower()
        if "recaptcha" in src:
            return True
    return False

# --------------------
# Persistent dedupe log
# --------------------

def _load_downloaded_keys():
    """
    Returns a set of unique recording keys we've already downloaded.
    Supports lines like:
      KEY|E:\\onmeeting-downloader\\downloads\\Recording_2025-09-23_13-37-00.mp4
    and legacy lines that may contain only a saved path.
    """
    keys = set()
    for lf in LOG_FILES:
        if os.path.exists(lf):
            try:
                with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if "|" in line:
                            k, _ = line.split("|", 1)
                            if k.strip():
                                keys.add(k.strip())
                        else:
                            # legacy path-only line – keep as-is so we never re-log it,
                            # though it won't help with URL-key matching
                            keys.add(line)
            except Exception:
                pass
    return keys

def _append_downloaded(key, final_path):
    """
    Append to BOTH log files to keep compatibility with your previous setup.
    """
    line = f"{key}|{os.path.abspath(final_path)}\n"
    for lf in LOG_FILES:
        try:
            with open(lf, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            # Don't crash if one file can't be written
            pass

def _recording_key_from_url(url: str) -> str:
    """
    Try to extract a stable key from /rec/play/<KEY> part of the URL.
    If not found, use the full URL as a fallback.
    """
    try:
        path = urlparse(url).path
    except Exception:
        path = url or ""
    m = re.search(r"/rec/play/([^/?#]+)", path)
    return m.group(1) if m else (url or "unknown")

# --------------------
# Login
# --------------------

def selenium_login():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # Reduce Chrome background network chatter & set download dir to per-run folder
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "autofill.profile_enabled": False,
        "autofill.credit_card_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
        "download.default_directory": os.path.abspath(RUN_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-features=PreconnectToSearchProvider,NetworkPrediction,Translate")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    wait = WebDriverWait(driver, 25)

    try:
        polite_get(driver, LOGIN_URL)
        logger.info("Opened login page")

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Try cookie/consent buttons (English/Arabic)
        for xp in [
            "//button[contains(., 'I understand')]",
            "//button[contains(., 'Accept')]",
            "//button[contains(., 'Accept all')]",
            "//button[contains(., 'موافق')]",
            "//button[contains(., 'قبول')]",
        ]:
            try:
                el = driver.find_element(By.XPATH, xp)
                if el.is_displayed() and el.is_enabled():
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                    logger.info("Clicked consent button")
                    _sleep(*THROTTLE["between_actions"])
                    break
            except Exception:
                pass

        # Simple login form
        def find_first(locator_list):
            for by, val in locator_list:
                els = driver.find_elements(by, val)
                for e in els:
                    try:
                        if e.is_displayed() and e.is_enabled():
                            return e
                    except Exception:
                        pass
            return None

        email_el = find_first([
            (By.NAME, "email"),
            (By.ID, "email"),
            (By.CSS_SELECTOR, "input[type='email']"),
        ])
        pass_el = find_first([
            (By.NAME, "password"),
            (By.ID, "password"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ])
        login_btn = find_first([
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.XPATH, "//button[@type='submit']"),
            (By.XPATH, "//button[contains(., 'Login') or contains(., 'Sign in') or contains(., 'تسجيل الدخول')]"),
        ])

        if detect_recaptcha(driver):
            save_debug(driver, "recaptcha")
            driver.quit()
            raise RuntimeError("reCAPTCHA detected - manual intervention required")

        if not (email_el and pass_el):
            save_debug(driver, "locate_inputs_failed")
            driver.quit()
            raise RuntimeError("Login inputs not found")

        email_el.clear(); email_el.send_keys(USERNAME)
        pass_el.clear();  pass_el.send_keys(PASSWORD)
        (login_btn or pass_el).click()
        logger.info("Clicked login button")

        wait.until(EC.url_contains("/dashbord/meeting"))
        logger.info("Login successful - reached /dashbord/meeting")
        _sleep(THROTTLE["post_login"])

        # hand off cookies to requests session (future use)
        session = requests.Session()
        for c in driver.get_cookies():
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"))
        session.headers.update({"User-Agent": driver.execute_script("return navigator.userAgent;")})

        return driver, session

    except Exception as e:
        logger.exception("Exception during selenium_login: %s", e)
        raise

# --------------------
# Core downloading
# --------------------

def _unique_target_path(base_dir):
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    base = f"Recording_{ts}.mp4"
    path = os.path.join(base_dir, base)
    k = 1
    while os.path.exists(path):
        path = os.path.join(base_dir, f"Recording_{ts}_{k}.mp4")
        k += 1
    return path

def process_video_page(driver, session, page_url, downloaded_keys):
    logger.info("Checking recordings page: %s", page_url)
    polite_get(driver, page_url)
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    _sleep(1.2)

    # Limit search to the recordings area so we don't touch the sidebar
    try:
        container = driver.find_element(By.CSS_SELECTOR, "div.recordParentSlug")
    except Exception:
        container = driver

    play_buttons = container.find_elements(
        By.XPATH,
        ".//button[contains(@class,'itemMenuEmploy') or normalize-space(.)='تشغيل' or translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='play']"
    )

    if not play_buttons:
        logger.warning("No Play buttons found on: %s", page_url)
        save_debug(driver, "no_play_buttons_found")
        return

    logger.info("Found %d Play buttons on this page.", len(play_buttons))

    for idx in range(len(play_buttons)):
        try:
            # Re-open page and container each iteration (kept for stability), but politely
            polite_get(driver, page_url)
            WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            _sleep(1.0)
            try:
                container = driver.find_element(By.CSS_SELECTOR, "div.recordParentSlug")
            except Exception:
                container = driver

            play_buttons = container.find_elements(
                By.XPATH,
                ".//button[contains(@class,'itemMenuEmploy') or normalize-space(.)='تشغيل' or translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='play']"
            )
            if idx >= len(play_buttons):
                logger.info("Index %d out of range after reload (have %d). Stopping.", idx, len(play_buttons))
                break

            btn = play_buttons[idx]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            _sleep(*THROTTLE["between_actions"])

            before_handles = set(driver.window_handles)
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)

            _sleep(0.8)
            after_handles = set(driver.window_handles)
            new_handles = list(after_handles - before_handles)
            new_tab = None
            if new_handles:
                new_tab = new_handles[0]
                driver.switch_to.window(new_tab)

            # Wait for /rec/play/
            try:
                WebDriverWait(driver, 25).until(EC.url_contains("/rec/play/"))
            except Exception:
                save_debug(driver, f"no_rec_play_after_click_{idx+1}")
                if new_tab:
                    driver.close()
                    driver.switch_to.window(list(before_handles)[0])
                else:
                    polite_get(driver, page_url)
                continue

            # --- NEW: dedupe by recording key from URL ---
            rec_key = _recording_key_from_url(driver.current_url)
            if rec_key in downloaded_keys:
                logger.info("Already downloaded (key=%s). Skipping.", rec_key)
                _sleep(0.8)
                if new_tab:
                    driver.close()
                    driver.switch_to.window(list(before_handles)[0])
                else:
                    try:
                        driver.back()
                    except Exception:
                        polite_get(driver, page_url)
                continue

            # Click the orange download button
            try:
                dl = WebDriverWait(driver, 25).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.download_buttonDownload__gocit"))
                )
            except Exception:
                dl = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'download') or contains(., 'تحميل')]"))
                )

            click_ts = time.time()
            try:
                dl.click()
            except Exception:
                driver.execute_script("arguments[0].click();", dl)

            logger.info("Clicked download for recording key: %s", rec_key)
            _wait_for_downloads_completion()

            # Rename the newest downloaded file into RUN_DIR with a unique timestamped name
            newest = _pick_new_file(click_ts)
            if newest:
                target = _unique_target_path(RUN_DIR)
                try:
                    os.replace(newest, target)
                    logger.info("Saved as: %s", os.path.basename(target))
                    # Log & remember so future runs skip it
                    _append_downloaded(rec_key, target)
                    downloaded_keys.add(rec_key)
                except Exception as e:
                    logger.warning("Could not move %s -> %s: %s", newest, target, e)
            else:
                logger.warning("No new file detected after download; skip renaming.")

            # polite cooldown after each download
            _sleep(*THROTTLE["post_download"])

            # Back to recordings list
            if new_tab:
                driver.close()
                driver.switch_to.window(list(before_handles)[0])
            else:
                try:
                    driver.back()
                except Exception:
                    polite_get(driver, page_url)
            _sleep(1.0)

        except Exception as e:
            logger.warning("Failed processing item %d: %s", idx + 1, e)
            save_debug(driver, f"item_error_{idx+1}")
            try:
                polite_get(driver, page_url)
                _sleep(1.0)
            except Exception:
                pass

# --------------------
# Main
# --------------------

def main():
    driver = None
    try:
        # Load persistent dedupe set once
        downloaded_keys = _load_downloaded_keys()

        driver, session = selenium_login()
        for page in VIDEO_PAGES:
            try:
                process_video_page(driver, session, page, downloaded_keys)
            except Exception:
                logger.exception("Failed processing page %s", page)
                if driver:
                    save_debug(driver, f"page_error_{int(time.time())}")
            # polite pause between pages
            _sleep(*THROTTLE["between_page_loads"])
    except Exception as e:
        logger.error("Fatal error: %s", e)
        try:
            if driver:
                save_debug(driver, "fatal")
                driver.quit()
        except Exception:
            pass
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        logger.info("Finished run")

if __name__ == "__main__":
    main()
