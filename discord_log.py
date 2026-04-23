import os
import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SYSLOG_CHANNEL_ID = os.getenv("DISCORD_SYSLOG_CHANNEL")

def send_syslog(message: str):
    if not DISCORD_BOT_TOKEN or not SYSLOG_CHANNEL_ID:
        print("[SysLog] 未設定 DISCORD_BOT_TOKEN 或 DISCORD_SYSLOG_CHANNEL，跳過")
        return
    url = f"https://discord.com/api/v10/channels/{SYSLOG_CHANNEL_ID}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    chunks = [message[i:i+2000] for i in range(0, len(message), 2000)]
    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk})
        if resp.status_code not in (200, 201):
            print(f"[SysLog] 發送失敗：{resp.status_code} {resp.text[:120]}")
