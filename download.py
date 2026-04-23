import requests
import urllib3
import glob
import os
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 設定區 ────────────────────────────────────────
SAVE_FOLDER = r"C:\ActiveFundRadar\Files"


# 每次 Cookie 過期就來這裡更新（從 Chrome DevTools 複製）
COOKIES = {
    "_nxquid":                    "obZpieYzkTcgEo+dF3idAX9+5R9ctw==0018",
    "__RequestVerificationToken": "hIQ9IFUjeMAHfro-ZPVtyRc0vZhACLVeGj7hHQLcPxQDjcjZVNbP_uLhHEMp3KV5DD-GeGq-9eSQ8rtefNhYQM9g-IWzmcNVaRsrKwLHYgk1",
    "_ga":                        "GA1.1.995097158.1773665611",
    "_ga_3MMYCX29JS":             "GS2.1.s1774526227$o10$g1$t1774526228$j59$l0$h1964111591",
    "_gcl_au":                    "1.1.1052116248.1773665611",
    "ASP.NET_SessionId":          "la345cdxk3auxkpaarztt4if",
}

FUND_CONFIGS = [
    {"code": "61YTW", "name": "00988A"},
    {"code": "49YTW", "name": "00981A"},
]

CAPITAL_00992A_URL = "https://www.capitalfund.com.tw/etf/product/detail/500/portfolio"

def download_etf_excel(fund_code: str, fund_name: str):
    url = f"https://www.ezmoney.com.tw/ETF/Fund/AssetExcelNPOI?fundCode={fund_code}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Referer": f"https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={fund_code}",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    resp = requests.get(url, headers=headers, cookies=COOKIES, timeout=30, verify=False)
    
    if resp.status_code != 200:
        print(f"[錯誤] {fund_name} 下載失敗，狀態碼：{resp.status_code}")
        return None
    
    # 從 Content-Disposition 取得原始檔名
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        filename = cd.split("filename=")[-1].strip()
    else:
        filename = f"ETF_Investment_Portfolio_{datetime.now().strftime('%Y%m%d')}.xlsx"
    
    # 各自存到子資料夾
    fund_folder = os.path.join(SAVE_FOLDER, fund_name)
    os.makedirs(fund_folder, exist_ok=True)
    filename_with_fund = f"{fund_name}_{filename}"
    save_path = os.path.join(fund_folder, filename_with_fund)

    if os.path.exists(save_path):
        print(f"[跳過] {fund_name} 今日檔案已存在 → {filename}")
        return save_path

    with open(save_path, "wb") as f:
        f.write(resp.content)

    print(f"[成功] {fund_name} 下載完成 → {filename}")
    return save_path

def download_00992A_selenium():
    import time
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options

    fund_id     = "00992A"
    fund_folder = os.path.abspath(os.path.join(SAVE_FOLDER, fund_id))
    os.makedirs(fund_folder, exist_ok=True)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("prefs", {
        "download.default_directory":   fund_folder,
        "download.prompt_for_download": False,
        "download.directory_upgrade":   True,
    })

    chromedriver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe")
    service = webdriver.ChromeService(executable_path=chromedriver_path)
    driver  = webdriver.Chrome(service=service, options=options)
    # headless 模式需要 CDP 才能正常下載
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior":     "allow",
        "downloadPath": fund_folder,
    })

    try:
        driver.get(CAPITAL_00992A_URL)
        wait = WebDriverWait(driver, 30)

        # 等待 Angular 填入日期
        date_input = wait.until(EC.presence_of_element_located((By.ID, "condition-date")))
        wait.until(lambda d: date_input.get_attribute("value") not in (None, ""))

        date_val = date_input.get_attribute("value")  # "2026/04/24"
        date_str = date_val.replace("/", "-")          # "2026-04-24"

        save_path = os.path.join(fund_folder, f"{fund_id}_{date_str}.xlsx")
        if os.path.exists(save_path):
            print(f"[跳過] {fund_id} 今日檔案已存在 → {os.path.basename(save_path)}")
            return save_path

        # 清除可能殘留的舊檔
        stale = os.path.join(fund_folder, "00992A.xlsx")
        if os.path.exists(stale):
            os.remove(stale)

        btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.buyback-search-section-btn")
        ))
        btn.click()

        # 等待 .xlsx 出現（最多 30 秒）
        for _ in range(60):
            time.sleep(0.5)
            xlsx_files = [
                f for f in os.listdir(fund_folder)
                if f.endswith(".xlsx") and not f.startswith("~$")
            ]
            crdownloads = [f for f in os.listdir(fund_folder) if f.endswith(".crdownload")]
            if xlsx_files and not crdownloads:
                src = os.path.join(fund_folder, xlsx_files[0])
                os.rename(src, save_path)
                print(f"[成功] {fund_id} 下載完成 → {os.path.basename(save_path)}")
                return save_path

        print(f"[錯誤] {fund_id} 下載超時（30 秒）")
        return None

    except Exception as e:
        print(f"[錯誤] {fund_id} Selenium 下載失敗：{e}")
        return None
    finally:
        driver.quit()


if __name__ == "__main__":
    for fund in FUND_CONFIGS:
        download_etf_excel(fund["code"], fund["name"])
    download_00992A_selenium()