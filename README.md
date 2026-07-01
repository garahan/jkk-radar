# JKK Radar

Automated monitor for [JKK Tokyo](https://jhomes.to-kousya.or.jp/) public housing apartments. Finds listings closest to **Apple Shinjuku** and cheapest, then sends alerts via **Telegram**.

## How It Works

1. Scrapes the JKK vacancy search page every 15 minutes (via GitHub Actions)
2. Extracts apartment name, address, and rent from results
3. Geocodes each address using OpenStreetMap/Nominatim and caches results
4. Calculates distance to Apple Shinjuku store (35.6938°N, 139.7034°E)
5. Filters: within **15 km** and under **¥150,000/month**
6. Sorts by distance first, then price
7. Sends Telegram alerts for new matches (up to 10 per scan)

## Configuration

Edit these constants in `main.py` to adjust filtering:

| Variable | Default | Description |
|---|---|---|
| `APPLE_SHINJUKU_LAT` | `35.69376` | Target latitude |
| `APPLE_SHINJUKU_LON` | `139.70343` | Target longitude |
| `MAX_DISTANCE_KM` | `15.0` | Max distance from target (km) |
| `MAX_RENT` | `150000` | Max monthly rent (yen) |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export TELEGRAM_BOT_TOKEN="your-bot-token-from-botfather"
export TELEGRAM_CHAT_ID="your-chat-id"
```

See [.env.example](.env.example) for reference.

#### Getting a Telegram Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the token it gives you

#### Getting your Chat ID

1. Message your bot in Telegram
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id": <number>}` in the response

### 3. Run locally

```bash
python main.py
```

## GitHub Actions (Automated)

The included workflow (`.github/workflows/scrape.yml`) runs every 15 minutes.

### Required Repository Secrets

Add these in **Settings > Secrets and variables > Actions**:

- `TELEGRAM_BOT_TOKEN` — Bot token from @BotFather
- `TELEGRAM_CHAT_ID` — Chat ID for alerts

### What gets committed

The workflow auto-commits two data files back to the repo:

- `seen_apartments.json` — tracks already-alerted listings to avoid duplicates
- `geocache.json` — cached geocoding results to reduce API calls

## Project Structure

```
jkk-radar/
├── main.py                  # Scraper + geocoding + Telegram alerts
├── requirements.txt         # Python dependencies
├── .env.example             # Example environment variables
├── .gitignore               # Git ignore rules
├── seen_apartments.json     # Auto-generated: seen listing tracker
├── geocache.json            # Auto-generated: address geocode cache
└── .github/
    └── workflows/
        └── scrape.yml       # GitHub Actions scheduled workflow
```

## Telegram Alert Format

```
🏠 JKK Apartment Near Apple Shinjuku!

📍 コーシャハイム新宿
💰 ¥85,000/month
📏 2.3 km from Apple Shinjuku
🔗 View Details
```

## License

MIT
