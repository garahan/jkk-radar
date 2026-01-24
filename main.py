import os
import time
import json
import re
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from discord_webhook import DiscordWebhook, DiscordEmbed

# --- CONFIGURATION ---
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"
MAX_RENT = 110000

# Debug artifacts (saved to repo workspace; upload via actions/upload-artifact)
DEBUG_DIR = Path("debug_artifacts")
DEBUG_DIR.mkdir(exist_ok=True)


def setup_driver():
    chrome_options = Options()

    # New headless is more stable on modern Chrome (your runner shows chrome=144)
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=ja-JP")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    # Use a Linux UA to match GitHub Actions runner
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(45)
    return driver


def dump_debug(driver, tag: str):
    """Save screenshot + HTML to debug_artifacts/ for GitHub Actions upload."""
    try:
        ts = time.strftime("%Y%m%d-%H%M%S")
        png = DEBUG_DIR / f"{ts}-{tag}.png"
        html = DEBUG_DIR / f"{ts}-{tag}.html"
        driver.save_screenshot(str(png))
        html.write_text(driver.page_source, encoding="utf-8")
        print(f"🧩 Debug saved: {png} and {html}")
    except Exception as e:
        print(f"⚠️ Debug dump failed: {e}")


def load_seen():
    if Path(SEEN_FILE).exists():
        try:
            return json.loads(Path(SEEN_FILE).read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_seen(seen_list):
    Path(SEEN_FILE).write_text(json.dumps(list(dict.fromkeys(seen_list))), encoding="utf-8")


def send_discord_alert(title, price, size, link):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url:
        return
    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(
        title=f"Found: {title}",
        description=f"Rent: {price}\nSize: {size}",
        color="57F287",
    )
    embed.set_url(link)
    webhook.add_embed(embed)
    webhook.execute()


def find_in_any_frame(driver, by, value, timeout=15, clickable=False):
    """
    Find element in default content or any iframe.
    Returns (element, frame_index) where frame_index is None if in default.
    """
    end = time.time() + timeout
    last_err = None

    while time.time() < end:
        # 1) default content
        try:
            driver.switch_to.default_content()
            if clickable:
                el = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, value)))
            else:
                el = WebDriverWait(driver, 2).until(EC.presence_of_element_located((by, value)))
            return el, None
        except Exception as e:
            last_err = e

        # 2) each iframe
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for idx, frame in enumerate(frames):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if clickable:
                    el = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, value)))
                else:
                    el = WebDriverWait(driver, 2).until(EC.presence_of_element_located((by, value)))
                print(f"ℹ️ Using iframe #{idx}")
                return el, idx
            except Exception as e:
                last_err = e
                continue

        time.sleep(0.5)

    raise last_err if last_err else Exception("Element not found (unknown error)")


def js_click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    driver.execute_script("arguments[0].click();", element)


def parse_price_yen(text: str) -> int:
    """
    Extracts the first comma-formatted number as price.
    Adjust if your table format differs.
    """
    nums = [int(s.replace(",", "")) for s in re.findall(r"\b\d{1,3}(?:,\d{3})+\b", text)]
    return nums[0] if nums else 999999


