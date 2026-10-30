"""DiscordでiPhoneに届ける。

1記事を「案内」「タイトル」「本文」の3メッセージで送る。
本文は無料部分と有料部分の間に空行を入れてあり、noteに丸ごと貼ると
有料ラインがその余白に収まる。
"""
import time

GAP = "\n" * 6   # 無料部分と有料部分の間の余白（有料ラインがここに収まる）

import requests

from . import config


# 送り先。send_article の間だけフォーラムの投稿（スレッド）に切り替える
_target = {"url": None, "thread_id": None, "thread_name": None}


def _post(content: str):
    url = _target["url"] or config.DISCORD_WEBHOOK_URL
    if not url:
        print("（DISCORD_WEBHOOK_URL 未設定のため送信をスキップ）")
        return
    payload = {"content": content}
    params = {}
    if _target["thread_id"]:
        params["thread_id"] = _target["thread_id"]
    elif _target["thread_name"]:  # フォーラムに新しい投稿を作る（最初の1通）
        payload["thread_name"] = _target["thread_name"]
        params["wait"] = "true"
    for _ in range(5):
        r = requests.post(url, params=params, json=payload, timeout=20)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        if _target["thread_name"] and not _target["thread_id"]:
            _target["thread_id"] = r.json()["channel_id"]
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


def _label(text: str):
    """コピーしやすいよう、各パーツの前に区切りを入れる。"""
    _post(f"\u200b\n──────── {text} ────────")


def send_article(article: dict, deadline: str):
    """フォーラム用ウェブフックがあれば、記事ごとに別の投稿へまとめて送る。
    メインのチャンネルには「届いた」という1行だけ流す。"""
    if not config.DISCORD_FORUM_WEBHOOK_URL:
        _send_article_body(article, deadline)
        return
    name = f"{deadline}締切｜{article['title']}".replace("\n", " ")[:95]
    _target.update(url=config.DISCORD_FORUM_WEBHOOK_URL, thread_id=None, thread_name=name)
    try:
        _send_article_body(article, deadline)
    except Exception as e:  # フォーラムに送れなければ、いつものチャンネルに送る
        print(f"フォーラム送信失敗のため通常送信に切り替え: {e}")
        _target.update(url=None, thread_id=None, thread_name=None)
        _send_article_body(article, deadline)
        return
    finally:
        _target.update(url=None, thread_id=None, thread_name=None)
    send(f"📝 {name}（{article['price']}円）→ フォーラムに届きました")


def _send_article_body(article: dict, deadline: str):
    send(f"━━━━━━━━━━━━━━━━\n📝 新しい記事｜{article['price']}円｜締切 {deadline}")
    _label("📌 タイトル")
    send(article["title"])
    _label("📄 本文（無料＋余白＋有料）")
    body = article["free"] + GAP + article["paid"]
    if len(body) <= 1900:
        _post(body)
    else:  # 長すぎるときだけ、余白の位置で2通に分ける
        send(article["free"])
        _label("📄 本文の続き（有料部分）")
        send(article["paid"])
    if article.get("tags"):
        _label("#️⃣ ハッシュタグ")
        send(article["tags"])
    if article.get("x"):
        _label("🐦 X投稿用（URLを差し替えて投稿）")
        send(article["x"])
