import requests
import urllib3
import glob
import os
import re
from datetime import datetime, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _prev_trading_day(d):
    """
    回推到 d 之前最近一個交易日（跳過週末與國定假日）。
    群益 00992A 頁面的日期選擇器標示「最新日期」，實際是 PCF 適用日（T+1），
    成分股權重反映的是這個日期的前一個交易日收盤價，需回推校正。
    """
    year = d.year
    holidays = set()
    try:
        resp = requests.get(
            f"https://cdn.jsdelivr.net/gh/ruyut/TaiwanCalendar/data/{year}.json",
            timeout=10, verify=False,
        )
        resp.raise_for_status()
        holidays = {e["date"] for e in resp.json() if e["isHoliday"]}
    except Exception as e:
        print(f"[警告] 無法取得 {year} 年行事曆，僅以週末判斷交易日：{e}")

    while True:
        d -= timedelta(days=1)
        if d.weekday() < 5 and d.strftime("%Y%m%d") not in holidays:
            return d

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
    {"code": "63YTW", "name": "00403A"},
    {"code": "64YTW", "name": "00411A"},
    {"code": "65YTW", "name": "00987D"},
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

    driver = webdriver.Chrome(options=options)
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

        date_val    = date_input.get_attribute("value")  # "2026/04/24"（頁面標「最新日期」，實為 PCF 適用日 T+1）
        picker_date = datetime.strptime(date_val, "%Y/%m/%d")
        data_date   = _prev_trading_day(picker_date)     # 回推到權重實際反映的收盤交易日
        date_str    = data_date.strftime("%Y-%m-%d")

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


def download_00991A_http():
    """
    下載 00991A 持倉 xlsx。
    直接對 API 逐日探測（今天往回推），不再爬頁面上的下載連結日期——
    該連結的日期是頁面 datepicker 的預設值，會卡住不動，跟實際可下載的最新資料日期脫節。
    """
    fund_id = "00991A"
    fund_folder = os.path.join(SAVE_FOLDER, fund_id)
    os.makedirs(fund_folder, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    }

    existing_dates = {
        os.path.basename(f)[len(fund_id) + 1:-5]
        for f in glob.glob(os.path.join(fund_folder, f"{fund_id}_*.xlsx"))
    }

    saved_paths = []
    d = datetime.now().date()
    for _ in range(10):
        date_str = d.strftime("%Y-%m-%d")
        if date_str in existing_dates:
            break  # 已碰到抓過的日期，更早的應該也都抓過了

        api_url = f"https://www.fhtrust.com.tw/api/assetsExcel/ETF23/{d.strftime('%Y%m%d')}"
        try:
            resp = requests.get(api_url, headers=headers, timeout=30)
            resp.raise_for_status()
            if "excel" in resp.headers.get("Content-Type", ""):
                save_path = os.path.join(fund_folder, f"{fund_id}_{date_str}.xlsx")
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                saved_paths.append(save_path)
                print(f"[成功] {fund_id} 下載完成 → {os.path.basename(save_path)}")
        except Exception as e:
            print(f"[錯誤] {fund_id} {date_str} 下載失敗：{e}")

        d -= timedelta(days=1)

    if not saved_paths:
        print(f"[跳過] {fund_id} 沒有新資料")
        return None
    return sorted(saved_paths)[-1]


def download_00990A_selenium():
    """用 Selenium 載入元大頁面，點「展開」後刮全部持倉，存成 CSV"""
    import time, csv
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options

    fund_id     = "00990A"
    fund_folder = os.path.join(SAVE_FOLDER, fund_id)
    os.makedirs(fund_folder, exist_ok=True)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--ignore-certificate-errors")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("https://www.yuantaetfs.com/product/detail/00990A/ratio")
        wait = WebDriverWait(driver, 30)

        # 等第一筆資料出現
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".tbody .tr")))

        # 頁面上「持股列表」與「投資區域」各自有一顆「展開」按鈕，兩個都要點才能拿到完整列表
        for more_btn in driver.find_elements(By.CSS_SELECTOR, ".moreBtn"):
            try:
                if "on" not in more_btn.get_attribute("class"):
                    driver.execute_script("arguments[0].click();", more_btn)
            except Exception:
                pass
        time.sleep(1.5)

        # 取得日期
        trandate = driver.find_element(By.CSS_SELECTOR, ".trandate")
        dm = re.search(r"(\d{4})/(\d{2})/(\d{2})", trandate.text)
        if not dm:
            print(f"[錯誤] {fund_id} 找不到日期")
            return None
        data_date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"

        save_path = os.path.join(fund_folder, f"{fund_id}_{data_date}.csv")
        if os.path.exists(save_path):
            print(f"[跳過] {fund_id} 今日檔案已存在 → {os.path.basename(save_path)}")
            return save_path

        # 刮全部列。頁面上第 1 個 .tbody 是持股列表，第 2 個是投資區域比例表
        soup    = BeautifulSoup(driver.page_source, "html.parser")
        tbodies = soup.find_all("div", class_="tbody")
        rows    = tbodies[0].find_all("div", class_="tr") if len(tbodies) > 0 else []

        with open(save_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "ticker", "name", "shares", "weight"])
            for tr in rows:
                tds = tr.find_all("div", class_="td")
                if len(tds) < 4:
                    continue
                ticker = tds[0].find_all("span")[-1].get_text(strip=True)
                name   = tds[1].find_all("span")[-1].get_text(strip=True)
                shares = tds[2].find_all("span")[-1].get_text(strip=True)
                weight = tds[3].find_all("span")[-1].get_text(strip=True)
                writer.writerow([data_date, ticker, name, shares, weight])

        print(f"[成功] {fund_id} 下載完成 → {os.path.basename(save_path)}（{len(rows)} 筆）")

        # 投資區域比例表（名稱／比例／檔數），供 region.py 解析寫入 region_ratios
        region_rows = tbodies[1].find_all("div", class_="tr") if len(tbodies) > 1 else []
        if region_rows:
            region_path = os.path.join(fund_folder, f"{fund_id}_region_{data_date}.csv")
            with open(region_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "region", "ratio", "count"])
                for tr in region_rows:
                    tds = tr.find_all("div", class_="td")
                    if len(tds) < 3:
                        continue
                    region = tds[0].find_all("span")[-1].get_text(strip=True)
                    ratio  = tds[1].find_all("span")[-1].get_text(strip=True)
                    count  = tds[2].find_all("span")[-1].get_text(strip=True)
                    writer.writerow([data_date, region, ratio, count])
            print(f"[成功] {fund_id} 投資區域下載完成 → {os.path.basename(region_path)}（{len(region_rows)} 筆）")
        else:
            print(f"[警告] {fund_id} 找不到投資區域表格，略過")

        return save_path

    except Exception as e:
        print(f"[錯誤] {fund_id} Selenium 失敗：{e}")
        return None
    finally:
        driver.quit()


if __name__ == "__main__":
    import sys
    target = sys.argv[1:] if len(sys.argv) > 1 else ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"]

    for fund in FUND_CONFIGS:
        if fund["name"] in target:
            download_etf_excel(fund["code"], fund["name"])

    if "00992A" in target:
        download_00992A_selenium()

    if "00991A" in target:
        download_00991A_http()

    if "00990A" in target:
        download_00990A_selenium()