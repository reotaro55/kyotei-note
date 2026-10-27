"""1号艇の信頼度スコアと買い目（3連単・1着1号艇固定）を作る。

点数の付け方はアニキの感覚に合わせて自由に調整してOK。
"""
from itertools import permutations

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


def make_bets(boats: dict, n_second: int, n_third: int, before: dict | None = None) -> list[str]:
    """1-{2着候補}-{3着候補} の3連単。"""
    ranks = _tenji_ranks(before) if before else {}
    others = [b for w, b in boats.items() if w != 1]
    others.sort(key=lambda b: _partner_score(b, ranks.get(b["waku"])), reverse=True)
    picks = [b["waku"] for b in others]
    seconds, thirds = picks[:n_second], picks[:n_third]
    bets = []
    for a, c in permutations(thirds, 2):
        if a in seconds:
            bets.append(f"1-{a}-{c}")
    return bets


def is_hit(bets: list[str], trifecta: str) -> bool:
    return trifecta in bets


def tenji_ranks(before: dict) -> dict[int, int]:
    return _tenji_ranks(before)


# 便利関数
def pre_bets(boats):
    return make_bets(boats, config.PRE_SECOND, config.PRE_THIRD)


def post_bets(boats, before):
    return make_bets(boats, config.POST_SECOND, config.POST_THIRD, before)
