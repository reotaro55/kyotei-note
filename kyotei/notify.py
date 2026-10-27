"""DiscordでiPhoneに届ける。

1記事を「案内」「タイトル」「本文」の3メッセージで送る。
本文は無料部分と有料部分の間に空行を入れてあり、noteに丸ごと貼ると
有料ラインがその余白に収まる。
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


GAP = "\n" * 6   # 無料部分と有料部分の間の余白（有料ラインがここに収まる）


def send_article(article: dict, deadline: str):
    send(f"━━━━━━━━━━\n📝 新しい記事｜{article['price']}円｜締切 {deadline}\n"
         f"↓ タイトル → 本文（無料＋余白＋有料）→ ハッシュタグ → X投稿用の順に届きます")
    send(article["title"])
    body = article["free"] + GAP + article["paid"]
    if len(body) <= 1900:
        _post(body)
    else:  # 長すぎるときだけ、余白の位置で2通に分ける
        send(article["free"])
        send(article["paid"])
    if article.get("tags"):
        send(article["tags"])
    if article.get("x"):
        send("🐦 ↓X投稿用（URLを差し替えて投稿）")
        send(article["x"])
