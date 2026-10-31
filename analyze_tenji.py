"""集めた直前情報（tenji_data）と競走成績を突き合わせて、展示の効き目を検証する。

  python analyze_tenji.py --tenji tenji_wt/tenji_data

調べること:
  1) 1コースの展示F → 本番の1コース1着率・本番ST（「逃げ失敗75%」は本当か）
  2) 展示STと本番STの関係（展示が早い艇は本番も早いか）
  3) 隊形: 内凹み（カド先行）→ 4コースの1着率、中凹み（2コースだけ遅れ）→ 3コースの1着率
  4) カドの伸び（展示タイムが1・2コースより0.13秒以上速い）
  5) 現行の展示後予想とルール版（隊形・展示Fも使う）の比較（1号艇A1/A2のレース・6点）
"""
import argparse
import gzip
import json
import os
from collections import defaultdict
from datetime import date

from kyotei import history, notify, rules, scoring


def load_days(folder: str):
    for name in sorted(os.listdir(folder)):
        if name.endswith(".json.gz"):
            yield date(int(name[:4]), int(name[4:6]), int(name[6:8])), json.load(gzip.open(os.path.join(folder, name), "rt"))


def to_before(t: dict) -> dict:
    start = {int(c): {"boat": v[0], "st": v[1], "flying": v[2]} for c, v in t["st"].items()}
    boats = {int(w): {"tenji_time": x, "tilt": None, "parts": []} for w, x in t["tenji"].items()}
    return {"boats": boats, "start": start, "weather": {}, "ready": True}


class Rate:
    def __init__(self):
        self.n = self.k = 0
        self.sum = 0.0
        self.m = 0

    def add(self, hit: bool, val: float | None = None):
        self.n += 1
        self.k += bool(hit)
        if val is not None:
            self.sum += val
            self.m += 1

    def s(self, label="1着"):
        if not self.n:
            return "対象なし"
        out = f"{self.n:,}R {label}{self.k / self.n * 100:.1f}%"
        if self.m:
            out += f" 本番ST平均{self.sum / self.m:.3f}"
        return out


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sxy / (sx * sy) if sx and sy else None


