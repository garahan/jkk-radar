import os
import sys
import time
import json
import re
import math
import hashlib

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

# UR Chintai configuration
UR_API_BASE = "https://chintai.r6.ur-net.go.jp/chintai/api/"
UR_TDFK = "13"  # Tokyo prefecture
UR_AREAS = ["01", "02", "03", "04", "05", "06"]
UR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.ur-net.go.jp/chintai/kanto/tokyo/list/",
}


def calculate_match_score(price, distance_km, train_min, floor_area):
    """Calculate 1-5 star match score balancing cheap + close + short commute.

    Weights: price 40%, distance 30%, commute 30%.
    """
    if distance_km is None or distance_km == float("inf"):
        return 1
    if price is None or price <= 0:
        return 1

    # Price score: ¥20k=1.0, ¥80k=0.0 (linear)
    price_score = max(0, min(1, (MAX_RENT - price) / (MAX_RENT - 20000)))

    # Distance score: 0km=1.0, 40km=0.0 (linear)
    dist_score = max(0, min(1, (40 - distance_km) / 40))

    # Commute score: 0min=1.0, 100min=0.0 (linear)
    if train_min and train_min > 0:
        commute_score = max(0, min(1, (100 - train_min) / 100))
    else:
        commute_score = dist_score  # fallback to distance

    # Bonus for larger floor area (value for money)
    area_bonus = 0
    try:
        fa = float(floor_area)
        if fa >= 50:
            area_bonus = 0.1
        elif fa >= 40:
            area_bonus = 0.05
    except (ValueError, TypeError):
        pass

    # Weighted composite
    composite = (price_score * 0.40) + (dist_score * 0.30) + (commute_score * 0.30) + area_bonus
    composite = max(0, min(1, composite))

    # Convert to 1-5 stars (rounded to nearest 0.5)
    stars = round(composite * 4 + 1) / 2
    return max(1, min(5, stars))


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
        score = apt.get('match_score', 0)
        stars = '\u2b50' * int(score) + ('\u00bd' if score % 1 == 0.5 else '')
        source = apt.get('source', 'JKK')
        detail_url = apt.get('detail_url', '')
        text = (
            f"\U0001f3e0 *JKK Radar Alert! [{source}]*\n"
            f"{stars} ({score:.1f}/5 match)\n\n"
            f"\U0001f4cd *{apt['name']}*\n"
            f"\U0001f4b0 \u00a5{apt['price_display']}/month\n"
            f"\U0001f3e2 {apt['area']} | {apt['layout']}\n"
            f"\U0001f4cf {apt['distance_km']:.1f} km from Shinjuku\n"
        )
        if train_min:
            text += f"\U0001f687 ~{train_min} min by train from Shinjuku\n"
        text += f"\U0001f4d0 {apt['floor_area']} m\u00b2\n"
        if map_url:
            text += f"\U0001f517 [Google Maps]({map_url})\n"
        if detail_url:
            text += f"\U0001f4cc [Listing Detail]({detail_url})"
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


def send_telegram_removed(removed_apartments):
    """Send alert for apartments that disappeared from listings."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    if not removed_apartments:
        return

    for apt in removed_apartments[:5]:
        text = (
            f"\u274c *Listing Removed*\n\n"
            f"\U0001f4cd *{apt['name']}*\n"
            f"\U0001f4b0 \u00a5{apt.get('price_display', apt.get('price', '?'))}/month\n"
            f"\U0001f3e2 {apt.get('area', '')} | {apt.get('layout', '')}\n"
        )
        if apt.get('distance_km'):
            text += f"\U0001f4cf {apt['distance_km']}km from Shinjuku\n"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            http_requests.post(url, json=payload, timeout=10)
            print(f"Removed listing alert sent: {apt['name']}")
        except Exception:
            pass


def send_daily_digest(active_listings, new_count, removed_count):
    """Send a daily summary digest to Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    import datetime
    from datetime import timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now_str = datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")

    affordable = [a for a in active_listings if a.get("price", 0) <= MAX_RENT]
    avg_price = sum(a["price"] for a in affordable) / len(affordable) if affordable else 0
    avg_dist = sum(a.get("distance_km", 0) for a in affordable if a.get("distance_km")) / max(1, len([a for a in affordable if a.get("distance_km")]))

    text = (
        f"\U0001f4ca *Daily Digest*\n"
        f"_{now_str}_\n\n"
        f"*Active listings:* {len(active_listings)}\n"
        f"*Affordable (\u2264\u00a5{MAX_RENT:,}):* {len(affordable)}\n"
        f"*Avg rent:* \u00a5{int(avg_price):,}/mo\n"
        f"*Avg distance:* {avg_dist:.1f}km\n\n"
        f"*Since last digest:*\n"
    )
    if new_count:
        text += f"  \u2705 {new_count} new listing(s)\n"
    if removed_count:
        text += f"  \u274c {removed_count} removed\n"
    if not new_count and not removed_count:
        text += "  No changes detected.\n"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        http_requests.post(url, json=payload, timeout=10)
        print("Daily digest sent.")
    except Exception:
        pass