def main():
    print("Starting JKK Bot (CI-safe)...")
    driver = setup_driver()
    seen_apartments = load_seen()

    try:
        driver.get(JKK_URL)
        print(f"Landed on: {driver.title}")

        # Wait for the page to render something meaningful
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")

        # If there is a blocking modal/overlay, this is where you'd add dismissal logic.
        # Keep this minimal: artifacts will show if a modal blocks interaction.
        dump_debug(driver, "landed")

        # --- STEP 1: Check "区部" (Ward area) ---
        # Prefer an input associated with a label containing 区部.
        ward_xpath = (
            "//label[contains(normalize-space(),'区部')]/following::input[@type='checkbox'][1]"
            " | //label[contains(normalize-space(),'区部')]/preceding::input[@type='checkbox'][1]"
            " | //input[@type='checkbox' and (contains(@title,'区部') or contains(@aria-label,'区部'))]"
        )

        print("Selecting Ward area (区部)...")
        try:
            ward_el, _ = find_in_any_frame(driver, By.XPATH, ward_xpath, timeout=18, clickable=False)

            # In some sites the label is clickable but input is hidden; handle both safely:
            try:
                checked = ward_el.is_selected()
            except Exception:
                checked = False

            if not checked:
                js_click(driver, ward_el)
                time.sleep(0.5)
            print("✅ Ward filter applied (or already set).")
        except Exception as e:
            print(f"❌ Failed to set Ward filter: {e}")
            dump_debug(driver, "fail-ward")
            # Continue anyway; maybe the default already includes wards.

        # --- STEP 2: Click Search (検索する) ---
        search_xpath = (
            "//button[contains(normalize-space(),'検索する') or contains(normalize-space(),'検索')]"
            " | //a[contains(normalize-space(),'検索する') or contains(normalize-space(),'検索')]"
            " | //input[(@type='submit' or @type='button') and (contains(@value,'検索する') or contains(@value,'検索'))]"
            " | //img[contains(@alt,'検索する') or contains(@alt,'検索')]"
        )

        print("Clicking Search (検索する)...")
        try:
            search_el, _ = find_in_any_frame(driver, By.XPATH, search_xpath, timeout=18, clickable=True)
            js_click(driver, search_el)
            print("✅ Search clicked.")
        except Exception as e:
            print(f"❌ Failed to click Search: {e}")
            dump_debug(driver, "fail-search")
            return

        # --- STEP 3: Wait for results table ---
        # Results might be in a different frame after navigation.
        # Look for rows containing 詳細 or href containing detail, or a recognizable results table.
        result_row_xpath = (
            "//tr[.//a[contains(normalize-space(),'詳細')]"
            " or .//img[contains(@alt,'詳細')]"
            " or .//a[contains(@href,'detail')]]"
        )

        print("Waiting for results...")
        try:
            # Give enough time for server + JS
            row_el, _ = find_in_any_frame(driver, By.XPATH, result_row_xpath, timeout=25, clickable=False)
            # Ensure we are in the correct frame context and collect rows
            rows = driver.find_elements(By.XPATH, result_row_xpath)
            print(f"Found {len(rows)} listings.")
            dump_debug(driver, "results-loaded")
        except Exception as e:
            print(f"❌ Results not found: {e}")
            dump_debug(driver, "fail-results")
            return

        # --- STEP 4: Scrape + filter + alert ---
        new_finds = 0
        current_scan_links = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ").strip()

                # Link extraction: try common patterns
                link = None
                link_candidates = row.find_elements(
                    By.XPATH,
                    ".//a[contains(@href,'detail') or contains(normalize-space(),'詳細')]",
                )
                if link_candidates:
                    link = link_candidates[0].get_attribute("href")

                if not link:
                    # If 詳細 is an image inside a link
                    link_candidates = row.find_elements(By.XPATH, ".//a[.//img[contains(@alt,'詳細')]]")
                    if link_candidates:
                        link = link_candidates[0].get_attribute("href")

                if not link:
                    continue

                current_scan_links.append(link)

                price_int = parse_price_yen(text)

                if link in seen_apartments:
                    continue

                if price_int <= MAX_RENT:
                    # Title heuristic: first token; adjust if needed
                    title = (text.split(" ")[0] if text else "JKK Listing")
                    send_discord_alert(title, f"{price_int} JPY", "See listing", link)
                    print(f"✅ ALERT: {title} ({price_int}) {link}")
                    new_finds += 1

            except Exception:
                continue

        if current_scan_links:
            # Always update seen with scanned links to avoid repeat spam
            seen_apartments.extend(current_scan_links)
            save_seen(seen_apartments)

        print(f"Done. New alerts sent: {new_finds}")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        dump_debug(driver, "fatal")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
