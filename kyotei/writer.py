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
            "今節得点率": round(b["form"], 2) if b.get("form") is not None and b.get("kon_n", 0) >= 2 else None,
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
- シンプルに。1行は20字前後まで、言い切りの体言止め・常体
- 専門用語は1行に1つまで。用語を重ねてくどくしない。数字は展開予想全体で1つまで
- 競艇のプロ・記者が使う専門用語で書く。素人っぽい言い方（「速い」「強い」「勝ちそう」）は避ける
- 使う用語の例:
  展開: イン逃げ／先マイ／差し／まくり／まくり差し／握って回る／ジカまくり／抜き／2マーク
  隊形: スロー勢／ダッシュ勢／壁になる／凹む／スリット／起こし／一撃／カド
  足色: 出足／行き足／伸び／回り足／ターン回り／舟足
  評価: 地力上位／機力上位／仕上がり／信頼度／相手本線／押さえ／ヒモ穴
- 良い例:
  「1号艇、先マイ濃厚。」
  「崩すなら3号艇のカド一撃。」
  「2号艇は差してヒモ。」

ルール:
- データにない数字や情報を作らない
- 「出足」「伸び」など足色の評価は、展示タイム等のデータがあるときだけ書く（事前予想ではモーター2連率を「機力」として書く）
- 隊形（スロー/ダッシュ・カド）は進入データがあればそれに、なければ枠なりと想定して書く
- 「絶対」「必ず」「確実」「100%」「儲かる」など的中や利益を保証する表現は使わない
- 買い目は「本命」と「穴」の2本立て。それぞれの1着艇の勝ちパターンをコースに合わせて書く
  （1コースならイン逃げ・先マイ、2コースなら差し、3〜4コースならまくり・まくり差し、5〜6コースならまくり差し・展開待ち）

無料部分（hook と lines）の書き方:
- 目的は「お金を払ってでも続きが見たい」と思わせること。答えは見せず、気になる“引っかかり”だけ見せる
- 本命・穴がどの艇か、どのコースか、どんな決まり手か が推測できることは書かない
  （NG: 艇番、選手名、「イン」「逃げ」「先マイ」「差し」「まくり」「カド」「外枠」「1コース」など）
- 使える引き: 「数字の裏に違和感」「人気だけでは見えない1艇」「1マークで“ある攻防”」「本命と穴で頭が違う」「展示で評価が動いた」(展示後のみ)
- 良い例:
  「このメンバー、素直には決まらない。」
  「数字の裏に、1つだけ違和感がある。」
  「勝負を分けるのは1マークの“ある攻防”。」
  「人気だけ見ていると、この1艇を見落とす。」
- データにない「人気」「オッズ」の具体的な話は作らない

出力はJSONのみ:
{"hook": "見出しの一言（20字以内。⚡は付けない）",
 "lines": ["無料部分の短い文を2〜3行。答えを伏せて続きが気になる書き方で"],
 "tenkai": ["有料部分の展開予想を2〜3行だけ。1行目=本線の展開、2行目=崩れるならこの形、3行目(任意)=根拠の数字"],
 "honmei": "本命の根拠を1行（20字以内）",
 "ana": "穴の根拠を1行（20字以内）",
 "kanpyo": ["各艇の寸評を1号艇から6号艇まで6つ。各40字以内。プロ目線で、その艇がどう動くか・何着までありそうか。データの範囲で（例: 地力はメンバー上位。先に回って押し切りまで）"]}

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


HOOKS = ["素直には決まらない一戦。", "数字の裏に、違和感がある。", "勝負を分けるのは“ある攻防”。", "見落とされがちな1艇がいる。"]
TEASERS = [
    ["人気だけ見ていると、この1艇を見落とす。", "本命と穴、頭は別の艇。"],
    ["勝負を分けるのは1マークの“ある攻防”。", "その答えは有料部分で。"],
    ["データを並べると、1つだけ引っかかる数字がある。", "そこから組み立てた6点。"],
    ["本線は1つ。でも崩れる形も見えている。", "両方押さえて6点勝負。"],
]
# 無料部分で答えが透けるNGワード
SPOILERS = re.compile(r"[1-6１-６]号艇|イン|逃げ|先マイ|差し|まくり|捲り|カド|外枠|内枠|[1-6１-６]コース|枠なり|ダッシュ|スロー")


def _safe_free(t: dict, i: int) -> tuple[str, list[str]]:
    """無料部分に答えが透ける言葉があれば、伏せた定型文に差し替える。"""
    hook = t["hook"] if not SPOILERS.search(t["hook"]) else HOOKS[i % len(HOOKS)]
    lines = [x for x in t["lines"] if not SPOILERS.search(str(x))]
    if len(lines) < 2:
        lines = TEASERS[i % len(TEASERS)]
    return hook, lines


def _template(facts: dict) -> dict:
    rows = {r["枠"]: r for r in facts["選手データ"]}
    hm, an = rows[facts["本命の1着艇"]], rows[facts["穴の1着艇"]]
    i = int(facts["レース"].rstrip("R")) % len(HOOKS)
    return {
        "hook": HOOKS[i],
        "lines": TEASERS[i % len(TEASERS)],
        "tenkai": [f"{hm['枠']}号艇、" + ("先マイで押し切り本線。" if hm['枠'] == 1 else "攻めて主導権。"),
                   f"崩すなら{an['枠']}号艇の一撃。",
                   f"モーター2連率{hm['モーター2連率']:.0f}%、機力上位。"],
        "honmei": f"{hm['枠']}号艇の" + ("イン逃げ。" if hm['枠'] == 1 else "攻め切り。"),
        "ana": f"{an['枠']}号艇が展開を作る形。",
        "kanpyo": [_kanpyo(r, facts) for r in facts["選手データ"]],
    }


