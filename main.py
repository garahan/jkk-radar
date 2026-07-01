import os
import time
import json
import re
import math
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# --- CONFIGURATION ---
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"
GEOCACHE_FILE = "geocache.json"

# Apple Shinjuku store: 3-chome-29-1 Shinjuku, Shinjuku City, Tokyo
APPLE_SHINJUKU_LAT = 35.69376
APPLE_SHINJUKU_LON = 139.70343

MAX_DISTANCE_KM = 15.0
MAX_RENT = 150000


def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    prefs = {"profile.default_content_setting_values.popups": 1}
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_json_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {} if path.endswith("geocache.json") else []
    return {} if path.endswith("geocache.json") else []


def save_json_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def geocode_address(address, cache):
    if address in cache:
        return cache[address]

    geolocator = Nominatim(user_agent="jkk-radar-bot/1.0")
    queries = [address, f"{address}, Tokyo, Japan", f"{address}, 東京都"]

    for query in queries:
        try:
            location = geolocator.geocode(query, timeout=10)
            if location:
                result = {"lat": location.latitude, "lon": location.longitude}
                cache[address] = result
                time.sleep(1.1)  # respect Nominatim rate limit
                return result
        except GeocoderTimedOut:
            continue
        time.sleep(1.1)

    cache[address] = None
    return None


def send_telegram_alert(apartments):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Skipping.")
        return

    for apt in apartments:
        text = (
            f"\U0001f3e0 *JKK Apartment Near Apple Shinjuku!*\n\n"
            f"\U0001f4cd *{apt['name']}*\n"
            f"\U0001f4b0 \u00a5{apt['price']:,}/month\n"
            f"\U0001f4cf {apt['distance_km']:.1f} km from Apple Shinjuku\n"
            f"\U0001f517 [View Details]({apt['link']})"
        )
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"Telegram alert sent: {apt['name']}")
            else:
                print(f"Telegram error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Telegram send failed: {e}")


def send_telegram_summary(total, new_count):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    if new_count == 0:
        return

    text = (
        f"\U0001f50d *JKK Radar Scan Complete*\n"
        f"Scanned {total} listings \u2022 {new_count} new near Apple Shinjuku"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


def scrape_jkk(driver):
    wait = WebDriverWait(driver, 20)

    driver.get(JKK_URL)
    print("Landed on redirection page.")

    try:
        redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "\u3053\u3061\u3089")
        redirect_link.click()
        print("Clicked redirect link.")
    except Exception:
        print("Redirect link not found, waiting for auto-popup...")

    time.sleep(5)

    all_windows = driver.window_handles
    print(f"Detected {len(all_windows)} windows.")
    if len(all_windows) > 1:
        driver.switch_to.window(all_windows[-1])
        print(f"Switched to: {driver.title}")

    try:
        wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']"))
        )
        ward_cb = driver.find_element(
            By.XPATH,
            "//label[contains(.,'\u533a\u90e8')]/preceding-sibling::input | "
            "//label[contains(.,'\u533a\u90e8')]/../input",
        )
        if not ward_cb.is_selected():
            driver.execute_script("arguments[0].click();", ward_cb)
            print("Checked Ward Area.")
    except Exception as e:
        print(f"Checkbox error: {e}")

    try:
        search_btn = driver.find_element(
            By.XPATH,
            "//img[contains(@alt,'\u691c\u7d22')] | "
            "//a[contains(text(),'\u691c\u7d22')] | "
            "//input[contains(@value,'\u691c\u7d22')]",
        )
        driver.execute_script("arguments[0].click();", search_btn)
        print("Clicked Search.")
    except Exception as e:
        print(f"Search button failed: {e}")

    print("Waiting for results...")
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
            )
        )
        print("Results loaded.")
    except Exception:
        print("No results found (timeout).")

    rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
    print(f"Found {len(rows)} listings.")

    apartments = []
    for row in rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            text = row.text.replace("\n", " ")
            link_el = row.find_element(
                By.XPATH, ".//a[contains(@href, 'detail')]"
            )
            link = link_el.get_attribute("href")

            name = link_el.text.strip()
            if not name and cells:
                name = cells[0].text.strip()

            raw_nums = re.findall(r"[0-9,]+", text)
            price_int = 999999
            for s in raw_nums:
                try:
                    val = int(s.replace(",", ""))
                    if val > 10000:
                        price_int = val
                        break
                except Exception:
                    continue

            address = ""
            for cell in cells:
                cell_text = cell.text.strip()
                if re.search(r"(\u533a|\u5e02|\u753a|\u4e01\u76ee)", cell_text):
                    address = cell_text
                    break
            if not address:
                address = name

            apartments.append(
                {
                    "name": name or "Unknown",
                    "price": price_int,
                    "link": link,
                    "address": address,
                }
            )
        except Exception:
            pass

    return apartments


def main():
    print("Starting JKK Radar...")
    driver = setup_driver()
    geocache = load_json_file(GEOCACHE_FILE)
    seen_apartments = load_json_file(SEEN_FILE)

    try:
        apartments = scrape_jkk(driver)
        print(f"Parsed {len(apartments)} apartments.")

        for apt in apartments:
            geo = geocode_address(apt["address"], geocache)
            if geo:
                apt["distance_km"] = haversine_km(
                    APPLE_SHINJUKU_LAT,
                    APPLE_SHINJUKU_LON,
                    geo["lat"],
                    geo["lon"],
                )
            else:
                apt["distance_km"] = float("inf")

        save_json_file(GEOCACHE_FILE, geocache)

        nearby_cheap = [
            a
            for a in apartments
            if a["distance_km"] <= MAX_DISTANCE_KM and a["price"] <= MAX_RENT
        ]
        nearby_cheap.sort(key=lambda a: (a["distance_km"], a["price"]))

        new_apartments = [
            a for a in nearby_cheap if a["link"] not in seen_apartments
        ]
        print(f"New nearby+cheap apartments: {len(new_apartments)}")

        if new_apartments:
            send_telegram_alert(new_apartments[:10])
            send_telegram_summary(len(apartments), len(new_apartments))

            seen_apartments.extend(a["link"] for a in new_apartments)
            seen_apartments = list(set(seen_apartments))
            save_json_file(SEEN_FILE, seen_apartments)
            print(f"Alerted on {min(len(new_apartments), 10)} apartments.")
        else:
            print("No new apartments matching criteria.")

    except Exception as e:
        print(f"Critical error: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
