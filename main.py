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
    print("Starting JKK Force Entry Bot...")
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
        wait = WebDriverWait(driver, 10)

        # --- PHASE 1: FORCE THE REDIRECT ---
        print("Checking for redirect trap...")
        try:
            # 1. Try to find the form immediately
            wait.until(EC.presence_of_element_located((By.XPATH, "//label[contains(.,'区部')]")))
            print("✅ Form loaded immediately.")
        except:
            print("⚠️ Form not found yet. Looking for 'Click Here' link...")
            try:
                # 2. If not found, click the "If not displayed, click here" link
                # "こちら" = Here
                redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "こちら")
                redirect_link.click()
                print("✅ Clicked manual redirect link!")
                time.sleep(3) # Wait for load
            except:
                print("❌ Could not find redirect link. Dumping Page Title:")
                print(driver.title)

        # --- PHASE 2: SELECT "WARD AREA" (ROBUST) ---
        print("Targeting Ward Area...")
        try:
            # Use specific label targeting, not just [1]
            # Finds label containing "区部" then finds the input associated with it
            ward_checkbox = driver.find_element(By.XPATH, "//label[contains(.,'区部')]/preceding-sibling::input | //label[contains(.,'区部')]/../input | //input[contains(@title,'区部')]")
            driver.execute_script("arguments[0].checked = true;", ward_checkbox) # Force check
            print("✅ Checked 'Ward Area' box (Force JS).")
        except:
            # Fallback to the first checkbox if specific fail
            try:
                cb = driver.find_element(By.XPATH, "//input[@type='checkbox']")
                driver.execute_script("arguments[0].click();", cb)
                print("⚠️ Checked first checkbox as fallback.")
            except Exception as e:
                print(f"❌ Checkbox failed: {e}")

        # --- PHASE 3: CLICK SEARCH ---
        print("Hunting for Search button...")
        try:
            # Robust search for button
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //input[@alt='検索'] | //a[contains(text(),'検索')]")
            
            # Scroll into view just in case
            driver.execute_script("arguments[0].scrollIntoView(true);", search_btn)
            time.sleep(1)
            
            # Click
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ CLICKED Search Button.")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Search Button Failed: {e}")

        # --- PHASE 4: SCRAPE ---
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
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
                        send_discord_alert("Apartment", f"{price_int} Yen", "Check Link", link)
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