# --- TELEGRAM BOT COMMANDS ---
TG_OFFSET_FILE = "telegram_offset.txt"
TG_MAX_RESULTS = 10

def _fp_rank(plan):
    """Numeric rank for floor plan comparison (higher = larger)."""
    if not plan:
        return -1
    m = re.match(r"^(\d+)(R|LDK|DK|D|K)$", plan.strip().upper())
    if not m:
        return -1
    rooms = int(m.group(1))
    suffix_rank = {"R": 0, "K": 1, "D": 2, "DK": 3, "LDK": 4}.get(m.group(2), -1)
    return rooms * 10 + suffix_rank if suffix_rank >= 0 else -1

def _parse_tg_command(text):
    """Parse a backslash command. Returns (cmd_type, arg) or None."""
    if not text or not text.strip().startswith("\\"):
        return None
    text = text.strip()
    for pattern, cmd in (
        (r"^\\rent(\d+)$", "rent"),
        (r"^\\size(\d+(?:\.\d+)?)$", "size"),
        (r"^\\plan(\w+)$", "plan"),
        (r"^\\top$", "top"),
        (r"^\\help$", "help"),
    ):
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            return (cmd, m.group(1))
    m = re.match(r"^\\([\w\u3000-\u9fff\u30a0-\u30ff]+)$", text)
    if m:
        return ("ward", m.group(1))
    return None

def _filter_for_command(listings, cmd_type, arg):
    if cmd_type == "ward":
        q = arg.lower().replace("ward", "").replace("\u533a", "").strip()
        return [l for l in listings if q in (l.get("area") or "").lower()]
    if cmd_type == "rent":
        return [l for l in listings if (l.get("price") or 0) <= int(arg)]
    if cmd_type == "size":
        return [l for l in listings if (float(l.get("floor_area") or 0)) >= float(arg)]
    if cmd_type == "plan":
        min_rank = _fp_rank(arg)
        if min_rank < 0:
            return []
        return [l for l in listings if _fp_rank(l.get("layout") or "") >= min_rank]
    if cmd_type == "top":
        return sorted(listings, key=lambda a: (-(a.get("match_score", 0)), a.get("distance_km", 999), a.get("price", 0)))[:5]
    return listings

def _send_tg_message(token, chat_id, text):
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception:
        pass

def handle_telegram_commands(listings):
    """Process pending Telegram bot commands (one-shot for CI)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    offset = 0
    if os.path.exists(TG_OFFSET_FILE):
        try:
            offset = int(open(TG_OFFSET_FILE).read().strip())
        except ValueError:
            pass

    try:
        r = http_requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 0, "allowed_updates": ["message"]},
            timeout=5,
        )
        data = r.json()
        if not data.get("ok"):
            return
        updates = data.get("result", [])
        if not updates:
            return

        print(f"Processing {len(updates)} Telegram command(s)...")
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = (msg.get("text") or "").strip()
            msg_chat_id = str(msg.get("chat", {}).get("id", ""))
            if msg_chat_id != str(chat_id):
                continue

            parsed = _parse_tg_command(text)
            if not parsed:
                continue

            cmd_type, arg = parsed
            print(f"  Command: \\{cmd_type} {arg}")

            if cmd_type == "help":
                _send_tg_message(token, chat_id,
                    "\U0001f4cc *JKK Radar Commands*\n\n"
                    "\\top \u2014 Show top 5 best matches\n"
                    "\\rent80000 \u2014 Listings under \u00a580,000\n"
                    "\\size40 \u2014 Listings \u2265 40m\u00b2\n"
                    "\\plan2DK \u2014 Listings \u2265 2DK\n"
                    "\\\u65b0\u5bbf\u533a \u2014 Listings in Shinjuku ward\n"
                    "\\help \u2014 Show this help"
                )
                continue

            results = _filter_for_command(listings, cmd_type, arg)
            total = len(results)
            shown = results[:TG_MAX_RESULTS]

            if cmd_type == "ward":
                label = f"Ward: {arg}"
            elif cmd_type == "rent":
                label = f"Rent \u2264 \u00a5{int(arg):,}"
            elif cmd_type == "size":
                label = f"Area \u2265 {float(arg):g} m\u00b2"
            elif cmd_type == "plan":
                label = f"Floor plan \u2265 {str(arg).upper()}"
            elif cmd_type == "top":
                label = "Top 5 Best Matches"
            else:
                label = cmd_type

            header = f"\U0001f50d <b>{label}</b> \u2014 {total} listing{'s' if total != 1 else ''} found"
            if total > TG_MAX_RESULTS:
                header += f"\n<i>Showing first {TG_MAX_RESULTS} of {total}</i>"
            if total == 0:
                header += "\n\nNo active listings match this query."
            _send_tg_message(token, chat_id, header)

            for a in shown:
                score = a.get("match_score", 0)
                stars = "\u2b50" * int(score)
                body = (
                    f"<b>{a['name']}</b>\n"
                    f"\U0001f4b0 \u00a5{a.get('price', 0):,}/mo\n"
                    f"\U0001f3e2 {a.get('area', '')} | {a.get('layout', '')} | {a.get('floor_area', '?')}m\u00b2\n"
                )
                if a.get("distance_km"):
                    body += f"\U0001f4cf {a['distance_km']}km from Shinjuku\n"
                if a.get("train_min"):
                    body += f"\U0001f687 ~{a['train_min']}min by train\n"
                body += f"{stars} ({score:.1f}/5 match)\n"
                if a.get("maps_url"):
                    body += f'<a href="{a["maps_url"]}">\U0001f517 Google Maps</a>'
                _send_tg_message(token, chat_id, body)

        with open(TG_OFFSET_FILE, "w") as f:
            f.write(str(offset))
        print(f"Telegram commands processed. Offset saved: {offset}")
    except Exception as e:
        print(f"Telegram command handling error: {e}")


# --- UR CHINTAI SCRAPER ---

def _ur_parse_yen(text):
    """Extract integer from yen string like '62,600円'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", str(text))
    return int(digits) if digits else None


