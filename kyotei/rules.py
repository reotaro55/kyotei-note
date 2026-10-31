"""記事ルール版のスコア（まーくんのnote3本を参考にした、手で決めた点数）。

元の scoring.py には手を入れず、config.USE_RULES が True のときだけ本番で使う。
backtest.py は現行版とこのルール版を同じレースで比べる。

参考にした考え方（数値の多くは出典不明なので、バックテストと成績ログで検証する前提）:
  1) 場の差: 1コースの1着率は場によって約44%〜63%と大きく違う
  2) 展示STは「数字そのもの」ではなく「隊形（6艇の相対位置）」を見る
     - 内凹み: 4カドが1〜3コースより先行 → 4の捲り。外隣（5）が連動しやすい
     - 中凹み: 2コースだけ遅れる → 3の捲り差し。差された1が残りやすい
  3) カドの展示タイムが1・2号艇より0.13秒以上速い → 捲りの裏付け
  4) 1号艇の展示F: 本番で慎重になりやすい（弱めのマイナス。75%で負けるという話は根拠不足）
  5) スジ: 捲り → 外隣が2着、捲り差し → 差された内側が2着、2の差し → 1が残る
"""
from . import scoring

# 1コース1着率（%）。記事に出ていた値。出ていない場は全国平均。
# ※公式の場データで照合してから値を更新すること（週次リサーチで取得している）
NATIONAL_IN1 = 55.9
VENUE_IN1 = {
    "01": 49.7,  # 桐生
    "02": 43.8,  # 戸田
    "03": 46.0,  # 江戸川（記事では44〜48%）
    "04": 45.1,  # 平和島
    "05": 52.9,  # 多摩川
    "08": 57.8,  # 常滑
    "09": 57.4,  # 津
    "11": 51.9,  # びわこ
    "12": 61.1,  # 住之江
    "13": 60.8,  # 尼崎
    "14": 48.1,  # 鳴門
    "18": 62.6,  # 徳山
    "19": 61.4,  # 下関
    "20": 59.5,  # 若松
    "21": 60.1,  # 芦屋
    "22": 57.5,  # 福岡
    "24": 61.3,  # 大村
}
# カドの捲りが多い場（4コースに少し上乗せ）
KADO_VENUES = {"01", "02", "14"}  # 桐生・戸田・鳴門

# ---- 重み（strength の単位は「全国勝率1点＝10」） ----
VENUE_W = 0.6        # 1コース1着率が全国平均より1%低いごとに1コースから引く点
KADO_BONUS = 3.0     # カド捲りが多い場の4コース
UCHI_HEKOMI_ST = 0.07   # 半艇身 ≒ 0.07秒
NOBI_DIFF = 0.13        # 展示タイム差 0.13秒 ≒ スリット後に1艇身
W_UCHI_HEKOMI = 8.0  # 内凹み（4カド先行）: 4に＋、1に−
W_NOBI = 6.0         # カドが1・2号艇より0.13秒以上速い: 4に＋、1に−
W_BOTH = 6.0         # 内凹み＋伸びの両方がそろったときの上乗せ
W_NAKA_HEKOMI = 6.0  # 中凹み: 3に＋
W_TENJI_F = 4.0      # 1コースの展示F: 1に−


def venue_in1(jcd: str | None) -> float:
    return VENUE_IN1.get(jcd or "", NATIONAL_IN1)


def _courses(boats: dict, before: dict | None) -> dict[int, int]:
    c = scoring._courses(before)
    return {w: c.get(w, w) for w in boats}


def signals(boats: dict, before: dict | None) -> dict:
    """展示から読み取れる展開のサイン。展示がなければ全部 False。"""
    sig = {"uchi_hekomi": False, "nobi": False, "naka_hekomi": False, "tenji_f": False,
           "kado": None, "notes": []}
    if not before:
        return sig
    start = before.get("start") or {}
    by_course = {c: v for c, v in start.items() if v.get("boat")}
    course_of = _courses(boats, before)
    boat_at = {c: w for w, c in course_of.items()}
    kado = boat_at.get(4)
    sig["kado"] = kado
    st = {c: v.get("st") for c, v in by_course.items()}

    # 1コースの展示F
    if by_course.get(1, {}).get("flying"):
        sig["tenji_f"] = True
        sig["notes"].append("1コースが展示でF")

    # 隊形（展示STがあるときだけ。成績ファイルの過去データには無い）
    if all(st.get(c) is not None for c in (1, 2, 3, 4)):
        inner_avg = (st[1] + st[2] + st[3]) / 3
        if inner_avg - st[4] >= UCHI_HEKOMI_ST - 1e-9:
            sig["uchi_hekomi"] = True
            sig["notes"].append(f"内凹み（カドが内より{inner_avg - st[4]:.2f}秒先行）")
        if st[2] - st[1] >= UCHI_HEKOMI_ST - 1e-9 and st[2] - st[3] >= UCHI_HEKOMI_ST - 1e-9:
            sig["naka_hekomi"] = True
            sig["notes"].append("中凹み（2コースだけ遅れ）")

    # 伸び（展示タイム）
    t = {w: b.get("tenji_time") for w, b in (before.get("boats") or {}).items()}
    b1, b2 = boat_at.get(1), boat_at.get(2)
    if kado and t.get(kado) and t.get(b1) and t.get(b2):
        diff = min(t[b1], t[b2]) - t[kado]
        if diff >= NOBI_DIFF - 1e-9:
            sig["nobi"] = True
            sig["notes"].append(f"カド{kado}号艇の展示タイムが1・2コースより{diff:.2f}秒速い")
    return sig


