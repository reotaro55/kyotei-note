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
        "本命の1着艇": int(bets["本命"][0][0]),
        "穴の1着艇": int(bets["穴"][0][0]),
        "選手データ": rows,
        "気象": (before or {}).get("weather", {}),
    }


PROMPT = """あなたは競艇予想noteブランド「艇眼｜TEIGAN」のライターです。
キャッチコピーは「強い艇を探すな。勝つ展開を見抜け。」。
以下のデータだけを根拠に、記事の文章を書いてください。

文体:
- 1行は短く（25字前後まで）、言い切りの体言止め・常体でテンポよく
- 例:「実力だけでは決まらない一戦。」「スタートから1マークの攻防、2・3着の残り目まで読み込んだ。」

ルール:
- データにない数字や情報を作らない
- 「絶対」「必ず」「確実」「100%」「儲かる」など的中や利益を保証する表現は使わない
- 買い目は「本命」（本命の1着艇が逃げ・先マイ）と「穴」（穴の1着艇が差し・まくり等で勝つ）の2本立て

出力はJSONのみ:
{"hook": "見出しの一言（20字以内。⚡は付けない）",
 "lines": ["無料部分の短い文を3〜4行。レースの見どころ。艇番・選手名・買い目は書かない"],
 "tenkai": ["有料部分の展開予想を3〜5行。どの艇がどう動くか。データの数字を1〜2個使う"],
 "honmei": "本命の根拠を1行（30字以内）",
 "ana": "穴の根拠を1行（30字以内）"}

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
            if out.get("hook") and out.get("lines") and out.get("tenkai"):
                return out
            LAST_ERROR = "返ってきた文章の形式が想定と違いました"
            break
        except Exception as e:  # 失敗してもテンプレートで続行する
            LAST_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
            break
    print(f"ChatGPT API エラー（テンプレート文で代用）: {LAST_ERROR}")
    return None


HOOKS = ["実力と機力がぶつかる一戦。", "勝負どころを見極める。", "展開ひとつで景色が変わる。", "1マークの攻防がカギ。"]


def _template(facts: dict) -> dict:
    rows = {r["枠"]: r for r in facts["選手データ"]}
    hm, an = rows[facts["本命の1着艇"]], rows[facts["穴の1着艇"]]
    i = int(facts["レース"].rstrip("R")) % len(HOOKS)
    return {
        "hook": HOOKS[i],
        "lines": ["機力・スタート・進入・展開を総合的に評価。",
                  "人気順だけでは拾いきれない可能性も探った。"],
        "tenkai": [f"{hm['枠']}号艇{hm['選手']}が主導権を握る展開が本線。",
                   f"全国勝率{hm['全国勝率']:.2f}、モーター2連率{hm['モーター2連率']:.1f}%。",
                   f"崩れるなら{an['枠']}号艇{an['選手']}の一撃。"],
        "honmei": f"{hm['枠']}号艇の地力と機力を信頼。",
        "ana": f"{an['枠']}号艇が攻めて主導権を奪う展開。",
    }


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


def _para(lines) -> str:
    """noteで読みやすいよう、1行ごとに空行を入れる。"""
    return "\n\n".join(clean_ng(str(x)).strip() for x in lines if str(x).strip())


def build_article(kind, race, bets, before=None, tenji_ranks=None, post_notes=None) -> dict:
    facts = _facts(kind, race, bets, before, tenji_ranks, post_notes)
    t = _llm(facts) or _template(facts)
    price = config.PRICE_PRE if kind == "pre" else config.PRICE_POST
    head = (f"🔥 艇眼｜本日の注目レース" if kind == "pre"
            else f"🔥 艇眼｜{race.get('grade', '')}{race['venue']}{race['rno']}R 展示後予想")
    hd = race.get("hd", "")
    date = f"{int(hd[4:6])}/{int(hd[6:8])} " if len(hd) == 8 else ""
    top = [f"🚤 {date}{race['venue']}{race['rno']}R"]
    if race.get("title"):
        top.append(f"🏆 {race['title']}")
    free_lines = [f"⚡ {t['hook']}"] + list(t["lines"])
    if kind == "post":
        free_lines.append("👁️ 展示タイム・スタート展示まで反映した最終判断。")
    free_lines += ["🔥 本命と穴、異なる展開を想定して6点に絞る。",
                   "🎯 本命3点＋穴3点",
                   f"🔐 ここから有料予想【{price}円】"]
    free_part = head + "\n\n" + "\n".join(top) + "\n\n" + _para(free_lines)

    paid_part = "\n\n".join([
        "🔥 展開予想",
        _para(t["tenkai"]),
        "🎯 本命（3点）\n" + "\n".join(bets["本命"]),
        clean_ng(t["honmei"]),
        "💣 穴（3点）\n" + "\n".join(bets["穴"]),
        clean_ng(t["ana"]),
        "📊 データ\n" + _data_table(facts),
        config.DISCLAIMER,
    ])
    return {"title": make_title(kind, race), "price": price, "free": free_part, "paid": paid_part}
