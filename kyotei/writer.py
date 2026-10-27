"""記事の文章を作る。

買い目・数字はプログラムが決め、ChatGPTには「文章」だけを書かせる。
こうするとChatGPTが数字を間違えたり盛ったりしても、買い目は狂わない。
"""
import json
import re

import requests

from . import config

NG_WORDS = {
    "絶対": "かなり",
    "必ず": "高い確率で",
    "確実": "有力",
    "100%": "高確率",
    "１００％": "高確率",
    "鉄板": "信頼度が高い",
    "間違いない": "期待できる",
    "儲かる": "狙い目",
    "勝てる": "狙える",
}


def clean_ng(text: str) -> str:
    for ng, ok in NG_WORDS.items():
        text = text.replace(ng, ok)
    return text


def stars(score: float) -> str:
    n = 5 if score >= 85 else 4 if score >= 70 else 3 if score >= 55 else 2
    return "★" * n + "☆" * (5 - n)


def make_title(kind: str, race: dict) -> str:
    """艇眼のタイトル形式: 🔥🚤【艇眼】10/28 SG尼崎6R｜展示後予想⚡"""
    hd = race.get("hd", "")
    date = f"{int(hd[4:6])}/{int(hd[6:8])} " if len(hd) == 8 else ""
    label = "事前予想" if kind == "pre" else "激アツ展示後予想"
    return f"🔥🚤【艇眼】{date}{race.get('grade', '')}{race['venue']}{race['rno']}R｜{label}⚡"


def _facts(kind, race, bets, before=None, tenji_ranks=None, post_notes=None):
    rows = []
    for w in range(1, 7):
        b = race["boats"].get(w)
        if not b:
            continue
        row = {
            "枠": w, "選手": b["name"], "級別": b["class"],
            "全国勝率": b["win_rate"], "当地勝率": b["local_win_rate"],
            "平均ST": b["avg_st"], "モーター2連率": b["motor2"],
        }
        if before:
            bb = before["boats"].get(w, {})
            row["展示タイム"] = bb.get("tenji_time")
            row["展示タイム順位"] = (tenji_ranks or {}).get(w)
            st = next((v for v in before["start"].values() if v.get("boat") == w), None)
            if st:
                row["スタート展示ST"] = st["st"]
        rows.append(row)
    return {
        "種類": "事前予想" if kind == "pre" else "展示後予想",
        "場": race["venue"], "レース": f"{race['rno']}R", "締切": race["deadline"],
        "レース名": race.get("title", ""),
        "1号艇の信頼度(100点満点)": race["score"],
        "ポイント": post_notes or race["notes"],
        "買い目": bets,
        "選手データ": rows,
        "気象": (before or {}).get("weather", {}),
    }


PROMPT = """あなたは競艇予想noteのライターです。以下のデータだけを根拠に、記事の文章を書いてください。

ルール:
- データにない数字や情報を作らない
- 「絶対」「必ず」「確実」「100%」「儲かる」など的中や利益を保証する表現は使わない
- 買い目は書き換えない（文章内で触れる場合はデータの通りに）
- 読みやすい日本語、です・ます調

出力はJSONのみ:
{"free": "無料部分（120〜180字。レースの見どころと1号艇の評価。買い目や2・3着候補は書かない）",
 "reason": "有料部分の根拠（300〜450字。1号艇を信頼する理由と、2・3着候補を選んだ理由。データの数字を使う）"}

データ:
"""


LAST_ERROR = ""


def _llm(facts: dict) -> dict | None:
    """ChatGPTに文章を書かせる。失敗したら None（理由は LAST_ERROR に残す）。"""
    global LAST_ERROR
    LAST_ERROR = ""
    if not config.OPENAI_API_KEY:
        LAST_ERROR = "キー未設定"
        return None
    body = {
        "model": config.OPENAI_MODEL,
        "messages": [{"role": "user", "content": PROMPT + json.dumps(facts, ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
    }
    for attempt in range(2):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json=body, timeout=90,
            )
            if r.status_code != 200:
                try:
                    msg = r.json().get("error", {}).get("message", "")
                except ValueError:
                    msg = r.text[:200]
                LAST_ERROR = f"HTTP {r.status_code}: {msg[:300]}"
                # JSON指定に未対応のモデルなら外して再挑戦
                if attempt == 0 and "response_format" in msg:
                    body.pop("response_format", None)
                    continue
                break
            text = r.json()["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{.*\}", text, re.S)
            out = json.loads(m.group(0) if m else text)
            if out.get("free") and out.get("reason"):
                return out
            LAST_ERROR = "返ってきた文章の形式が想定と違いました"
            break
        except Exception as e:  # 失敗してもテンプレートで続行する
            LAST_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
            break
    print(f"ChatGPT API エラー（テンプレート文で代用）: {LAST_ERROR}")
    return None


def _template(facts: dict) -> dict:
    b1 = facts["選手データ"][0]
    free = (f"{facts['場']}{facts['レース']}は1号艇{b1['選手']}選手（{b1['級別']}）に注目。"
            f"全国勝率{b1['全国勝率']:.2f}と、メンバーの中で地力上位の存在です。"
            f"インからの逃げが本線になるレースと見ています。")
    reason = ("■ポイント\n" + "\n".join(f"・{n}" for n in facts["ポイント"]) +
              f"\n\n1号艇の信頼度は{facts['1号艇の信頼度(100点満点)']}点。"
              "1着は1号艇に固定し、勝率・モーター・枠の並びから相手を絞りました。")
    return {"free": free, "reason": reason}


def _data_table(facts: dict) -> str:
    lines = []
    for r in facts["選手データ"]:
        line = (f"{r['枠']}号艇 {r['選手']}（{r['級別']}） 勝率{r['全国勝率']:.2f}"
                f" モーター{r['モーター2連率']:.1f}%")
        if r.get("展示タイム"):
            line += f" 展示{r['展示タイム']:.2f}（{r.get('展示タイム順位')}位）"
        if r.get("スタート展示ST") is not None:
            line += f" ST{r['スタート展示ST']:.2f}"
        lines.append(line)
    return "\n".join(lines)


def build_article(kind, race, bets, before=None, tenji_ranks=None, post_notes=None) -> dict:
    facts = _facts(kind, race, bets, before, tenji_ranks, post_notes)
    text = _llm(facts) or _template(facts)
    free = clean_ng(text["free"]).strip()
    reason = clean_ng(text["reason"]).strip()
    free_part = f"{free}\n\n1号艇の信頼度：{stars(race['score'])}"
    if kind == "post":
        free_part += "\n展示タイム・スタート展示を反映した最終予想です。"
    paid_part = (
        f"■買い目（3連単 {len(bets)}点）\n" + "\n".join(bets) +
        f"\n\n■根拠\n{reason}\n\n■データ\n{_data_table(facts)}\n\n{config.DISCLAIMER}"
    )
    return {
        "title": make_title(kind, race),
        "price": config.PRICE_PRE if kind == "pre" else config.PRICE_POST,
        "free": free_part,
        "paid": paid_part,
    }
