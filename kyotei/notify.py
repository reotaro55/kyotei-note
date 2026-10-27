"""DiscordでiPhoneに届ける。

1記事を「案内」「タイトル」「無料部分」「有料部分」の4メッセージに分けて送る。
iPhoneのDiscordでメッセージを長押し →「テキストをコピー」→ noteに貼り付け。
"""
import time

import requests

from . import config


def _post(content: str):
    if not config.DISCORD_WEBHOOK_URL:
        print("（DISCORD_WEBHOOK_URL 未設定のため送信をスキップ）")
        return
    for _ in range(5):
        r = requests.post(config.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=20)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        time.sleep(0.6)
        return
    raise RuntimeError("Discordへの送信に失敗しました")


def send(text: str):
    """2000字制限に合わせて分割して送る。"""
    while text:
        if len(text) <= 1900:
            _post(text)
            return
        cut = text.rfind("\n", 0, 1900)
        cut = cut if cut > 500 else 1900
        _post(text[:cut])
        text = text[cut:].lstrip("\n")


def send_article(article: dict, deadline: str):
    send(f"━━━━━━━━━━\n📝 新しい記事｜{article['price']}円｜締切 {deadline}\n"
         f"↓ タイトル・無料部分・有料部分の順に届きます")
    send(article["title"])
    send(article["free"])
    send(article["paid"])
