"""1号艇の信頼度スコア（レースの厳選用）と、買い目（本命3点＋穴3点）を作る。

点数の付け方はアニキの感覚に合わせて自由に調整してOK。
"""
from . import config

CLASS_BONUS = {"A1": 15, "A2": 8, "B1": 0, "B2": -10}


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def pre_score(boats: dict) -> tuple[float, list[str]]:
    """出走表だけで1号艇の信頼度を0〜100点で出す。理由のメモも返す。"""
    b1 = boats.get(1)
    if not b1 or len(boats) < 6:
        return 0.0, ["出走表が揃っていない"]
    notes = []
    s = 0.0
    s += _clip((b1["win_rate"] - 5.0) * 10, 0, 30)
    if b1["local_win_rate"]:
        s += _clip((b1["local_win_rate"] - 5.0) * 6, 0, 15)
    s += CLASS_BONUS.get(b1["class"], 0)
    s += _clip((b1["motor2"] - 30) * 0.5, -5, 10)
    if b1["avg_st"]:
        s += _clip((0.18 - b1["avg_st"]) * 100, -5, 10)
    others = [b["win_rate"] for w, b in boats.items() if w != 1]
    gap = b1["win_rate"] - max(others)
    s += _clip(gap * 8, -10, 20)
    if b1["F"]:
        s -= 5
        notes.append(f"1号艇はF{b1['F']}持ち")
    notes.append(f"1号艇 全国勝率{b1['win_rate']:.2f}・{b1['class']}")
    notes.append(f"他艇の最高勝率との差 {gap:+.2f}")
    return round(_clip(s, 0, 100), 1), notes


def _partner_score(b: dict, tenji_rank: int | None = None) -> float:
    s = b["win_rate"] * 10 + b["motor2"] * 0.3
    s += {2: 6, 3: 4, 4: 2}.get(b["waku"], 0)       # 内枠ほど2・3着に残りやすい
    s += CLASS_BONUS.get(b["class"], 0) * 0.5
    if tenji_rank:
        s += {1: 8, 2: 5, 3: 2, 5: -3, 6: -5}.get(tenji_rank, 0)
    return s


def _tenji_ranks(before: dict) -> dict[int, int]:
    times = {w: b["tenji_time"] for w, b in before["boats"].items() if b["tenji_time"]}
    order = sorted(times, key=lambda w: times[w])
    return {w: i + 1 for i, w in enumerate(order)}


def post_score(boats: dict, before: dict) -> tuple[float, list[str], bool]:
    """展示後スコア。3つ目の戻り値は「見送り推奨」かどうか。"""
    s, notes = pre_score(boats)
    skip = False
    ranks = _tenji_ranks(before)
    r1 = ranks.get(1)
    if r1:
        s += {1: 10, 2: 5, 3: 0, 4: -4, 5: -10, 6: -15}.get(r1, 0)
        notes.append(f"1号艇の展示タイム {r1}位")
        if r1 >= 5:
            skip = True
    course1 = before["start"].get(1, {})
    if course1.get("boat") not in (None, 1):
        s -= 20
        skip = True
        notes.append(f"スタート展示で{course1.get('boat')}号艇がインを取った")
    st1 = next((v["st"] for v in before["start"].values() if v.get("boat") == 1), None)
    if st1 is not None:
        if st1 <= 0.10:
            s += 5
        elif st1 >= 0.25:
            s -= 5
        notes.append(f"1号艇の展示ST {st1:.2f}")
    return round(_clip(s, 0, 100), 1), notes, skip


COURSE_BONUS = {1: 25, 2: 8, 3: 6, 4: 4, 5: 0, 6: -3}  # インほど1着を取りやすい


def _courses(before: dict | None) -> dict[int, int]:
    """艇番 → 進入コース。展示前は枠なり。"""
    if before and before.get("start"):
        m = {v["boat"]: c for c, v in before["start"].items() if v.get("boat")}
        if len(m) >= 5:
            return m
    return {}


