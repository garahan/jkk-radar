# JKK Radar

An automated apartment hunting bot for [JKK Tokyo (Tokyo Metropolitan Housing Supply Corporation)](https://jhomes.to-kousya.or.jp/). It continuously monitors public housing vacancies and alerts you via Telegram when affordable apartments appear near a target location in Tokyo.

---

## Purpose

Finding affordable public housing in central Tokyo is extremely competitive. JKK (Tokyo Metropolitan Housing Supply Corporation) manages thousands of apartments across Tokyo's 23 wards, and vacancies appear and disappear quickly.

JKK Radar automates this process by:
- Scanning the official JKK vacancy listing page every 15 minutes
- Filtering results by distance to your target location and monthly rent
- Sending instant Telegram notifications so you can apply before anyone else

The default target is **Shinjuku station** (3-chome Shinjuku, Shinjuku City), but you can change the target coordinates to any location.

---

## How It Works

### Step-by-step flow

```
┌─────────────────────────────────────────────────────────┐
│                   GitHub Actions Cron                    │
│                  (every 15 minutes)                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  1. LAUNCH BROWSER                                       │
│     Headless Chrome via Selenium                         │
│     Navigate to JKK vacancy search page                  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  2. NAVIGATE THE SEARCH FORM                             │
│     - Click redirect link ("こちら") to open popup       │
│     - Switch to popup window                             │
│     - Check "区部" (Ward Area) checkbox                  │
│     - Click "検索" (Search) button                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  3. PARSE RESULTS                                        │
│     For each apartment listing:                          │
│     - Extract apartment name from detail link text       │
│     - Extract monthly rent (numbers > ¥10,000)           │
│     - Extract address (cells containing 区/市/町/丁目)    │
│     - Extract detail page URL                            │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  4. GEOCODE ADDRESSES                                    │
│     - Look up each address in local cache (geocache.json)│
│     - If not cached: query OpenStreetMap Nominatim API   │
│     - Try multiple query formats:                        │
│       1. Raw address                                     │
│       2. "{address}, Tokyo, Japan"                       │
│       3. "{address}, 東京都"                              │
│     - Cache results to avoid repeated API calls          │
│     - Rate limited to 1 request per 1.1 seconds          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  5. CALCULATE DISTANCE                                   │
│     - Haversine formula (great-circle distance)          │
│     - From each apartment to the configured target       │
│       (default: 35.69376°N, 139.70343°E, Shinjuku)       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  6. FILTER & SORT                                        │
│     - Keep only: rent ≤ MAX_RENT, distance ≤ MAX_DIST,  │
│       and match score ≥ MIN_MATCH_SCORE                 │
│     - Sort by: match score (descending), then distance   │
│     - Exclude previously seen apartments                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  7. ALERT VIA TELEGRAM                                   │
│     - Send a single batched message with up to 5 best    │
│       matching apartments                                │
│     - Each alert includes: name, rent, distance, score,  │
│       commute time, and map/detail links                 │
│     - Save seen apartments to avoid duplicate alerts     │
└─────────────────────────────────────────────────────────┘
```

### Key technical details

- **Browser automation**: Uses Selenium with headless Chrome. The JKK site uses JavaScript popups and form submissions that require a real browser engine.
- **Geocoding**: Uses OpenStreetMap's Nominatim API (free, no API key needed). Results are cached in `geocache.json` so each address is only looked up once.
- **Distance calculation**: Haversine formula computes the straight-line distance in kilometers between two geographic coordinates.
- **Duplicate prevention**: `seen_apartments.json` stores URLs of previously alerted apartments. Only new listings trigger alerts.

---

## Configuration

All settings are read from environment variables. Copy `.env.example` to `.env` and edit the values:

| Variable | Default | Description |
|---|---|---|
| `TARGET_LAT` | `35.69376` | Target latitude (default: Shinjuku) |
| `TARGET_LON` | `139.70343` | Target longitude (default: Shinjuku) |
| `MAX_RENT` | `80000` | Maximum monthly rent in JPY |
| `MAX_DISTANCE_KM` | `20` | Maximum straight-line distance from target |
| `MIN_MATCH_SCORE` | `2.0` | Minimum 1-5 star match score required to alert |
| `MAX_TELEGRAM_RESULTS` | `5` | Maximum apartments in one Telegram message |
| `SEND_DAILY_DIGEST` | `False` | Set `1` to send a daily digest |
| `ALERT_REMOVED` | `False` | Set `1` to alert when listings disappear |
| `GOOGLE_MAPS_API_KEY` | — | Optional API key for accurate transit times |
| `SEEN_FILE` | `seen_apartments.json` | Path to seen apartments tracker |
| `GEOCACHE_FILE` | `geocache.json` | Path to geocoding cache |

### Changing the target location

To monitor apartments near a different location, update `TARGET_LAT` and `TARGET_LON` in your `.env`:

```bash
# Example: near Tokyo Station
TARGET_LAT=35.6812
TARGET_LON=139.7671
```

---

## Setup

### Prerequisites

- Python 3.9+
- Google Chrome (or Chromium)
- A Telegram bot

### 1. Clone the repository

```bash
git clone https://github.com/garahan/jkk-radar.git
cd jkk-radar
```

### 2. Install dependencies

```bash
pip install selenium selenium-stealth requests geopy
```

**Dependencies:**
| Package | Purpose |
|---|---|
| `selenium` | Browser automation for scraping JKK |
| `selenium-stealth` | Helps avoid bot detection |
| `requests` | HTTP client for Telegram Bot API and UR Chintai API |
| `geopy` | Geocoding addresses via Nominatim |

### 3. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow the prompts to name your bot
4. Copy the **bot token** (looks like `123456789:ABCdefGhIjKlmNoPqRsTuVwXyZ`)

### 4. Get your Telegram Chat ID

1. Send any message to your new bot in Telegram
2. Open this URL in a browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Find `"chat":{"id": <NUMBER>}` in the JSON response — that number is your chat ID

### 5. Set environment variables

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIjKlmNoPqRsTuVwXyZ
TELEGRAM_CHAT_ID=987654321

# Optional: tighten or loosen the filters
MAX_RENT=80000
MAX_DISTANCE_KM=20
MIN_MATCH_SCORE=2.0
MAX_TELEGRAM_RESULTS=5
```

Then load them:

```bash
export $(cat .env | xargs)
```

### 6. Run

```bash
python scraper/scraper.py
```

---

## GitHub Actions (Automated Monitoring)

The included workflow runs the scraper automatically every 15 minutes using GitHub Actions.

### Setting up automated monitoring

1. Push this repo to GitHub
2. Go to **Settings > Secrets and variables > Actions**
3. Add repository secrets:
   - `TELEGRAM_BOT_TOKEN` — your bot token
   - `TELEGRAM_CHAT_ID` — your chat ID
   - `GOOGLE_MAPS_API_KEY` — optional, for accurate transit times

Optional: add the same preference variables as in `.env` (e.g., `MAX_RENT`, `MAX_DISTANCE_KM`, `MIN_MATCH_SCORE`) as repository variables or secrets. If omitted, the defaults in `.env.example` are used.
4. The workflow starts automatically on the next 15-minute interval

### Workflow details

**File:** `.github/workflows/scrape.yml`

| Feature | Detail |
|---|---|
| Schedule | Every 15 minutes (`*/15 * * * *`) |
| Runner | `ubuntu-latest` |
| Python | 3.11 |
| Browser | Chrome (installed via `browser-actions/setup-chrome`) |
| Auto-commit | `seen_apartments.json` and `geocache.json` are committed back to the repo |
| Debug | Screenshots uploaded as artifacts on failure |
| Manual trigger | Supported via `workflow_dispatch` |

### Data files committed by the workflow

| File | Purpose |
|---|---|
| `seen_apartments.json` | Tracks which apartment URLs have already been alerted, preventing duplicate notifications across runs |
| `geocache.json` | Caches geocoded addresses (address → lat/lon mapping) so the Nominatim API is only called once per unique address |

---

## Project Structure

```
jkk-radar/
│
├── scraper/scraper.py                      # Main scraper script
│   ├── setup_driver()           #   Configure headless Chrome
│   ├── scrape_jkk(driver)       #   Navigate JKK site and extract listings
│   ├── scrape_ur()              #   Fetch UR Chintai listings via API
│   ├── geocode_address()        #   Resolve address → coordinates
│   ├── haversine_km()           #   Calculate distance between two points
│   ├── send_telegram_alert()    #   Send one batched Telegram message
│   └── main()                   #   Orchestrate: scrape → geocode → filter → alert
│
├── .env.example                 # Template for required environment variables
├── .gitignore                   # Git ignore rules
│
├── seen_apartments.json         # [auto-generated] Seen apartment URL tracker
├── geocache.json                # [auto-generated] Address geocoding cache
│
└── .github/
    └── workflows/
        └── scrape.yml           # GitHub Actions: 15-min scheduled scraper
```

---

## Telegram Alert Format

The scraper sends a single batched message with up to `MAX_TELEGRAM_RESULTS` best matches:

```
🏠 JKK Radar — 3 best matches

1. コーシャハイム新宿 [JKK]
⭐⭐⭐ (3.0/5)
💰 ¥85,000/month
🏢 新宿区 | 2DK
📏 2.3 km from target
🚇 ~12 min by train
📐 50.0 m²
🔗 Google Maps

---

2. 神田小川町ハイツ [UR]
...
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| No results found | The JKK site may be under maintenance (shows "おわび" page). Wait and retry. |
| Geocoding returns `inf` distance | The address couldn't be resolved. Check `geocache.json` for `null` entries. If a building is geocoded to the wrong city, it will be re-tried on the next run. |
| Telegram alerts not sending | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly. Test with: `curl https://api.telegram.org/bot<TOKEN>/getMe` |
| GitHub Actions not running | Check that repository secrets are configured and the workflow is enabled. |
| Chrome/driver errors | Ensure Chrome and ChromeDriver versions are compatible. The workflow handles this automatically. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
