"""バックテスト: 今の厳選ルールと買い目（本命3点＋穴3点）が、過去に通用していたかを調べる。

  python backtest.py --months 12

公式の過去データ（番組表・競走成績）を使い、毎日の「厳選 → 買い目」を本番と同じ
ロジックで再現して、的中率・回収率を集計する。各点100円で計算。

本番との違い（データの都合）:
  - 番組表に平均STとF数が無いので、事前スコアのST・F補正は使っていない
  - 展示ST（スタート展示）は成績ファイルに無いので、展示後スコアのST補正は使っていない
  - 展示進入の代わりに本番の進入を使っている（多くの場合同じ）
"""
import argparse
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from kyotei import config, history, notify, rules, scoring

PREFILTER = ("A1", "A2")


def daily_plan(b_races: list[dict]) -> tuple[list, list]:
    """planner.build_plan と同じ選び方を、番組表データで再現する。"""
    first = defaultdict(lambda: "99:99")
    for r in b_races:
        if r["rno"] == 1:
            first[r["jcd"]] = r["deadline"]
    pre, post = [], []
    for r in b_races:
        if r["boats"][1]["class"] not in PREFILTER:
            continue
        nighter = first[r["jcd"]] >= "14:00"
        post_race = nighter or r["rno"] in config.POST_ROUNDS_DAY
        if not post_race and r["deadline"] > config.PRE_DEADLINE_LIMIT:
            continue
        score, _ = scoring.pre_score(r["boats"])
        item = dict(r, score=score)
        (post if post_race else pre).append(item)
    pre.sort(key=lambda x: x["score"], reverse=True)
    chosen = [x for x in pre if x["score"] >= config.PRE_MIN_SCORE][: config.PRE_MAX]
    if len(chosen) < config.PRE_MIN:
        chosen = pre[: config.PRE_MIN]
    post.sort(key=lambda x: x["score"], reverse=True)
    post_chosen = [x for x in post if x["score"] >= config.POST_MIN_SCORE][: config.POST_MAX]
    return chosen, post_chosen


class Stat:
    def __init__(self):
        self.n = self.hit = self.ret = 0
        self.h_hit = self.h_ret = self.a_hit = self.a_ret = 0
        self.first = defaultdict(int)  # 1着の艇番
        self.head_ok = 0               # 本命の1着艇が実際に1着
        self.ana_head_ok = 0

    def add(self, bets, res):
        self.n += 1
        win = res["order"].get(1)
        self.first[win] += 1
        if int(bets["本命"][0][0]) == win:
            self.head_ok += 1
        if int(bets["穴"][0][0]) == win:
            self.ana_head_ok += 1
        for combo, pay, _ in res["trifecta"]:
            if combo in bets["本命"]:
                self.h_hit += 1
                self.h_ret += pay
            if combo in bets["穴"]:
                self.a_hit += 1
                self.a_ret += pay
        got = [pay for combo, pay, _ in res["trifecta"] if combo in scoring.flat(bets)]
        if got:
            self.hit += 1
            self.ret += sum(got)

    def pct(self, a, b):
        return f"{a / b * 100:.1f}%" if b else "-"

    def lines(self, label):
        if not self.n:
            return [f"■{label}: 対象なし"]
        inv = self.n * 600
        return [
            f"■{label}（{self.n:,}レース）",
            f"  6点合計  的中率 {self.pct(self.hit, self.n)}  回収率 {self.pct(self.ret, inv)}",
            f"  本命3点  的中率 {self.pct(self.h_hit, self.n)}  回収率 {self.pct(self.h_ret, self.n * 300)}",
            f"  穴3点    的中率 {self.pct(self.a_hit, self.n)}  回収率 {self.pct(self.a_ret, self.n * 300)}",
            f"  本命の頭が1着 {self.pct(self.head_ok, self.n)} ／ 穴の頭が1着 {self.pct(self.ana_head_ok, self.n)}",
            f"  1号艇の1着率 {self.pct(self.first[1], self.n)}",
        ]