# 今節の得点率と勝負駆けの重み（バックテストで決める。0なら使わない）
FORM_W = 0.0   # 得点率が平均(5.5)より1高いごとに足す点
KAKE_W = 0.0   # 予選最終日でボーダー付近（勝負駆け）の選手に足す点


def strength(b: dict, course: int, tenji_rank: int | None = None) -> float:
    """1着になる力のざっくりした点数。"""
    s = b["win_rate"] * 10 + (b.get("local_win_rate") or b["win_rate"]) * 3
    if FORM_W and b.get("form") is not None and b.get("kon_n", 0) >= 2:
        s += FORM_W * (b["form"] - 5.5)
    if KAKE_W and b.get("kakeru"):
        s += KAKE_W
    s += b["motor2"] * 0.3 + CLASS_BONUS.get(b["class"], 0)
    s += COURSE_BONUS.get(course, 0)
    if tenji_rank:
        s += {1: 8, 2: 5, 3: 2, 5: -3, 6: -5}.get(tenji_rank, 0)
    return s


def ranking(boats: dict, before: dict | None = None) -> list[int]:
    """1着になる力の順に艇番を並べる。"""
    ranks = _tenji_ranks(before) if before else {}
    courses = _courses(before)
    order = sorted(
        boats.values(),
        key=lambda b: strength(b, courses.get(b["waku"], b["waku"]), ranks.get(b["waku"])),
        reverse=True,
    )
    return [b["waku"] for b in order]


# 2・3着の相手選びに使う重み（バックテストで決める。0なら頭と同じ強さ順）
P_FORM_W = 0.0   # 今節の得点率
P_KAKE_W = 0.0   # 勝負駆け


def partner_score(b: dict, course: int, tenji_rank: int | None = None) -> float:
    """2・3着に残る力。頭の強さに、今節の調子と勝負駆けを足す。"""
    s = strength(b, course, tenji_rank)
    if P_FORM_W and b.get("form") is not None and b.get("kon_n", 0) >= 2:
        s += P_FORM_W * (b["form"] - 5.5)
    if P_KAKE_W and b.get("kakeru"):
        s += P_KAKE_W
    return s


def make_bets(boats: dict, before: dict | None = None) -> dict[str, list[str]]:
    """本命3点＋穴3点の3連単。

    頭（1着）は strength の順で、本命=一番手、穴=二番手。
    2・3着の相手は partner_score の順で選ぶ。
    """
    ranks = _tenji_ranks(before) if before else {}
    courses = _courses(before)
    c = lambda w: courses.get(w, w)
    w = ranking(boats, before)
    a, h = w[0], w[1]
    pr = sorted((x for x in boats if x != a),
                key=lambda x: partner_score(boats[x], c(x), ranks.get(x)), reverse=True)
    p1, p2, p3 = pr[0], pr[1], pr[2]
    qr = [x for x in sorted(boats, key=lambda x: partner_score(boats[x], c(x), ranks.get(x)), reverse=True)
          if x not in (a, h)]
    q1, q2 = qr[0], qr[1]
    honmei = [f"{a}-{p1}-{p2}", f"{a}-{p2}-{p1}", f"{a}-{p1}-{p3}"]
    ana = [f"{h}-{a}-{q1}", f"{h}-{q1}-{a}", f"{h}-{a}-{q2}"]
    return {"本命": honmei, "穴": ana}


def flat(bets: dict[str, list[str]]) -> list[str]:
    return [t for v in bets.values() for t in v]


def is_hit(bets, trifecta: str) -> bool:
    return trifecta in (flat(bets) if isinstance(bets, dict) else bets)


def tenji_ranks(before: dict) -> dict[int, int]:
    return _tenji_ranks(before)


# 便利関数
def pre_bets(boats):
    return make_bets(boats)


def post_bets(boats, before):
    return make_bets(boats, before)
