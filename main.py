import os
import time
import json
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
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
    print("Starting JKK Smart Filler...")
    driver = setup_driver()
    
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try: seen_apartments = json.load(f)
            except: seen_apartments = []
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        wait = WebDriverWait(driver, 10)
        print(f"Landed on: {driver.title}")
        time.sleep(2)

        # --- STEP 1: CHECK THE "WARDS" (区部) BOX ---
        # If we don't check this, we get 0 results.
        try:
            print("Looking for 'Ward Area' (区部) checkbox...")
            # Try to find the label or input containing '区部'
            ward_checkbox = driver.find_element(By.XPATH, "//label[contains(text(),'区部')] | //input[@type='checkbox' and contains(@title,'区部')]")
            
            # Scroll to it and click
            ActionChains(driver).move_to_element(ward_checkbox).click().perform()
            print("✅ Checked 'Ward Area' box.")
        except Exception as e:
            print(f"⚠️ Could not check Ward box (Might already be checked or different layout): {e}")

        # --- STEP 2: CLICK SEARCH (検索する) ---
        print("Hunting for Search button...")
        try:
            # Updated selectors based on your text "[検索する]"
            search_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'検索する')] | //img[@alt='検索する'] | //input[@value='検索する'] | //img[@alt='検索']")))
            search_btn.click()
            print("✅ CLICKED Search Button.")
        except:
             # Backup: JavaScript Click if standard click fails
            try:
                btn = driver.find_element(By.XPATH, "//a[contains(text(),'検索')]")
                driver.execute_script("arguments[0].click();", btn)
                print("✅ Force-Clicked button via JS.")
            except:
                print("❌ Could not find Search button.")

        time.sleep(5) # Wait for results

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
        else:
            print("No new cheap listings found.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
