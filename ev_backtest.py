"""期待値（確率×オッズ）で買い目を選んだらどうなるかを、集めた確定オッズで検証する。

  python ev_backtest.py --model reports/model.json --odds odds_wt/odds_data

確定オッズ（締切時点）を使うので、実際に朝買う人より少し有利な前提になる点に注意。
"""
import argparse
import gzip
import json
import os
from collections import defaultdict
from datetime import date, datetime

import numpy as np

import backtest
import train_model as tm
from kyotei import history, scoring


def top_by(d: dict, n: int, cond=lambda c: True) -> list[str]:
    return [c for c, _ in sorted(((c, v) for c, v in d.items() if cond(c)), key=lambda t: -t[1])[:n]]


class S:
    def __init__(self):
        self.n = self.hit = self.ret = self.pts = 0

    def add(self, combos, res):
        if not combos:
            return
        self.n += 1
        self.pts += len(combos)
        got = [p for c, p, _ in res["trifecta"] if c in combos]
        if got:
            self.hit += 1
            self.ret += sum(got)

    def line(self, name):
        if not self.n:
            return f"  {name}: 対象なし"
        return (f"  {name}: {self.n:,}R 的中{self.hit / self.n * 100:.1f}% "
                f"回収{self.ret / (self.pts * 100) * 100:.1f}%")


def strategies(p, wakus, odds, model, boats, before):
    tp = tm.trifecta_probs(p, wakus, model["l2"], model["l3"])
    ev = {c: tp[c] * odds[c] for c in tp if c in odds}
    head = str(wakus[int(np.argmax(p))])
    out = {
        "現行ルール": scoring.flat(scoring.make_bets(boats, before)),
        "確率上位6点": top_by(tp, 6),
        "期待値上位6点": top_by(ev, 6),
        "本命3(確率)+穴3(期待値・別の頭)": top_by(tp, 3, lambda c: c[0] == head)
        + top_by(ev, 3, lambda c: c[0] != head),
    }
    best = max(ev.values()) if ev else 0
    for t in (1.0, 1.2, 1.5, 2.0):
        out[f"期待値{t}以上の目だけ(最大6点)"] = [c for c in top_by(ev, 6) if ev[c] >= t]
        out[f"期待値上位6点・最大期待値{t}以上のレースだけ"] = top_by(ev, 6) if best >= t else []
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="reports/model.json")
    ap.add_argument("--odds", default="odds_wt/odds_data")
    ap.add_argument("--cache", default="history_cache")
    a = ap.parse_args()
    models = json.load(open(a.model))
    files = sorted(f for f in os.listdir(a.odds) if f.endswith(".json.gz"))
    stats = {k: defaultdict(S) for k in ("pre", "post", "all")}
    days = 0
    for f in files:
        d = datetime.strptime(f[:8], "%Y%m%d").date()
        odds_day = json.load(gzip.open(os.path.join(a.odds, f), "rt"))
        if not odds_day:
            continue
        bt = history.fetch_text("B", d, a.cache, 1.0)
        kt = history.fetch_text("K", d, a.cache, 1.0) if bt else None
        if not (bt and kt):
            continue
        days += 1
        ks = history.parse_k(kt)
        b_races = history.parse_b(bt)
        pre, post = backtest.daily_plan(b_races)
        sel = {(r["jcd"], r["rno"]): "pre" for r in pre} | {(r["jcd"], r["rno"]): "post" for r in post}
        for r in b_races:
            key = (r["jcd"], r["rno"])
            odds = odds_day.get(f"{r['jcd']}-{r['rno']}")
            k = ks.get(key)
            if not odds or not k or k["cancelled"] or not k["trifecta"] or len(k["tenji"]) < 6:
                continue
            kind = sel.get(key)
            use_post = kind == "post"
            model = models["post" if use_post else "pre"]
            wakus, X = tm.race_matrix(r["boats"], k if use_post else None)
            p = tm.win_probs(model, X)
            before = history.to_before(k) if use_post else None
            for name, combos in strategies(p, wakus, odds, model, r["boats"], before).items():
                stats["all"][name].add(combos, k)
                if kind:
                    stats[kind][name].add(combos, k)
    out = [f"💹 期待値バックテスト（確定オッズ {days}日分・各点100円）", ""]
    for kind, label in (("pre", "事前予想の厳選レース"), ("post", "展示後予想の厳選レース"),
                        ("all", "候補レースすべて（1号艇A級・出走表モデル）")):
        out.append(f"■{label}")
        out += [s.line(name) for name, s in stats[kind].items()]
        out.append("")
    text = "\n".join(out)
    os.makedirs("reports", exist_ok=True)
    open("reports/ev_report.txt", "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
