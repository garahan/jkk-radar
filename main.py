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
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-popup-blocking") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
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

def switch_to_new_window(driver):
    time.sleep(3) 
    handles = driver.window_handles
    print(f"Detected {len(handles)} windows.")
    if len(handles) > 1:
        driver.switch_to.window(handles[-1])
        print(f"Switched to popup: {driver.title}")
        return True
    return False

def main():
    print("Starting JKK Patient Observer...")
    driver = setup_driver()
    
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try: seen_apartments = json.load(f)
            except: seen_apartments = []
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        wait = WebDriverWait(driver, 20)

        # --- PHASE 1: REDIRECT & POPUP ---
        try:
            redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "こちら")
            redirect_link.click()
        except: pass
        
        switch_to_new_window(driver)

        # --- PHASE 2: WARD AREA ---
        print("Checking Ward Area...")
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']")))
            ward_checkbox = driver.find_element(By.XPATH, "//label[contains(.,'区部')]/preceding-sibling::input | //label[contains(.,'区部')]/../input")
            if not ward_checkbox.is_selected():
                driver.execute_script("arguments[0].click();", ward_checkbox)
                print("✅ Checked Ward Area.")
        except Exception as e:
            print(f"⚠️ Checkbox issue: {e}")

        # --- PHASE 3: SEARCH ---
        print("Clicking Search...")
        try:
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //input[contains(@value,'検索')] | //a[contains(text(),'検索')]")
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ Clicked Search.")
        except Exception as e:
            print(f"❌ Search Click Failed: {e}")

        # --- PHASE 4: WAIT FOR RESULTS (THE FIX) ---
        print("Waiting for results table...")
        try:
            # Wait for at least one row with a 'detail' link to appear
            # We wait up to 15 seconds for the table to refresh
            wait.until(EC.presence_of_element_located((By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")))
            print("✅ Results Table Loaded!")
        except:
            print("⚠️ Timeout waiting for results table. (Market might be empty or page slow)")

        # --- PHASE 5: SCRAPE ---
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
        print(f"Scanning {len(rows)} rows...")
        
        new_finds = 0
        current_scan_ids = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ")
                link = row.find_element(By.XPATH, ".//a[contains(@href, 'detail')]").get_attribute("href")
                
                # Price Parser
                raw_nums = re.findall(r'[0-9,]+', text)
                price_int = 999999
                for s in raw_nums:
                    try:
                        val = int(s.replace(",", ""))
                        if val > 10000: 
                            price_int = val
                            break
                    except: continue

                current_scan_ids.append(link)

                if link not in seen_apartments:
                    if price_int <= MAX_RENT:
                        print(f"MATCH! {text[:20]}... ({price_int})")
                        send_discord_alert("Apartment", f"{price_int} Yen", "Check Link", link)
                        new_finds += 1
            except: pass 

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
        # Capture source for debug if needed
        # print(driver.page_source[:500])
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
