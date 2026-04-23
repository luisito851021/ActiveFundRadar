import subprocess
import sys
import re
import os
from datetime import datetime
import sqlite3

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from discord_log import send_syslog


def _run(script, args=[]):
    cmd = [sys.executable, script] + args
    print(f"\n{'='*40}")
    print(f"執行：{' '.join(cmd)}")
    print('='*40)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(
        cmd, cwd=r"C:\ActiveFundRadar",
        capture_output=True,
        env=env,
    )
    output = (
        result.stdout.decode("utf-8", errors="replace") +
        result.stderr.decode("utf-8", errors="replace")
    )
    print(output, end="")
    return result.returncode == 0, output


def _get_latest_date(fund_id, db_path=r"C:\ActiveFundRadar\etf.db"):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT date FROM holdings WHERE fund_id=? ORDER BY date DESC LIMIT 1",
        (fund_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _get_counts(fund_id, date, db_path=r"C:\ActiveFundRadar\etf.db"):
    conn = sqlite3.connect(db_path)
    h = conn.execute(
        "SELECT COUNT(*) FROM holdings WHERE fund_id=? AND date=?", (fund_id, date)
    ).fetchone()[0]
    c = conn.execute(
        "SELECT COUNT(*) FROM daily_changes WHERE fund_id=? AND date=?", (fund_id, date)
    ).fetchone()[0]
    conn.close()
    return h, c



def _parse_send(output):
    tg = True if "[Telegram] 發送成功" in output else (False if "[Telegram] 發送失敗" in output else None)
    dc = True if "[Discord] 發送成功" in output else (False if "[Discord] 發送失敗" in output else None)
    return tg, dc


def _parse_tokens(output):
    m = re.search(r'\[Token\] input=(\d+)\s+output=(\d+)\s+total=(\d+)', output)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (None, None, None)


def _icon(val):
    return {True: "✅", False: "❌", None: "➖"}.get(val, "➖")


def _build_report(start_str, steps, fund_stats, elapsed):
    lines = [
        "📋 **ActiveFundRadar 執行報告**",
        f"🕐 {start_str}",
        "",
        "**📦 執行步驟**",
        f"{_icon(steps.get('download'))} `download.py` — 下載 XLSX",
        f"{_icon(steps.get('main'))} `main.py`　　 — 寫入資料庫",
    ]

    for fund_id, s in fund_stats.items():
        if not s:
            continue
        date_str = s.get("date", "?")
        holdings = s.get("holdings", "?")
        changes  = s.get("changes", "?")
        lines += [
            "",
            f"**📊 {fund_id}　{date_str}**",
            f"　持倉 **{holdings}** 檔　異動 **{changes}** 筆",
            f"　{_icon(steps.get(f'diff_{fund_id}'))} `diff.py`",
        ]

        tg, dc = s.get("notify_tg"), s.get("notify_dc")
        lines.append(
            f"　{_icon(steps.get(f'notify_{fund_id}'))} `notify.py`"
            f"　TG:{_icon(tg)}　DC:{_icon(dc)}"
        )

        tg2, dc2 = s.get("analyze_tg"), s.get("analyze_dc")
        tokens = s.get("tokens")
        tok_str = f"　Token: `{tokens[0]:,}in / {tokens[1]:,}out`" if tokens else ""
        lines.append(
            f"　{_icon(steps.get(f'analyze_{fund_id}'))} `analyze.py`"
            f"　TG:{_icon(tg2)}　DC:{_icon(dc2)}{tok_str}"
        )

    lines += ["", f"⏱ 總耗時：**{elapsed}** 秒"]
    return "\n".join(lines)


if __name__ == "__main__":
    start = datetime.now()
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n🚀 ActiveFundRadar 自動執行開始：{start_str}")

    steps      = {}
    fund_stats = {"00988A": {}, "00981A": {}}

    # Step 1：下載 XLSX
    ok, _ = _run("download.py")
    steps["download"] = ok
    if not ok:
        print("[中止] 下載失敗，請檢查網路或 Cookie 是否過期")
        send_syslog(
            f"❌ **ActiveFundRadar 中止**\n🕐 {start_str}\n\n"
            f"❌ `download.py` 失敗，請檢查網路或 Cookie"
        )
        sys.exit(1)

    # Step 2：寫入資料庫
    ok, _ = _run("main.py")
    steps["main"] = ok
    if not ok:
        print("[中止] 寫入資料庫失敗")
        send_syslog(
            f"❌ **ActiveFundRadar 中止**\n🕐 {start_str}\n\n"
            f"✅ `download.py`\n❌ `main.py` 寫入資料庫失敗"
        )
        sys.exit(1)

    # Step 3：各 ETF diff → notify → analyze
    for fund_id in ["00988A", "00981A"]:
        latest = _get_latest_date(fund_id)
        if not latest:
            print(f"[跳過] {fund_id} 資料庫無資料")
            continue

        fund_stats[fund_id]["date"] = latest
        print(f"\n📅 {fund_id} 最新日期：{latest}")

        ok, _ = _run("diff.py", [latest])
        steps[f"diff_{fund_id}"] = ok
        if not ok:
            print(f"[警告] {fund_id} diff 執行失敗")
            continue

        # diff 完成後才能取到正確的 changes 數量
        h, c = _get_counts(fund_id, latest)
        fund_stats[fund_id]["holdings"] = h
        fund_stats[fund_id]["changes"]  = c

        ok, output = _run("notify.py", [latest, fund_id])
        steps[f"notify_{fund_id}"] = ok
        tg, dc = _parse_send(output)
        fund_stats[fund_id]["notify_tg"] = tg
        fund_stats[fund_id]["notify_dc"] = dc

        ok, output = _run("analyze.py", [latest, fund_id])
        steps[f"analyze_{fund_id}"] = ok
        tg, dc = _parse_send(output)
        fund_stats[fund_id]["analyze_tg"] = tg
        fund_stats[fund_id]["analyze_dc"] = dc
        inp, out, total = _parse_tokens(output)
        if inp is not None:
            fund_stats[fund_id]["tokens"] = (inp, out, total)

    elapsed = int((datetime.now() - start).total_seconds())
    print(f"\n✅ 全部完成：{datetime.now().strftime('%H:%M:%S')}")

    report = _build_report(start_str, steps, fund_stats, elapsed)
    send_syslog(report)