def strength(b: dict, course: int, jcd: str | None, tenji_rank: int | None, sig: dict) -> float:
    s = scoring.strength(b, course, tenji_rank)
    if course == 1:
        s -= (NATIONAL_IN1 - venue_in1(jcd)) * VENUE_W
        if sig["tenji_f"]:
            s -= W_TENJI_F
        if sig["uchi_hekomi"]:
            s -= W_UCHI_HEKOMI
        if sig["nobi"]:
            s -= W_NOBI / 2
    if course == 4:
        if jcd in KADO_VENUES:
            s += KADO_BONUS
        if sig["uchi_hekomi"]:
            s += W_UCHI_HEKOMI
        if sig["nobi"]:
            s += W_NOBI
        if sig["uchi_hekomi"] and sig["nobi"]:
            s += W_BOTH
    if course == 3 and sig["naka_hekomi"]:
        s += W_NAKA_HEKOMI
    return s


def ranking(race: dict, before: dict | None = None) -> list[int]:
    boats = race["boats"]
    ranks = scoring._tenji_ranks(before) if before else {}
    course = _courses(boats, before)
    sig = signals(boats, before)
    return sorted(boats, key=lambda w: strength(boats[w], course[w], race.get("jcd"), ranks.get(w), sig),
                  reverse=True)


def make_bets(race: dict, before: dict | None = None, p_form_w: float = 0.0) -> dict[str, list[str]]:
    """本命3点は現行と同じ組み方（頭だけルール版の順位）。穴3点をスジで組む。"""
    boats = race["boats"]
    ranks = scoring._tenji_ranks(before) if before else {}
    course = _courses(boats, before)
    boat_at = {c: w for w, c in course.items()}
    sig = signals(boats, before)
    saved = scoring.P_FORM_W
    scoring.P_FORM_W = p_form_w
    try:
        ps = {w: scoring.partner_score(boats[w], course[w], ranks.get(w)) for w in boats}
    finally:
        scoring.P_FORM_W = saved
    w = ranking(race, before)
    a, h = w[0], w[1]
    pr = sorted((x for x in boats if x != a), key=lambda x: ps[x], reverse=True)
    honmei = [f"{a}-{pr[0]}-{pr[1]}", f"{a}-{pr[1]}-{pr[0]}", f"{a}-{pr[0]}-{pr[2]}"]

    hc = course[h]
    rest = [x for x in sorted(boats, key=lambda x: ps[x], reverse=True) if x not in (a, h)]
    if hc >= 4 and (sig["uchi_hekomi"] or sig["nobi"] or hc > 4 or race.get("jcd") in KADO_VENUES):
        # 捲り: 外隣が連動
        n = boat_at.get(hc + 1)
        if n and n != a:
            others = [x for x in rest if x != n]
            ana = [f"{h}-{n}-{a}", f"{h}-{n}-{others[0]}", f"{h}-{a}-{n}"]
        else:
            ana = [f"{h}-{a}-{rest[0]}", f"{h}-{rest[0]}-{a}", f"{h}-{a}-{rest[1]}"]
    elif hc >= 3:
        # 捲り差し: 差された内側（1・2コース）が残る
        i1, i2 = boat_at.get(1), boat_at.get(2)
        inner = [x for x in (i1, i2) if x and x != h]
        if len(inner) == 2:
            third = next(x for x in rest + [a] if x not in inner and x != h)
            ana = [f"{h}-{inner[0]}-{inner[1]}", f"{h}-{inner[1]}-{inner[0]}", f"{h}-{inner[0]}-{third}"]
        else:
            ana = [f"{h}-{a}-{rest[0]}", f"{h}-{rest[0]}-{a}", f"{h}-{a}-{rest[1]}"]
    else:
        # 2の差し（または1が穴側）: 1が残る形は現行と同じ
        ana = [f"{h}-{a}-{rest[0]}", f"{h}-{rest[0]}-{a}", f"{h}-{a}-{rest[1]}"]
    # 重複を除いて3点にそろえる
    seen, out = set(honmei), []
    for t in ana + [f"{h}-{a}-{x}" for x in rest] + [f"{h}-{x}-{a}" for x in rest]:
        if t not in seen and len(set(t.split("-"))) == 3:
            seen.add(t)
            out.append(t)
        if len(out) == 3:
            break
    return {"本命": honmei, "穴": out}


def danger(race: dict) -> tuple[float, list[str]]:
    """1号艇の危うさ（0〜100）。穴狙い枠のレース選び用。出走表だけで出す。"""
    boats = race["boats"]
    b1 = boats[1]
    notes, s = [], 0.0
    gap = NATIONAL_IN1 - venue_in1(race.get("jcd"))
    if gap > 0:
        s += gap * 2
        notes.append(f"イン1着率が低い場（{venue_in1(race.get('jcd')):.1f}%）")
    top = max(b["win_rate"] for w, b in boats.items() if w != 1)
    if top > b1["win_rate"]:
        s += min((top - b1["win_rate"]) * 15, 30)
        notes.append(f"1号艇より勝率の高い選手がいる（+{top - b1['win_rate']:.2f}）")
    if b1["motor2"] < 30:
        s += min((30 - b1["motor2"]) * 1.0, 15)
        notes.append(f"1号艇のモーター2連率{b1['motor2']:.1f}%")
    kado = boats.get(4)
    if kado and kado["win_rate"] >= 6.5 and kado["win_rate"] >= b1["win_rate"] - 0.3:
        s += 10
        notes.append(f"4号艇（カド）が勝率{kado['win_rate']:.2f}")
    if race.get("jcd") in KADO_VENUES and kado and kado["motor2"] >= 40:
        s += 5
    return round(min(s, 100), 1), notes