# 買い目の別パターン（どれも6点）。w = 強い順の艇番
VARIANTS = {
    "現行(本命3+穴3)": lambda w: [f"{w[0]}-{w[1]}-{w[2]}", f"{w[0]}-{w[2]}-{w[1]}", f"{w[0]}-{w[1]}-{w[3]}",
                               f"{w[1]}-{w[0]}-{w[2]}", f"{w[1]}-{w[2]}-{w[0]}", f"{w[1]}-{w[0]}-{w[3]}"],
    "本命6点(頭固定・相手3艇)": lambda w: [f"{w[0]}-{a}-{b}" for a in w[1:4] for b in w[1:4] if a != b],
    "本命4+穴2": lambda w: [f"{w[0]}-{w[1]}-{w[2]}", f"{w[0]}-{w[2]}-{w[1]}", f"{w[0]}-{w[1]}-{w[3]}",
                          f"{w[0]}-{w[2]}-{w[3]}", f"{w[1]}-{w[0]}-{w[2]}", f"{w[2]}-{w[0]}-{w[1]}"],
    "本命3+頭崩れ3(2着に本命)": lambda w: [f"{w[0]}-{w[1]}-{w[2]}", f"{w[0]}-{w[2]}-{w[1]}", f"{w[0]}-{w[1]}-{w[3]}",
                                    f"{w[1]}-{w[0]}-{w[2]}", f"{w[2]}-{w[0]}-{w[1]}", f"{w[3]}-{w[0]}-{w[1]}"],
    "本命3+本命消し3(高配当)": lambda w: [f"{w[0]}-{w[1]}-{w[2]}", f"{w[0]}-{w[2]}-{w[1]}", f"{w[0]}-{w[1]}-{w[3]}",
                                   f"{w[1]}-{w[2]}-{w[3]}", f"{w[1]}-{w[3]}-{w[2]}", f"{w[2]}-{w[1]}-{w[3]}"],
}


class VStat:
    def __init__(self):
        self.n = self.hit = self.ret = 0

    def add(self, combos, res):
        self.n += 1
        got = [pay for c, pay, _ in res["trifecta"] if c in combos]
        if got:
            self.hit += 1
            self.ret += sum(got)

    def line(self, name):
        if not self.n:
            return f"  {name}: -"
        return f"  {name}: 的中{self.hit / self.n * 100:.1f}% 回収{self.ret / (self.n * 600) * 100:.1f}%"


PARTNER_VARIANTS = [(0, 0), (2, 0), (4, 0), (8, 0), (0, 5), (0, 10), (2, 5), (4, 5), (4, 10), (8, 10)]


def mark_kakeru(b_races: list[dict], series_len: dict):
    """予選最終日に、得点率がボーダー(18位)付近の選手へ kakeru=True を付ける。"""
    by_venue = defaultdict(list)
    for r in b_races:
        by_venue[r["jcd"]].append(r)
    for jcd, races in by_venue.items():
        day, n = races[0].get("day"), series_len.get(jcd)
        if not day or not n or n < 4 or day != n - 2:
            continue
        forms = {}
        for r in races:
            for b in r["boats"].values():
                if b.get("form") is not None:
                    forms[b["racer_id"]] = b["form"]
        order = sorted(forms, key=lambda k: forms[k], reverse=True)
        band = set(order[12:24])  # 13〜24位
        for r in races:
            if "予選" not in r.get("race_name", ""):
                continue
            for b in r["boats"].values():
                b["kakeru"] = b["racer_id"] in band


def strength_report(samples: list) -> list[str]:
    out = ["", "■2・3着の相手選びの比較（得点率の重み, 勝負駆けの重み）",
           "  ※「相手的中」= 本命の頭が1着だったとき、本命3点が当たった割合"]
    kakeru_races = sum(1 for _, boats, _, _ in samples if any(b.get("kakeru") for b in boats.values()))
    out.append(f"  ※勝負駆けの選手がいたレース: {kakeru_races:,}")
    base = (scoring.P_FORM_W, scoring.P_KAKE_W)
    for fw, kw in PARTNER_VARIANTS:
        scoring.P_FORM_W, scoring.P_KAKE_W = fw, kw
        row = []
        for kind in ("pre", "post"):
            n = head = hm = hit = ret = 0
            for k, boats, before, res in samples:
                if k != kind:
                    continue
                bets = scoring.make_bets(boats, before)
                n += 1
                if int(bets["本命"][0][0]) == res["order"].get(1):
                    head += 1
                    if any(c in bets["本命"] for c, _, _ in res["trifecta"]):
                        hm += 1
                got = [p for c, p, _ in res["trifecta"] if c in scoring.flat(bets)]
                if got:
                    hit += 1
                    ret += sum(got)
            row.append(f"{'事前' if kind == 'pre' else '展示後'} 相手的中{hm / head * 100:.1f}% 的中{hit / n * 100:.1f}% 回収{ret / (n * 600) * 100:.1f}%" if n and head else "-")
        out.append(f"  ({fw:>2},{kw:>2}) " + " ｜ ".join(row))
    scoring.P_FORM_W, scoring.P_KAKE_W = base
    return out