class Bet:
    def __init__(self):
        self.n = self.hit = self.ret = self.h_ret = self.a_ret = 0

    def add(self, bets, res):
        self.n += 1
        got = 0
        for c, pay, _ in res["trifecta"]:
            if c in bets["本命"]:
                self.h_ret += pay
                got += pay
            if c in bets["穴"]:
                self.a_ret += pay
                got += pay
        if got:
            self.hit += 1
            self.ret += got

    def s(self):
        if not self.n:
            return "対象なし"
        return (f"{self.n:,}R 的中{self.hit / self.n * 100:.1f}% 回収{self.ret / (self.n * 600) * 100:.1f}%"
                f"（本命{self.h_ret / (self.n * 300) * 100:.1f}% 穴{self.a_ret / (self.n * 300) * 100:.1f}%）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenji", default="tenji_data")
    ap.add_argument("--cache", default="history_cache")
    a = ap.parse_args()

    f1, nf1 = Rate(), Rate()          # 1コース展示F / それ以外 → 1コース1着
    f1_man, nf1_man = Rate(), Rate()  # 同・万舟（3連単1万円以上）
    f1_strong = Rate()                # 1コース展示F かつ 展示タイム1〜2位
    ex, ho = [], []                   # 展示ST・本番ST（Fでない艇）
    fl_st, ok_st = [], []             # 展示Fだった艇／そうでない艇の本番ST
    uchi, uchi4, naka3, base4, base3 = Rate(), Rate(), Rate(), Rate(), Rate()
    nobi4, both4 = Rate(), Rate()
    cur, rule = Bet(), Bet()
    cur_sig, rule_sig = Bet(), Bet()   # 何かサインが出たレースだけ
    days = races = 0
    first = last = None

    for d, data in load_days(a.tenji):
        if not data:
            continue
        b_txt = history.fetch_text("B", d, a.cache, 1.0)
        k_txt = history.fetch_text("K", d, a.cache, 1.0)
        if not b_txt or not k_txt:
            continue
        b_map = {(r["jcd"], r["rno"]): r for r in history.parse_b(b_txt)}
        k_map = history.parse_k(k_txt)
        days += 1
        first, last = first or d, d
        for key, t in data.items():
            jcd, rno = key.split("-")
            res = k_map.get((jcd, int(rno)))
            race = b_map.get((jcd, int(rno)))
            if not res or not race or res["cancelled"] or not res["trifecta"] or len(res["order"]) < 3:
                continue
            before = to_before(t)
            st = before["start"]
            if len(st) < 6 or any(v["st"] is None for v in st.values()):
                continue
            races += 1
            win = res["order"].get(1)
            course_of = {w: c for w, c in res["course"].items()}
            boat_at = {c: w for w, c in course_of.items()}
            man = max(p for _, p, _ in res["trifecta"]) >= 10000

            # 1) 1コースの展示F（展示で1コースにいた艇）
            b1 = st[1]["boat"]
            one_real = boat_at.get(1)
            hit1 = win == one_real
            ranks = scoring._tenji_ranks(before)
            if st[1]["flying"]:
                f1.add(hit1, res["st"].get(one_real))
                f1_man.add(man, None)
                if ranks.get(b1, 9) <= 2:
                    f1_strong.add(hit1)
            else:
                nf1.add(hit1, res["st"].get(one_real))
                nf1_man.add(man, None)

            # 2) 展示STと本番ST
            for c, v in st.items():
                w = v["boat"]
                real = res["st"].get(w)
                if real is None or real < 0:
                    continue
                if v["flying"]:
                    fl_st.append(real)
                else:
                    ok_st.append(real)
                    ex.append(v["st"])
                    ho.append(real)

            # 3)4) 隊形と伸び（展示の進入で見る）
            sig = rules.signals(race["boats"], before)
            w4 = boat_at.get(4)
            w3 = boat_at.get(3)
            base4.add(win == w4)
            base3.add(win == w3)
            if sig["uchi_hekomi"]:
                uchi.add(hit1)
                uchi4.add(win == w4)
            if sig["naka_hekomi"]:
                naka3.add(win == w3)
            if sig["nobi"]:
                nobi4.add(win == w4)
            if sig["uchi_hekomi"] and sig["nobi"]:
                both4.add(win == w4)

            # 5) 予想の比較（1号艇A1/A2のレース）
            if race["boats"][1]["class"] in ("A1", "A2"):
                cb = scoring.post_bets(race["boats"], before)
                rb = rules.make_bets(race, before)
                cur.add(cb, res)
                rule.add(rb, res)
                if sig["uchi_hekomi"] or sig["naka_hekomi"] or sig["nobi"] or sig["tenji_f"]:
                    cur_sig.add(cb, res)
                    rule_sig.add(rb, res)

    avg = lambda xs: sum(xs) / len(xs) if xs else float("nan")
    r = corr(ex, ho)
    out = [f"🔬 展示データの検証 {first}〜{last}（{days}日・{races:,}レース）", "",
           "■1) 1コースの展示F",
           f"  展示Fあり: {f1.s()}",
           f"  展示Fなし: {nf1.s()}",
           f"  展示Fあり＋展示タイム1〜2位: {f1_strong.s()}",
           f"  万舟率 展示Fあり {f1_man.s('万舟')} ／ なし {nf1_man.s('万舟')}",
           "  ※レポートの主張は「展示Fありの逃げ成功24.6%」",
           "",
           "■2) 展示STと本番ST",
           f"  相関係数 {r:.3f}（{len(ex):,}艇）" if r is not None else "  相関: データ不足",
           f"  本番ST平均 展示Fだった艇 {avg(fl_st):.3f}（{len(fl_st):,}艇）／ それ以外 {avg(ok_st):.3f}",
           "",
           "■3) 隊形",
           f"  内凹み（カドが1〜3コース平均より0.07秒以上先行）: 1コース{uchi.s()}／4コース{uchi4.s()}",
           f"  中凹み（2コースだけ0.07秒以上遅れ）: 3コース{naka3.s()}",
           f"  参考・全レース: 4コース{base4.s()}／3コース{base3.s()}",
           "",
           "■4) カドの伸び（展示タイムが1・2コースより0.13秒以上速い）",
           f"  4コース{nobi4.s()}",
           f"  内凹み＋伸びの両方: 4コース{both4.s()}",
           "",
           "■5) 展示後予想の比較（1号艇A1/A2・6点・各点100円）",
           f"  現行: {cur.s()}",
           f"  ルール版: {rule.s()}",
           f"  サイン（内凹み・中凹み・伸び・展示F）が出たレースだけ: 現行 {cur_sig.s()}",
           f"                                                ルール版 {rule_sig.s()}",
           ]
    text = "\n".join(out)
    print(text)
    os.makedirs("reports", exist_ok=True)
    open("reports/tenji_report.txt", "w").write(text + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("```\n" + text + "\n```\n")
    if os.environ.get("NOTIFY") == "1":
        notify.send(text)


if __name__ == "__main__":
    main()
