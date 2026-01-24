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
# 「空き家検索（条件指定）」の初期ページ
JKK_URL = "https://jhomes.to-kousya.or.jp/search/jkknet/service/akiyaJyoukenStartInit"
SEEN_FILE = "seen_apartments.json"
MAX_RENT = 110000 

def setup_driver():
    chrome_options = Options()
    # ポップアップを許可する設定（重要）
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-popup-blocking") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # プリファレンスでポップアップを許可
    prefs = {"profile.default_content_setting_values.popups": 1}
    chrome_options.add_experimental_option("prefs", prefs)
    
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
    print("Starting JKK Final Fix Bot...")
    driver = setup_driver()
    
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            try: seen_apartments = json.load(f)
            except: seen_apartments = []
    else:
        seen_apartments = []

    try:
        # 1. サイトにアクセス
        driver.get(JKK_URL)
        print("Landed on redirection page.")
        wait = WebDriverWait(driver, 20)

        # 2. 「こちら」をクリックしてポップアップを強制起動
        try:
            # "こちら" というリンクを探してクリック
            redirect_link = driver.find_element(By.PARTIAL_LINK_TEXT, "こちら")
            redirect_link.click()
            print("Clicked 'Here' link to force popup.")
        except:
            print("Link not found, waiting for auto-popup...")

        time.sleep(5) # ウィンドウが開くのを待つ

        # 3. 新しいウィンドウ（ポップアップ）に乗り移る ★最重要★
        all_windows = driver.window_handles
        print(f"Detected {len(all_windows)} windows.")
        
        if len(all_windows) > 1:
            # 最後のウィンドウ（新しく開いた方）にスイッチ
            driver.switch_to.window(all_windows[-1])
            print(f"Switched to new window: {driver.title}")
        else:
            print("⚠️ No new window found. Continuing on current page...")

        # 4. 「区部」にチェックを入れる
        try:
            # フォームが表示されるまで待つ
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']")))
            print("Form loaded. Checking 'Ward Area'...")
            
            # 「区部」という文字の近くにあるチェックボックスを探す
            ward_checkbox = driver.find_element(By.XPATH, "//label[contains(.,'区部')]/preceding-sibling::input | //label[contains(.,'区部')]/../input")
            
            if not ward_checkbox.is_selected():
                driver.execute_script("arguments[0].click();", ward_checkbox)
                print("✅ Checked 'Ward Area'.")
        except Exception as e:
            print(f"⚠️ Checkbox error (Search might fail): {e}")

        # 5. 「検索する」ボタンを押す
        try:
            print("Clicking Search...")
            # 画像ボタン、またはテキストリンクの「検索」を探す
            search_btn = driver.find_element(By.XPATH, "//img[contains(@alt,'検索')] | //a[contains(text(),'検索')] | //input[contains(@value,'検索')]")
            driver.execute_script("arguments[0].click();", search_btn)
            print("✅ Clicked Search.")
        except Exception as e:
            print(f"❌ Search Button Failed: {e}")

        # 6. 結果一覧が表示されるのを待つ
        print("Waiting for results table...")
        try:
            # 「詳細」リンクが含まれる行が表示されるまで最大20秒待つ
            wait.until(EC.presence_of_element_located((By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")))
            print("✅ Results loaded!")
        except:
            print("⚠️ No results found (Timeout). Market might be empty.")

        # 7. 物件情報を取得
        rows = driver.find_elements(By.XPATH, "//tr[.//a[contains(@href, 'detail')]]")
        print(f"Scanning {len(rows)} apartments...")
        
        new_finds = 0
        current_scan_ids = []

        for row in rows:
            try:
                text = row.text.replace("\n", " ")
                link = row.find_element(By.XPATH, ".//a[contains(@href, 'detail')]").get_attribute("href")
                
                # 価格の抽出（カンマ区切りの数字を探す）
                raw_nums = re.findall(r'[0-9,]+', text)
                price_int = 999999
                for s in raw_nums:
                    try:
                        val = int(s.replace(",", ""))
                        if val > 10000: # 部屋番号などを除外するため1万以上を家賃とみなす
                            price_int = val
                            break
                    except: continue

                current_scan_ids.append(link)

                # 新着チェック & 家賃フィルター
                if link not in seen_apartments:
                    if price_int <= MAX_RENT:
                        print(f"MATCH! {text[:20]}... ({price_int})")
                        send_discord_alert("JKK Apartment", f"{price_int} Yen", "Check Link", link)
                        new_finds += 1
            except: pass 

        # 履歴を保存
        if new_finds > 0:
            seen_apartments.extend(current_scan_ids)
            seen_apartments = list(set(seen_apartments))
            with open(SEEN_FILE, 'w') as f:
                json.dump(seen_apartments, f)
            print(f"Sent {new_finds} alerts.")

    except Exception as e:
        print(f"Critical Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
