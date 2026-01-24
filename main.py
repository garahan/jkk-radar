import os
import time
import json
import re
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

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def send_discord_alert(title, price, size, link):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url: return
    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(title=f"💎 Found: {title}", description=f"💰 {price}\n📐 {size}", color='57F287')
    embed.set_url(link)
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("Starting JKK Patient Bot...")
    driver = setup_driver()
    
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try: seen_apartments = json.load(f)
            except: seen_apartments = []
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        print(f"Landed on: {driver.title}")
        
        # --- THE FIX: WAIT FOR THE FORM ---
        wait = WebDriverWait(driver, 25) # Wait up to 25 seconds for redirect
        
        print("Waiting for redirect to finish...")
        try:
            # Wait until the word "地域" (Region) appears. This means the Form has loaded.
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '地域')]")))
            print("✅ Redirect finished! Form loaded.")
        except:
            print("⚠️ Timeout waiting for form. Dumping text:")
            print(driver.find_element(By.TAG_NAME, "body").text[:500])

        # --- STEP 1: CLICK "WARD AREA" (区部) ---
        try:
            # JavaScript Click is most reliable for these checkboxes
            print("Clicking 'Ward Area'...")
            # Find the input that has '区部' in its parent or title, or just the first checkbox in the table
            checkbox = driver.find_element(By.XPATH, "//input[@type='checkbox'][1]") 
            driver.execute_script("arguments[0].click();", checkbox)
            print("✅ Clicked first checkbox (Usually Ward Area).")
        except Exception as e:
            print(f"⚠️ Checkbox warning: {e}")

        # --- STEP 2: CLICK SEARCH (検索する) ---
        print("Hunting for Search button...")
        try:
            # Look for image alt='検索する' or text
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //a[contains(text(),'検索')] | //input[@value='検索する']")
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ CLICKED Search Button.")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Search Button Failed: {e}")

        # --- STEP 3: SCRAPE ---
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(text(),'詳細') or contains(@alt,'詳細')]]")
        print(f"Found {len(rows)} listings on the table.")
        
        new_finds = 0
        current_scan_ids = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ")
                link = row.find_element(By.XPATH, ".//a[contains(@href, 'detail')]").get_attribute("href")
                
                # Parse Price
                row_numbers = [int(s.replace(',', '')) for s in re.findall(r'\b\d{1,3}(?:,\d{3})+\b', text)]
                price_int = row_numbers[0] if row_numbers else 999999

                current_scan_ids.append(link)

                if link not in seen_apartments:
                    if price_int <= MAX_RENT:
                        print(f"MATCH! {text[:20]}... ({price_int})")
                        title = text.split(" ")[0]
                        send_discord_alert(title, f"{price_int} Yen", "Check Link", link)
                        new_finds += 1
            except:
                pass 

        if new_finds > 0:
            seen_apartments.extend(current_scan_ids)
            seen_apartments = list(set(seen_apartments))
            with open(SEEN_FILE, 'w') as f:
                json.dump(seen_apartments, f)
            print(f"Sent {new_finds} alerts.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
