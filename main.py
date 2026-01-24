import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from discord_webhook import DiscordWebhook, DiscordEmbed

# --- CONFIGURATION ---
# The direct search URL for JKK (Often changes, so we check the main search page)
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") # Run in background
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def send_discord_alert(title, url, price, size):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url:
        print("No Discord Webhook found!")
        return

    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(title=f"🏠 New JKK Apartment: {title}", description=f"Price: {price}\nSize: {size}", color='03b2f8')
    embed.set_url(url)
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("Starting Scan...")
    driver = setup_driver()

    # Load known apartments
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            seen_apartments = json.load(f)
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        time.sleep(5) # Wait for page to load

        # --- CUSTOM LOGIC FOR JKK ---
        # Note: JKK is tricky. This scraper looks for general "List Items"
        # If JKK changes their site, this specific part needs updating.

        # This is a generic "Find Links" approach to avoid breaking easily
        links = driver.find_elements(By.TAG_NAME, "a")

        current_scan_ids = []
        new_finds = 0

        for link in links:
            text = link.text
            href = link.get_attribute("href")

            # Simple Filter: Look for text that looks like a JKK listing
            # (You can adjust 'yen' or 'm2' based on what you see on the site)
            if href and "detail" in href and "yen" in text.lower(): 

                unique_id = href # Use URL as ID
                current_scan_ids.append(unique_id)

                if unique_id not in seen_apartments:
                    print(f"New Find: {text}")
                    send_discord_alert("New Listing Found", href, text, "Check Link")
                    new_finds += 1

        # Save the new list so we don't alert again
        if new_finds > 0:
            # Append new finds to our memory
            seen_apartments.extend(current_scan_ids)
            # Keep list unique
            seen_apartments = list(set(seen_apartments))
            with open(SEEN_FILE, 'w') as f:
                json.dump(seen_apartments, f)

        print(f"Scan complete. Found {new_finds} new apartments.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
