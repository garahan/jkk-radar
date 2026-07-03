import os
import sys
import time
import json
import re
import math

# Ensure output is not buffered (important for CI logs)
sys.stdout.reconfigure(line_buffering=True)
import requests as http_requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# --- CONFIGURATION ---
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"
GEOCACHE_FILE = "geocache.json"

# Reference point: Shinjuku, Tokyo
SHINJUKU_LAT = 35.69376
SHINJUKU_LON = 139.70343

MAX_RENT = 80000


def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    prefs = {"profile.default_content_setting_values.popups": 1}
    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=chrome_options)

    stealth(
        driver,
        languages=["ja-JP", "ja", "en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = {runtime: {}};
            """
        },
    )

    return driver


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
    queries = [address, f"{address}, Tokyo, Japan", f"{address}, \u6771\u4eac\u90fd"]

    for query in queries:
        try:
            location = geolocator.geocode(query, timeout=10)
            if location:
                result = {"lat": location.latitude, "lon": location.longitude}
                cache[address] = result
                time.sleep(1.1)
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
        map_url = apt.get('maps_url', '')
        train_min = apt.get('train_min', None)
        text = (
            f"\U0001f3e0 *JKK Apartment Alert!*\n\n"
            f"\U0001f4cd *{apt['name']}*\n"
            f"\U0001f4b0 \u00a5{apt['price_display']}/month\n"
            f"\U0001f3e2 {apt['area']} | {apt['layout']}\n"
            f"\U0001f4cf {apt['distance_km']:.1f} km from Shinjuku\n"
        )
        if train_min:
            text += f"\U0001f687 ~{train_min} min by train from Shinjuku\n"
        text += f"\U0001f4d0 {apt['floor_area']} m\u00b2\n"
        if map_url:
            text += f"\U0001f517 [View on Google Maps]({map_url})"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        try:
            resp = http_requests.post(url, json=payload, timeout=10)
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
        f"Scanned {total} listings \u2022 {new_count} new affordable apartments"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        http_requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


def navigate_to_search(driver):
    """Navigate to JKK and handle any redirect/popup pages."""
    driver.get(JKK_URL)
    time.sleep(3)

    # The site may redirect or open in same window. Check current state.
    current_url = driver.current_url
    title = driver.title
    print(f"Landed on: {title} ({current_url})")

    # If we hit the "おわび" (apology/maintenance) page, the site might be
    # blocking us. Try once more after a delay.
    page_source = driver.page_source
    if "\u304a\u308f\u3073" in title or "\u304a\u308f\u3073" in page_source:
        print("Hit maintenance page. Retrying after delay...")
        time.sleep(5)
        driver.get(JKK_URL)
        time.sleep(5)
        title = driver.title
        if "\u304a\u308f\u3073" in title:
            print("Still on maintenance page. Bot detection likely active.")
            return False

    # Handle "こちら" redirect link if present
    try:
        redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "\u3053\u3061\u3089")
        redirect_link.click()
        time.sleep(3)
    except Exception:
        pass

    # Handle popup windows if they opened
    all_windows = driver.window_handles
    if len(all_windows) > 1:
        driver.switch_to.window(all_windows[-1])
        print(f"Switched to window: {driver.title}")

    return True


def perform_search(driver):
    """Check ward area and click search using JavaScript."""
    wait = WebDriverWait(driver, 15)

    # Wait for the form to load
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.NAME, "akiyaInitRM.akiyaRefM.allCheck")
            )
        )
    except Exception:
        print("Search form not found.")
        return False

    # Check "区部" (all wards) via JavaScript
    driver.execute_script("""
        var checkboxes = document.querySelectorAll(
            'input[name="akiyaInitRM.akiyaRefM.allCheck"]'
        );
        for (var cb of checkboxes) {
            if (cb.getAttribute('text') === 'ALLKU' && !cb.checked) {
                cb.click();
            }
        }
    """)
    print("Checked all ward checkboxes.")
    time.sleep(1)

    # Click the search button via JavaScript
    driver.execute_script("""
        var imgs = document.querySelectorAll('img[name="Image1"]');
        if (imgs.length > 0) {
            imgs[0].parentElement.click();
        }
    """)
    print("Clicked search.")

    # Wait for results page to load
    time.sleep(5)

    # Verify we're on the results page
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//form[@name='frmMain']")
            )
        )
        print("Results page loaded.")
        return True
    except Exception:
        print("Results page did not load.")
        return False


def parse_results(driver):
    """Parse the results table from the search results page."""
    apartments = []

    # Find all data rows in the results table
    # The results table has header row with: 住宅外観, 住宅名, 地域, 優先種別,
    # 住宅種別, 間取り, 床面積[m2], 家賃[円], 共益費[円], 募集戸数
    # followed by data rows with matching <td> cells + a detail button
    rows = driver.find_elements(
        By.XPATH,
        "//form[@name='frmMain']//table//tr[.//img[contains(@src,'bt2_syousai')]]",
    )

    if not rows:
        # Fallback: try finding rows with detail images
        rows = driver.find_elements(
            By.XPATH,
            "//tr[.//img[contains(@name,'Image')]]",
        )

    print(f"Found {len(rows)} result rows.")

    for row in rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 8:
                continue

            # cells layout: [image, name, area, priority_type, housing_type,
            #                layout, floor_area, rent, common_fee, units, detail]
            name = cells[1].text.strip()
            area = cells[2].text.strip()
            layout = cells[5].text.strip()
            floor_area = cells[6].text.strip()
            rent_text = cells[7].text.strip()

            # Skip header/junk rows
            if not name or "\u4f4f\u5b85" in name or "\u25a0" in name:
                continue
            if not re.search(r"\d", rent_text):
                continue

            # Parse rent range like "206,800～233,400"
            rent_nums = re.findall(r"[\d,]+", rent_text)
            if rent_nums:
                # Use the lowest rent
                price_min = min(int(n.replace(",", "")) for n in rent_nums)
            else:
                price_min = 999999

            # Create a unique ID from name + layout
            uid = f"{name}_{layout}"

            apartments.append(
                {
                    "name": name,
                    "area": area,
                    "layout": layout,
                    "floor_area": floor_area,
                    "price": price_min,
                    "price_display": rent_text,
                    "uid": uid,
                }
            )

        except Exception as e:
            print(f"Error parsing row: {e}")
            continue

    return apartments


def scrape_jkk(driver):
    """Full scraping pipeline: navigate, search, parse."""
    if not navigate_to_search(driver):
        return []

    if not perform_search(driver):
        return []

    # First, increase results per page to 50 to reduce pagination
    try:
        driver.execute_script("""
            var sel = document.querySelector(
                'select[name="akiyaRefRM.showCount"]'
            );
            if (sel) {
                sel.value = '50';
                sel.dispatchEvent(new Event('change'));
            }
        """)
        time.sleep(3)
    except Exception:
        pass

    apartments = parse_results(driver)
    seen_uids = {a["uid"] for a in apartments}

    # Check for pagination (max 20 pages as safety limit)
    for page in range(2, 21):
        try:
            next_links = driver.find_elements(
                By.XPATH, "//a[contains(text(), '\u5f8c\u308d\u3078')]"
            )
            if not next_links:
                break
            next_links[0].click()
            time.sleep(3)
            print(f"Scraping page {page}...")
            more = parse_results(driver)
            # Detect duplicate results (means we've looped)
            new_items = [a for a in more if a["uid"] not in seen_uids]
            if not new_items:
                print("No new results on this page, stopping pagination.")
                break
            apartments.extend(new_items)
            seen_uids.update(a["uid"] for a in new_items)
        except Exception:
            break

    return apartments


def main():
    print("Starting JKK Radar...")
    driver = setup_driver()
    geocache = load_json_file(GEOCACHE_FILE)
    seen_apartments = load_json_file(SEEN_FILE)

    try:
        apartments = scrape_jkk(driver)
        print(f"Total apartments found: {len(apartments)}")

        if not apartments:
            print("No apartments found. Site may be blocking or empty.")
            return

        # Geocode using apartment name + area
        for apt in apartments:
            geo_query = f"{apt['name']} {apt['area']}, \u6771\u4eac\u90fd"
            geo = geocode_address(geo_query, geocache)
            if not geo:
                geo = geocode_address(f"{apt['area']}, \u6771\u4eac\u90fd", geocache)
            if geo:
                apt["distance_km"] = haversine_km(
                    SHINJUKU_LAT,
                    SHINJUKU_LON,
                    geo["lat"],
                    geo["lon"],
                )
                apt["lat"] = geo["lat"]
                apt["lon"] = geo["lon"]
                apt["maps_url"] = f"https://www.google.com/maps?q={geo['lat']},{geo['lon']}"
                # Estimate train time: Tokyo avg train speed ~25 km/h + 8 min station access
                apt["train_min"] = int(round(apt["distance_km"] / 25 * 60 + 8))
            else:
                apt["distance_km"] = float("inf")
                apt["lat"] = None
                apt["lon"] = None
                apt["maps_url"] = ""
                apt["train_min"] = None

        save_json_file(GEOCACHE_FILE, geocache)

        # Filter by max rent
        affordable = [a for a in apartments if a["price"] <= MAX_RENT]
        print(f"After rent filter (<=\u00a5{MAX_RENT:,}): {len(affordable)} apartments")

        # Sort by distance (ascending), then price
        affordable.sort(key=lambda a: (a["distance_km"], a["price"]))

        # Save ALL results for web dashboard (unfiltered, sorted by distance)
        all_sorted = sorted(apartments, key=lambda a: (a["distance_km"], a["price"]))
        import datetime
        results = {
            "last_updated": datetime.datetime.now().isoformat(),
            "total": len(all_sorted),
            "affordable_count": len(affordable),
            "max_rent": MAX_RENT,
            "apartments": [
                {
                    "name": a["name"],
                    "area": a["area"],
                    "layout": a["layout"],
                    "floor_area": a["floor_area"],
                    "price": a["price"],
                    "price_display": a["price_display"],
                    "distance_km": round(a["distance_km"], 1) if a["distance_km"] != float("inf") else None,
                    "train_min": a.get("train_min"),
                    "lat": a.get("lat"),
                    "lon": a.get("lon"),
                    "maps_url": a.get("maps_url", ""),
                    "uid": a["uid"],
                    "affordable": a["price"] <= MAX_RENT,
                }
                for a in all_sorted
            ],
        }
        save_json_file("results.json", results)
        print("Saved results.json for dashboard.")

        # Filter out already-seen apartments (only notify NEW ones)
        new_apartments = [a for a in affordable if a["uid"] not in seen_apartments]
        print(f"New affordable apartments: {len(new_apartments)}")

        if new_apartments:
            # Deduplicate by building name — keep the cheapest unit per building
            seen_buildings = set()
            unique_buildings = []
            for a in new_apartments:
                if a["name"] not in seen_buildings:
                    seen_buildings.add(a["name"])
                    unique_buildings.append(a)

            # Sort by best match: closest + cheapest (combined score)
            unique_buildings.sort(key=lambda a: (a["distance_km"], a["price"]))

            # Only alert top 5
            top5 = unique_buildings[:5]
            send_telegram_alert(top5)
            send_telegram_summary(len(apartments), len(new_apartments))

            # Save notification history
            import datetime
            notif_file = "notifications.json"
            notif_history = load_json_file(notif_file) if os.path.exists(notif_file) else []
            notif_history.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "total_scanned": len(apartments),
                "new_count": len(new_apartments),
                "alerted": [
                    {
                        "name": a["name"],
                        "area": a["area"],
                        "price": a["price"],
                        "price_display": a["price_display"],
                        "distance_km": round(a["distance_km"], 1) if a["distance_km"] != float("inf") else None,
                        "train_min": a.get("train_min"),
                        "maps_url": a.get("maps_url", ""),
                    }
                    for a in top5
                ],
            })
            # Keep last 50 notifications
            notif_history = notif_history[-50:]
            save_json_file(notif_file, notif_history)
            print("Saved notifications.json")

            seen_apartments.extend(a["uid"] for a in new_apartments)
            seen_apartments = list(set(seen_apartments))
            save_json_file(SEEN_FILE, seen_apartments)
            print(f"Alerted on {len(top5)} unique buildings (from {len(new_apartments)} new units).")
        else:
            print("No new affordable apartments since last scan.")

    except Exception as e:
        print(f"Critical error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