def bucket(score):
    return "75点以上" if score >= 75 else "65〜75点" if score >= 65 else "55〜65点" if score >= 55 else "55点未満"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--cache", default="history_cache")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--start", help="YYYY-MM-DD（指定時は --months より優先）")
    ap.add_argument("--end", help="YYYY-MM-DD")
    a = ap.parse_args()

    end = (date.fromisoformat(a.end) if a.end
           else datetime.now(ZoneInfo("Asia/Tokyo")).date() - timedelta(days=1))
    start = (date.fromisoformat(a.start) if a.start
             else end - timedelta(days=round(a.months * 30.4)))
    pre_s, post_s = Stat(), Stat()
    pre_b = defaultdict(Stat)
    var = {k: defaultdict(VStat) for k in ("pre", "post", "all")}
    month = defaultdict(lambda: [0, 0])  # 月 → [投資, 払戻]（事前＋展示後）
    days = skipped_post = 0

    # 1周目: 番組表を全部読み込み、節の長さ（何日開催か）を求める
    loaded = {}
    d = start
    while d <= end + timedelta(days=7):
        b_txt = history.fetch_text("B", d, a.cache, a.sleep)
        loaded[d] = history.parse_b(b_txt) if b_txt else []
        d += timedelta(days=1)
    day_of = {(d, r["jcd"]): r.get("day") for d, rs in loaded.items() for r in rs}
    series_len = {}  # (日付, 場) → その節の日数
    for (d, jcd), day in day_of.items():
        if not day:
            continue
        n, x = day, d
        while day_of.get((x + timedelta(days=1), jcd)) == n + 1:
            n += 1
            x += timedelta(days=1)
        series_len[(d, jcd)] = n
    samples = []
    # 記事ルール版との比較（同じレースで現行とルール版を並べる）
    cmp = {k: Stat() for k in ("pre_cur", "pre_rule", "post_cur", "post_rule",
                               "ana_cur", "ana_rule", "low_cur", "low_rule")}
    nobi_n = [0, 0]  # 展示後: [伸びサインあり, そのうちカドが1着]

    d = start
    while d <= end:
        b_races = loaded.get(d) or []
        k_txt = history.fetch_text("K", d, a.cache, a.sleep) if b_races else None
        if b_races and k_txt:
            days += 1
            results = history.parse_k(k_txt)
            mark_kakeru(b_races, {j: n for (x, j), n in series_len.items() if x == d})
            pre, post = daily_plan(b_races)
            for r in b_races:  # 比較用: 厳選なしで全レースを買った場合
                res = results.get((r["jcd"], r["rno"]))
                if res and not res["cancelled"] and res["trifecta"] and len(res["tenji"]) == 6:
                    w = scoring.ranking(r["boats"])
                    for name, f in VARIANTS.items():
                        var["all"][name].add(f(w), res)
            # 穴狙い枠: 1号艇の危うさが高い順に1日5レース（締切15時まで）
            ana_pool = []
            for r in b_races:
                if r["deadline"] > config.PRE_DEADLINE_LIMIT:
                    continue
                dg, _ = rules.danger(r)
                if dg >= 30:
                    ana_pool.append((dg, r))
            ana_pool.sort(key=lambda x: x[0], reverse=True)
            for dg, r in ana_pool[:5]:
                res = results.get((r["jcd"], r["rno"]))
                if not res or res["cancelled"] or not res["trifecta"] or len(res["tenji"]) < 6:
                    continue
                cmp["ana_cur"].add(scoring.pre_bets(r["boats"]), res)
                cmp["ana_rule"].add(rules.make_bets(r, None, scoring.PRE_P_FORM_W), res)
            for r in pre:
                res = results.get((r["jcd"], r["rno"]))
                if not res or res["cancelled"] or not res["trifecta"] or len(res["tenji"]) < 6:
                    continue
                samples.append(("pre", r["boats"], None, res))
                bets = scoring.pre_bets(r["boats"])
                rb = rules.make_bets(r, None, scoring.PRE_P_FORM_W)
                cmp["pre_cur"].add(bets, res)
                cmp["pre_rule"].add(rb, res)
                if rules.venue_in1(r["jcd"]) < 52:
                    cmp["low_cur"].add(bets, res)
                    cmp["low_rule"].add(rb, res)
                w = scoring.ranking(r["boats"])
                for name, f in VARIANTS.items():
                    var["pre"][name].add(f(w), res)
                before_ret = pre_s.ret
                pre_s.add(bets, res)
                pre_b[bucket(r["score"])].add(bets, res)
                month[f"{d:%Y-%m}"][0] += 600
                month[f"{d:%Y-%m}"][1] += pre_s.ret - before_ret
            for r in post:
                res = results.get((r["jcd"], r["rno"]))
                if not res or res["cancelled"] or not res["trifecta"] or len(res["tenji"]) < 6:
                    continue
                before = history.to_before(res)
                score, _, skip = scoring.post_score(r["boats"], before)
                if skip or score < config.POST_MIN_SCORE:
                    skipped_post += 1
                    continue
                samples.append(("post", r["boats"], before, res))
                bets = scoring.post_bets(r["boats"], before)
                cmp["post_cur"].add(bets, res)
                cmp["post_rule"].add(rules.make_bets(r, before), res)
                sg = rules.signals(r["boats"], before)
                if sg["nobi"]:
                    nobi_n[0] += 1
                    nobi_n[1] += res["order"].get(1) == sg["kado"]
                w = scoring.ranking(r["boats"], before)
                for name, f in VARIANTS.items():
                    var["post"][name].add(f(w), res)
                before_ret = post_s.ret
                post_s.add(bets, res)
                month[f"{d:%Y-%m}"][0] += 600
                month[f"{d:%Y-%m}"][1] += post_s.ret - before_ret
        if d.day == 1:
            print(f"{d:%Y-%m} まで処理（事前{pre_s.n} 展示後{post_s.n}）", flush=True)
        d += timedelta(days=1)

    out = [f"🧪 バックテスト結果 {start:%Y/%m/%d}〜{end:%Y/%m/%d}（{days}日分・各点100円）", ""]
    out += pre_s.lines("事前予想") + [""]
    out += post_s.lines("展示後予想") + [f"  （展示を見て見送り: {skipped_post:,}レース）", ""]
    out.append("■事前予想 スコア別の回収率（6点）")
    for k in ("75点以上", "65〜75点", "55〜65点", "55点未満"):
        s = pre_b.get(k)
        if s and s.n:
            out.append(f"  {k}: {s.n:,}R 的中{s.pct(s.hit, s.n)} 回収{s.pct(s.ret, s.n * 600)}")
    for kind, label in (("pre", "事前"), ("post", "展示後"), ("all", "厳選なし・全レース・出走表のみ")):
        out += ["", f"■買い目パターン比較（{label}・6点）"]
        out += [var[kind][name].line(name) for name in VARIANTS]
    out += ["", "■記事ルール版との比較（同じレース・6点）"]
    for key, label in (("pre", "事前"), ("post", "展示後（展示STなし。伸び・場・スジのみ）"),
                       ("low", "事前のうちイン弱い場（1コース1着率52%未満）"),
                       ("ana", "穴狙い枠（1号艇の危うさ上位5R/日）")):
        out.append(f"  [{label}]")
        for side, name in (("cur", "現行"), ("rule", "ルール版")):
            st = cmp[f"{key}_{side}"]
            if st.n:
                out.append(f"    {name}: {st.n:,}R 的中{st.pct(st.hit, st.n)} 回収{st.pct(st.ret, st.n * 600)}"
                           f" ／本命 回収{st.pct(st.h_ret, st.n * 300)} 穴 的中{st.pct(st.a_hit, st.n)} 回収{st.pct(st.a_ret, st.n * 300)}"
                           f" ／1号艇1着{st.pct(st.first[1], st.n)}")
    if nobi_n[0]:
        out.append(f"  展示後でカドの伸びサイン（0.13秒以上速い）: {nobi_n[0]:,}R、カドが1着 {nobi_n[1] / nobi_n[0] * 100:.1f}%")
    out += strength_report(samples)
    out += ["", "■月別の回収率（事前＋展示後）"]
    for m in sorted(month):
        inv, ret = month[m]
        out.append(f"  {m}: {ret / inv * 100:.0f}%" if inv else f"  {m}: -")
    text = "\n".join(out)
    print(text)
    os.makedirs("reports", exist_ok=True)
    open("reports/backtest_latest.txt", "w").write(text + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("```\n" + text + "\n```\n")
    notify.send(text)


if __name__ == "__main__":
    main()