def _ur_parse_area(floorspace):
    """Parse float from area string like '61&#13217;' → 61.0."""
    if not floorspace:
        return None
    import html as html_mod
    unescaped = html_mod.unescape(str(floorspace))
    m = re.search(r"[\d.]+", unescaped)
    return float(m.group()) if m else None


def _ur_parse_floor(floor_str):
    """Parse integer from floor string like '5階' → 5."""
    if not floor_str:
        return None
    m = re.search(r"\d+", str(floor_str))
    return int(m.group()) if m else None


def _ur_make_uid(building_id, room_id):
    """Generate stable UID for UR listing."""
    raw = f"{building_id}|{room_id}"
    return "ur_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def scrape_ur():
    """Scrape UR Chintai Tokyo listings via REST API. Returns list of apartment dicts."""
    print("Starting UR Chintai scrape...")
    session = http_requests.Session()
    session.headers.update(UR_HEADERS)

    all_buildings = []
    for area_code in UR_AREAS:
        time.sleep(0.5)
        try:
            resp = session.post(
                UR_API_BASE + "bukken/search/list_bukken/",
                data={"tdfk": UR_TDFK, "area": area_code},
                timeout=30,
            )
            resp.raise_for_status()
            buildings = resp.json()
            if isinstance(buildings, list):
                all_buildings.extend(buildings)
                print(f"  UR area {area_code}: {len(buildings)} buildings")
        except Exception as e:
            print(f"  UR area {area_code} failed: {e}")

    print(f"UR total buildings: {len(all_buildings)}")

    # Filter to buildings with vacancies
    vacant_buildings = [b for b in all_buildings if (b.get("roomCount") or 0) > 0]
    print(f"UR buildings with vacancies: {len(vacant_buildings)}")

    apartments = []
    for building in vacant_buildings:
        building_id = building.get("id", "")
        time.sleep(0.3)
        try:
            resp = session.post(
                UR_API_BASE + "room/list/",
                data={"tdfk": UR_TDFK, "id": building_id, "mode": "init"},
                timeout=30,
            )
            resp.raise_for_status()
            rooms = resp.json()
            if not isinstance(rooms, list):
                continue

            for room in rooms:
                room_id = room.get("id", "")
                rent_yen = _ur_parse_yen(room.get("rent"))
                area_sqm = _ur_parse_area(room.get("floorspace"))

                if rent_yen is None:
                    continue

                name_parts = [p for p in [building.get("name", ""), room.get("name", "")] if p]
                detail_path = room.get("urlDetail", "")
                detail_url = ("https://www.ur-net.go.jp" + detail_path) if detail_path else ""

                apt = {
                    "name": "\u3000".join(name_parts),
                    "area": building.get("skcs", ""),
                    "layout": room.get("type", ""),
                    "floor_area": str(area_sqm) if area_sqm else "?",
                    "price": rent_yen,
                    "price_display": f"{rent_yen:,}",
                    "uid": _ur_make_uid(building_id, room_id),
                    "source": "UR",
                    "detail_url": detail_url,
                    "address": building.get("skcs", ""),
                    "access": building.get("access", ""),
                    "floor": _ur_parse_floor(room.get("floor")),
                    "management_fee": _ur_parse_yen(room.get("commonfee")),
                }
                apartments.append(apt)
        except Exception as e:
            print(f"  UR building {building_id} rooms failed: {e}")

    print(f"UR total rooms scraped: {len(apartments)}")
    return apartments


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
    print("Starting JKK + UR Radar...")
    driver = setup_driver()
    geocache = load_json_file(GEOCACHE_FILE)
    seen_apartments = load_json_file(SEEN_FILE)

    try:
        # Scrape JKK
        apartments = scrape_jkk(driver)
        print(f"JKK apartments found: {len(apartments)}")

        # Scrape UR (no Selenium needed — REST API)
        driver.quit()
        driver = None
        ur_apartments = scrape_ur()
        print(f"UR apartments found: {len(ur_apartments)}")

        # Merge: tag JKK apartments with source
        for apt in apartments:
            apt.setdefault("source", "JKK")
        apartments.extend(ur_apartments)
        print(f"Total combined apartments: {len(apartments)}")

        if not apartments:
            print("No apartments found from either source.")
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

        # Calculate match scores for all apartments
        for a in apartments:
            a["match_score"] = calculate_match_score(
                a["price"], a["distance_km"], a.get("train_min"), a.get("floor_area")
            )

        # Sort affordable by best match score (highest first)
        affordable.sort(key=lambda a: (-a["match_score"], a["distance_km"], a["price"]))

        # Save ALL results for web dashboard (sorted by match score)
        all_sorted = sorted(apartments, key=lambda a: (-a["match_score"], a["distance_km"], a["price"]))
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
                    "match_score": a["match_score"],
                    "source": a.get("source", "JKK"),
                    "detail_url": a.get("detail_url", ""),
                }
                for a in all_sorted
            ],
        }
        save_json_file("results.json", results)
        print("Saved results.json for dashboard.")

        # Filter out already-seen apartments (only notify NEW ones)
        new_apartments = [a for a in affordable if a["uid"] not in seen_apartments]
        print(f"New affordable apartments: {len(new_apartments)}")

        # Detect removed listings (previously seen, no longer in current results)
        current_uids = {a["uid"] for a in apartments}
        removed_uids = [uid for uid in seen_apartments if uid not in current_uids]
        removed_apartments = []
        if removed_uids:
            # We don't store full apartment details for seen UIDs, so just count them
            print(f"Removed listings detected: {len(removed_uids)}")
            # Clean up seen list
            seen_apartments = [uid for uid in seen_apartments if uid in current_uids]

        if new_apartments:
            # Deduplicate by building name — keep the cheapest unit per building
            seen_buildings = set()
            unique_buildings = []
            for a in new_apartments:
                if a["name"] not in seen_buildings:
                    seen_buildings.add(a["name"])
                    unique_buildings.append(a)

            # Sort by best match score (highest first)
            unique_buildings.sort(key=lambda a: (-a["match_score"], a["distance_km"], a["price"]))

            # Only alert top 5
            top5 = unique_buildings[:5]
            send_telegram_alert(top5)
            send_telegram_summary(len(apartments), len(new_apartments))

            # Alert on removed listings
            if removed_uids:
                send_telegram_removed([{"name": uid, "price_display": "?", "area": "", "layout": ""} for uid in removed_uids[:5]])

            # Save notification history
            import datetime
            notif_file = "notifications.json"
            notif_history = load_json_file(notif_file) if os.path.exists(notif_file) else []
            notif_history.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "total_scanned": len(apartments),
                "new_count": len(new_apartments),
                "removed_count": len(removed_uids),
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
            if removed_uids:
                send_telegram_removed([{"name": uid, "price_display": "?", "area": "", "layout": ""} for uid in removed_uids[:5]])
                save_json_file(SEEN_FILE, seen_apartments)

        # Daily digest (send once per day — check if last digest was >20 hours ago)
        DIGEST_FILE = "last_digest.txt"
        send_digest = True
        if os.path.exists(DIGEST_FILE):
            try:
                import datetime
                from datetime import timezone, timedelta
                jst = timezone(timedelta(hours=9))
                last = datetime.datetime.fromisoformat(open(DIGEST_FILE).read().strip())
                if last.tzinfo is None:
                    last = last.replace(tzinfo=jst)
                if (datetime.datetime.now(jst) - last).total_seconds() < 20 * 3600:
                    send_digest = False
            except Exception:
                pass

        if send_digest:
            send_daily_digest(apartments, len(new_apartments), len(removed_uids))
            import datetime
            from datetime import timezone, timedelta
            jst = timezone(timedelta(hours=9))
            with open(DIGEST_FILE, "w") as f:
                f.write(datetime.datetime.now(jst).isoformat())

        # Handle Telegram bot commands
        handle_telegram_commands(apartments)

    except Exception as e:
        print(f"Critical error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
