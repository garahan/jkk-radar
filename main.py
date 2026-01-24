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
    # Allow popups in headless mode
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
    """Checks for a popup window and switches to it"""
    time.sleep(3) # Give popup time to fire
    handles = driver.window_handles
    print(f"Detected {len(handles)} browser tabs/windows.")
    
    if len(handles) > 1:
        print("🔀 Switching to the new popup window...")
        driver.switch_to.window(handles[-1]) # Switch to the last opened window
        print(f"Now on page: {driver.title}")
        return True
    return False

def main():
    print("Starting JKK Popup Handler Bot...")
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
        wait = WebDriverWait(driver, 15)

        # --- PHASE 1: HANDLE REDIRECT & POPUP ---
        # 1. Try to force the click immediately if needed
        try:
            redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "こちら")
            redirect_link.click()
            print("Clicked manual redirect link.")
        except:
            print("No manual link found, waiting for auto-redirect...")

        # 2. CRITICAL: Switch to the new window if it opened
        switch_to_new_window(driver)

        # --- PHASE 2: SELECT "WARD AREA" (区部) ---
        print("Hunting for Ward Area...")
        try:
            # Wait for the form in the NEW window
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']")))
            
            # Find the specific label for Wards (区部)
            ward_checkbox = driver.find_element(By.XPATH, "//label[contains(.,'区部')]/preceding-sibling::input | //label[contains(.,'区部')]/../input | //input[contains(@title,'区部')]")
            
            if not ward_checkbox.is_selected():
                driver.execute_script("arguments[0].click();", ward_checkbox)
                print("✅ Checked 'Ward Area' box.")
            else:
                print("⚠️ Ward Area already checked.")
        except Exception as e:
            print(f"⚠️ Checkbox issue (Might fallback to first box): {e}")
            # Fallback: Click the very first checkbox we find
            try:
                cb = driver.find_element(By.XPATH, "//input[@type='checkbox']")
                driver.execute_script("arguments[0].click();", cb)
            except: pass

        # --- PHASE 3: CLICK SEARCH ---
        print("Hunting for Search button...")
        try:
            # Look for Search button (Image or Text)
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //input[contains(@value,'検索')] | //a[contains(text(),'検索')]")
            
            driver.execute_script("arguments[0].scrollIntoView(true);", search_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ CLICKED Search Button.")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Search Button Failed: {e}")

        # --- PHASE 4: SCRAPE ---
        # Look for rows that have a detail link
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
        print(f"Found {len(rows)} listings.")
        
        new_finds = 0
        current_scan_ids = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ")
                link = row.find_element(By.XPATH, ".//a[contains(@href, 'detail')]").get_attribute("href")
                
                # Robust Price Parser
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
                        send_discord_alert("New Apartment", f"{price_int} Yen", "Check Link", link)
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
        # DEBUG: If it fails, print current URL
        print(f"Current URL: {driver.current_url}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
