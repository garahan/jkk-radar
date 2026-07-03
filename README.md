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
│     - From each apartment to Shinjuku Store              │
│       (35.69376°N, 139.70343°E)                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  6. FILTER & SORT                                        │
│     - Keep only: distance ≤ 15 km AND rent ≤ ¥150,000   │
│     - Sort by: distance (ascending), then price          │
│     - Exclude previously seen apartments                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  7. ALERT VIA TELEGRAM                                   │
│     - Send up to 10 apartment alerts                     │
│     - Each alert includes: name, rent, distance, link    │
│     - Send summary message with scan stats               │
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

All configuration constants are at the top of `main.py`:

| Variable | Default | Description |
|---|---|---|
| `JKK_URL` | `https://jhomes.to-kousya.or.jp/...` | JKK vacancy search page URL |
| `SHINJUKU_LAT` | `35.69376` | Target latitude (Shinjuku) |
| `SHINJUKU_LON` | `139.70343` | Target longitude (Shinjuku) |
| `SEEN_FILE` | `seen_apartments.json` | Path to seen apartments tracker |
| `GEOCACHE_FILE` | `geocache.json` | Path to geocoding cache |

### Changing the target location

To monitor apartments near a different location, update the latitude and longitude:

```python
# Example: near Tokyo Station
SHINJUKU_LAT = 35.6812
SHINJUKU_LON = 139.7671
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
pip install -r requirements.txt
```

**Dependencies:**
| Package | Purpose |
|---|---|
| `selenium` | Browser automation for scraping JKK |
| `webdriver-manager` | Auto-downloads matching ChromeDriver |
| `requests` | HTTP client for Telegram Bot API |
| `geopy` | Geocoding addresses via Nominatim |
| `beautifulsoup4` | HTML parsing (utility) |

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
```

Then load them:

```bash
export $(cat .env | xargs)
```

### 6. Run

```bash
python main.py
```

---

## GitHub Actions (Automated Monitoring)

The included workflow runs the scraper automatically every 15 minutes using GitHub Actions.

### Setting up automated monitoring

1. Push this repo to GitHub
2. Go to **Settings > Secrets and variables > Actions**
3. Add two repository secrets:
   - `TELEGRAM_BOT_TOKEN` — your bot token
   - `TELEGRAM_CHAT_ID` — your chat ID
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
├── main.py                      # Main scraper script
│   ├── setup_driver()           #   Configure headless Chrome
│   ├── scrape_jkk(driver)       #   Navigate JKK site and extract listings
│   ├── geocode_address()        #   Resolve address → coordinates
│   ├── haversine_km()           #   Calculate distance between two points
│   ├── send_telegram_alert()    #   Send per-apartment Telegram messages
│   ├── send_telegram_summary()  #   Send scan summary message
│   └── main()                   #   Orchestrate: scrape → geocode → filter → alert
│
├── requirements.txt             # Python package dependencies
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

Each matching apartment produces a message like:

```
🏠 JKK Apartment Alert!

📍 コーシャハイム新宿
💰 ¥85,000/month
📏 2.3 km from Shinjuku
🔗 View Details
```

After all individual alerts, a summary is sent:

```
🔍 JKK Radar Scan Complete
Scanned 47 listings • 3 apartments found
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| No results found | The JKK site may be under maintenance (shows "おわび" page). Wait and retry. |
| Geocoding returns `inf` distance | The address couldn't be resolved. Check `geocache.json` for `null` entries. |
| Telegram alerts not sending | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly. Test with: `curl https://api.telegram.org/bot<TOKEN>/getMe` |
| GitHub Actions not running | Check that repository secrets are configured and the workflow is enabled. |
| Chrome/driver errors | Ensure Chrome and ChromeDriver versions are compatible. The workflow handles this automatically. |

---

## License

MIT License. See [LICENSE](LICENSE) for details.