def _kanpyo(r: dict, facts: dict) -> str:
    """ChatGPTが使えないときの寸評（データから機械的に作る）。"""
    rates = sorted((x["全国勝率"] for x in facts["選手データ"]), reverse=True)
    rank = rates.index(r["全国勝率"]) + 1
    s = "地力はメンバー上位。" if rank <= 2 else "地力は中位。" if rank <= 4 else "地力は見劣る。"
    if r["モーター2連率"] >= 40:
        s += "機力も上位。"
    if r.get("今節得点率") is not None and r["今節得点率"] >= 6.5:
        s += "今節は好調。"
    if r.get("展示タイム順位") == 1:
        s += "展示タイム1位で気配良好。"
    if r["枠"] == facts["本命の1着艇"]:
        s += "頭まで。"
    elif r["枠"] == facts["穴の1着艇"]:
        s += "展開ひとつで頭も。"
    return s


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
    hook, lines = _safe_free(t, race["rno"])
    free_lines = [f"⚡ {hook}"] + list(lines)
    if kind == "post":
        free_lines.append("👁️ 展示タイム・スタート展示まで反映した最終判断。")
    free_lines += ["🔥 本命と穴、異なる展開を想定して6点に絞る。",
                   "🎯 本命3点＋穴3点",
                   f"🔐 ここから有料予想【{price}円】"]
    free_part = head + "\n\n" + "\n".join(top) + "\n\n" + _para(free_lines)

    paid_part = "\n\n".join([
        "🔥 展開予想",
        _para(t["tenkai"]),
        "📝 各艇寸評\n" + "\n".join(f"{'①②③④⑤⑥'[i]}{clean_ng(str(c)).strip()}"
                                    for i, c in enumerate(list(t.get("kanpyo") or [])[:6])),
        "🎯 本命（3点）\n" + "\n".join(bets["本命"]),
        clean_ng(t["honmei"]),
        "💣 穴（3点）\n" + "\n".join(bets["穴"]),
        clean_ng(t["ana"]),
        "💰 配分の目安：本命◎厚め（2）：穴○（1）",
        "📊 データ\n" + _data_table(facts),
        config.DISCLAIMER,
    ])
    return {"title": make_title(kind, race), "price": price, "free": free_part, "paid": paid_part,
            "tags": make_tags(kind, race), "x": make_x_post(kind, race, hook, price)}


def x_len(text: str) -> int:
    """Xの文字数（日本語などは2、英数字は1。URLは23）。"""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(1 if ord(c) < 0x1100 else 2 for c in text)


def make_x_post(kind: str, race: dict, hook: str, price: int) -> str:
    """X（旧Twitter）告知用の短文。noteのURLは公開後にアニキが貼る。"""
    hd = race.get("hd", "")
    date = f"{int(hd[4:6])}/{int(hd[6:8])} " if len(hd) == 8 else ""
    label = "事前予想" if kind == "pre" else "展示後予想"
    lines = [
        f"🔥【艇眼】{date}{race.get('grade', '')}{race['venue']}{race['rno']}R {label}",
        f"⚡{hook}",
        f"🎯本命3点＋穴3点｜{price}円",
        f"⏰締切 {race['deadline']}",
        "👇続きはnoteで",
        "（ここにnoteのURL）",
        "#競艇予想 #ボートレース",
    ]
    text = "\n".join(lines)
    while x_len(text.replace("（ここにnoteのURL）", "https://note.com/x")) > 280 and len(lines) > 5:
        lines.pop(3)  # 長いときは締切の行から削る
        text = "\n".join(lines)
    return text


# noteで記事数の多い競艇系タグ（2026年10月時点）
#   #競艇予想 約330万 / #競艇 約240万 / #ボートレース 約175万
#   #競艇予想屋 約98万 / #ボートレース予想 約92万
BASE_TAGS = ["競艇予想", "競艇", "ボートレース", "競艇予想屋", "ボートレース予想"]


def make_tags(kind: str, race: dict) -> str:
    tags = BASE_TAGS + [f"{race['venue']}競艇"]
    if race.get("grade") in ("SG", "G1"):
        tags.append(race["grade"])
    tags.append("事前予想" if kind == "pre" else "展示後予想")
    tags.append("艇眼")
    return " ".join("#" + t for t in tags)


def make_x_roundup(hd: str, races: list[dict]) -> str:
    """朝のまとめ投稿。入りきる分だけレースを並べる。"""
    date = f"{int(hd[4:6])}/{int(hd[6:8])}"
    head = [f"☀️【艇眼】{date} 本日の事前予想 全{len(races)}R", ""]
    tail = ["", f"🎯各レース本命3点＋穴3点｜{config.PRICE_PRE}円", "👇noteで公開中",
            "（ここにnoteのURL）", "#競艇予想 #ボートレース"]
    body, rest = [], 0
    for i, r in enumerate(races):
        line = f"🚤{r['deadline']} {r.get('grade', '')}{r['venue']}{r['rno']}R"
        cand = head + body + [line] + ([f"ほか{len(races) - i - 1}R"] if i < len(races) - 1 else []) + tail
        if x_len("\n".join(cand).replace("（ここにnoteのURL）", "https://note.com/x")) > 280:
            rest = len(races) - i
            break
        body.append(line)
    if rest:
        body.append(f"ほか{rest}R")
    return "\n".join(head + body + tail)
