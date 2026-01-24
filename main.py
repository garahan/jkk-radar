import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from discord_webhook import DiscordWebhook, DiscordEmbed

# --- CONFIGURATION ---
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Force Desktop View (Important for JKK Table Layout)
    chrome_options.add_argument("--window-size=1920,1080")
    # Fake User Agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def send_discord_alert(title, price, size, link):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url:
        return
    
    webhook = DiscordWebhook(url=webhook_url)
    # Color: Green for cheap, Red for expensive
    color = '57F287' if "110,000" not in price else 'ED4245'
    
    embed = DiscordEmbed(title=f"🏠 New Find: {title}", description=f"💰 Rent: {price}\n📐 Size: {size}", color=color)
    embed.set_url(link)
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("Starting JKK Navigator...")
    driver = setup_driver()
    
    # Load history
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try:
                seen_apartments = json.load(f)
            except:
                seen_apartments = []
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        print(f"Landed on: {driver.title}")
        wait = WebDriverWait(driver, 15)

        # --- STEP 1: Click "Search First-Come Properties" (Screenshot 5) ---
        try:
            print("Looking for 'First-Come' button...")
            # Target the button by its Japanese text "先着順"
            first_come_btn = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "先着順")))
            first_come_btn.click()
            print("Clicked 'First-Come' button.")
        except Exception as e:
            print(f"Navigation Warning: Could not find first menu button. We might already be on the search page. Error: {e}")

        # --- STEP 2: Click "Search" (To see the list) ---
        # Usually, there is a conditions page. We just want to click "Search" to see everything.
        try:
            print("Looking for 'Search' (検索) button...")
            # Look for an image button with alt="検索" or text
            search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//img[@alt='検索'] | //input[@value='検索'] | //a[contains(text(),'検索')]")))
            search_btn.click()
            print("Clicked Search. Waiting for results...")
            time.sleep(5) # Give the table time to load
        except Exception as e:
            print(f"Search Button Warning: {e}")

        # --- STEP 3: Scrape the Table (Screenshot 6) ---
        print("Scanning results table...")
        
        # This finds all rows in the results table
        # We look for the 'Detail' button (詳細) because that confirms it's a listing row
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(text(),'詳細') or contains(@alt,'詳細')]]")
        
        print(f"Found {len(rows)} apartments.")
        
        new_finds = 0
        current_scan_ids = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ")
                
                # Get the Link
                link_elem = row.find_element(By.XPATH, ".//a[contains(@href, 'detail')]")
                link = link_elem.get_attribute("href")
                
                # Basic Parsing (splitting the row text)
                # JKK Table: [Name] [Area] [Type] [Layout] [Size] [Rent] ...
                # We just grab the whole text for the alert to be safe
                
                # Create a unique ID from the link
                unique_id = link 
                current_scan_ids.append(unique_id)

                if unique_id not in seen_apartments:
                    print(f"New Found: {text[:30]}...")
                    
                    # Extract roughly:
                    title = text.split(" ")[0] # First word is usually building name
                    
                    send_discord_alert(title, "Check Link", "Check Link", link)
                    new_finds += 1
                    
            except Exception as row_e:
                print(f"Skipped a row: {row_e}")

        # --- SAVE ---
        if new_finds > 0:
            seen_apartments.extend(current_scan_ids)
            seen_apartments = list(set(seen_apartments))
            with open(SEEN_FILE, 'w') as f:
                json.dump(seen_apartments, f)
            print(f"Successfully alerted {new_finds} new places.")
        else:
            print("No new unique listings found.")

    except Exception as e:
        print(f"Critical Error: {e}")
        # Debug: Print page source if it fails hard
        print("PAGE DUMP:", driver.page_source[:500])
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
