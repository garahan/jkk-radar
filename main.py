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
    chrome_options.add_argument("--headless=new") # New stable headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    # Linux User Agent to match GitHub Actions
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def save_debug_artifacts(driver, name):
    """Saves a screenshot and HTML to inspect later"""
    try:
        if not os.path.exists("debug_artifacts"):
            os.makedirs("debug_artifacts")
        
        # Save Screenshot
        driver.save_screenshot(f"debug_artifacts/{name}.png")
        
        # Save HTML
        with open(f"debug_artifacts/{name}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
            
        print(f"📸 Debug Artifacts Saved: debug_artifacts/{name}.png")
    except Exception as e:
        print(f"Could not save debug artifacts: {e}")

def send_discord_alert(title, price, size, link):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url: return
    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(title=f"💎 Found: {title}", description=f"💰 {price}\n📐 {size}", color='57F287')
    embed.set_url(link)
    webhook.add_embed(embed)
    webhook.execute()

def main():
    print("Starting Black Box Recorder Bot...")
    driver = setup_driver()
    
    # Load history
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try: seen_apartments = json.load(f)
            except: seen_apartments = []
    else:
        seen_apartments = []

    try:
        driver.get(JKK_URL)
        print(f"Landed on: {driver.title}")
        save_debug_artifacts(driver, "01_landed")
        
        wait = WebDriverWait(driver, 15)

        # --- PHASE 1: HANDLE REDIRECT ---
        # The site often shows "Please wait...". We force click "Here" if it stays too long.
        try:
            print("Checking for redirect trap...")
            # Look for the "Click Here" link (こちら)
            try:
                redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "こちら")
                print("Found redirect link. Clicking it...")
                redirect_link.click()
                time.sleep(3)
                save_debug_artifacts(driver, "02_after_redirect_click")
            except:
                print("No redirect link found. Hoping we are on the form...")

            # Wait for Ward Checkbox to verify we are on the form
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']")))
            print("✅ Form appears loaded.")
            save_debug_artifacts(driver, "03_form_loaded")
            
        except Exception as e:
            print(f"⚠️ Navigation Error. Saving Screenshot.")
            save_debug_artifacts(driver, "ERROR_navigation")
            raise e

        # --- PHASE 2: CLICK 'WARD AREA' (区部) ---
        try:
            print("Clicking Ward Area...")
            # Find any checkbox that looks like the first option
            checkbox = driver.find_element(By.XPATH, "//input[@type='checkbox']")
            driver.execute_script("arguments[0].click();", checkbox)
            print("✅ Clicked Checkbox.")
        except Exception as e:
            print(f"❌ Checkbox failed: {e}")
            save_debug_artifacts(driver, "ERROR_checkbox")

        # --- PHASE 3: CLICK SEARCH ---
        try:
            print("Clicking Search...")
            # Find anything that looks like a search button
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //a[contains(text(),'検索')] | //input[contains(@value,'検索')]")
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ Clicked Search.")
            time.sleep(5)
            save_debug_artifacts(driver, "04_results_page")
        except Exception as e:
            print(f"❌ Search Button failed: {e}")
            save_debug_artifacts(driver, "ERROR_search_btn")

        # --- PHASE 4: SCRAPE ---
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
                        if val > 10000: # Filter out small numbers like floor counts
                            price_int = val
                            break
                    except: continue

                current_scan_ids.append(link)

                if link not in seen_apartments:
                    if price_int <= MAX_RENT:
                        print(f"MATCH! {text[:20]}... ({price_int})")
                        send_discord_alert("Apartment", f"{price_int} Yen", "Check Link", link)
                        new_finds += 1
            except:
                pass 

        # Save
        if new_finds > 0:
            seen_apartments.extend(current_scan_ids)
            seen_apartments = list(set(seen_apartments))
            with open(SEEN_FILE, 'w') as f:
                json.dump(seen_apartments, f)
            print(f"Sent {new_finds} alerts.")
        else:
            print("No new cheap listings found.")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        save_debug_artifacts(driver, "FATAL_CRASH")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
