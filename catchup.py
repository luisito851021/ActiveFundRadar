"""
catchup.py — 開機補跑當日錯過的排程（由 ActiveFundRadar_CatchUp 在登入時觸發）

依觸發時間先後「逐一」啟動今天已過了觸發時間、卻還沒跑過的排程，等前一個結束才啟動下一個。
不直接把各排程設成「錯過後盡快執行」，是因為那樣晚開機時 4 個排程會同時啟動，
cross_fund.py 可能在其他基金 diff 寫完前就跑，並把當天標記為已處理而漏掉共振訊號。

用 Start-ScheduledTask 啟動原排程（而不是自己呼叫 run.py），
這樣執行內容與排程設定一致，且 LastRunTime 會更新，重複登入不會重跑。
"""
import json
import subprocess
import time
from datetime import datetime

TASKS = [
    "ActiveFundRadar",
    "ActiveFundRadar_00403A",
    "ActiveFundRadar_00992A",
    "ActiveFundRadar_CrossFund",
]
LOG_PATH = r"C:\ActiveFundRadar\Files\catchup.log"
TIMEOUT_SEC = 40 * 60


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _ps(cmd):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True, text=True, encoding="utf-8",
    )
    return out.stdout.strip()


def task_info(name):
    raw = _ps(
        f"$t=Get-ScheduledTask -TaskName '{name}'; $i=Get-ScheduledTaskInfo -TaskName '{name}';"
        f"@{{start=$t.Triggers[0].StartBoundary; days=$t.Triggers[0].DaysOfWeek;"
        f" last=$i.LastRunTime.ToString('yyyy-MM-ddTHH:mm:ss'); state=[string]$t.State}} | ConvertTo-Json -Compress"
    )
    return json.loads(raw)


def scheduled_today(info, now):
    """回傳今天這個排程的觸發時間；今天不在觸發星期內則回傳 None"""
    days = info.get("days")
    # DaysOfWeek 位元：週日=1、週一=2 … 週六=64；Python weekday 週一=0
    if days and not (days & (1 << ((now.weekday() + 1) % 7))):
        return None
    hh, mm = info["start"][11:13], info["start"][14:16]
    return now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


def wait_done(name):
    deadline = time.time() + TIMEOUT_SEC
    time.sleep(5)
    while time.time() < deadline:
        if task_info(name)["state"] != "Running":
            return True
        time.sleep(15)
    return False


if __name__ == "__main__":
    now = datetime.now()
    infos = {n: task_info(n) for n in TASKS}
    plan = []
    for n in TASKS:
        due = scheduled_today(infos[n], now)
        if due is None or now < due:
            continue
        if datetime.fromisoformat(infos[n]["last"]) >= due:
            continue
        plan.append((due, n))

    if not plan:
        log("[catchup] 今日無錯過的排程")
    for due, n in sorted(plan):
        log(f"[catchup] 補跑 {n}（原定 {due:%H:%M}）")
        _ps(f"Start-ScheduledTask -TaskName '{n}'")
        ok = wait_done(n)
        log(f"[catchup] {n} {'完成' if ok else '逾時，仍在執行'}，"
            f"LastTaskResult={_ps(f'(Get-ScheduledTaskInfo -TaskName {n}).LastTaskResult')}")
