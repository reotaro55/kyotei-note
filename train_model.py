"""各艇の1着確率を出すモデルを、過去データから学習・検証する。

  python train_model.py --train 2024-10-01:2025-09-30 --test 2025-10-01:2026-10-26

モデル: 条件付きロジット（レース内の6艇で softmax）。
  P(艇iが1着) = exp(w・x_i) / Σ exp(w・x_j)
3連単の確率は Harville 方式（1着が決まったら残りでまた softmax）で計算し、
2・3着は「強さの差が縮む」ように指数 λ2, λ3 をかけて調整する。

出力: reports/model.json（重み）と reports/model_report.txt（検証結果）
"""
import argparse
import gzip
import json
import math
import os
from collections import defaultdict
from datetime import date, timedelta
from itertools import permutations

import numpy as np

from kyotei import history

CLASSES = ("A1", "A2", "B1", "B2")
FEATURES = (
    ["course2", "course3", "course4", "course5", "course6"]
    + ["win_rate", "local_win_rate", "motor2", "boat2", "form", "form_missing"]
    + ["cls_A1", "cls_A2", "cls_B2"]
    + ["tenji1", "tenji2", "tenji5", "tenji6", "tenji_diff"]
)


def boat_features(b: dict, course: int, tenji_rank: int | None, tenji_diff: float | None) -> list[float]:
    f = b.get("form")
    x = [1.0 if course == c else 0.0 for c in (2, 3, 4, 5, 6)]
    x += [b["win_rate"], b.get("local_win_rate") or b["win_rate"], b["motor2"] / 10, b.get("boat2", 0) / 10,
          f if f is not None and b.get("kon_n", 0) >= 2 else 0.0,
          0.0 if f is not None and b.get("kon_n", 0) >= 2 else 1.0]
    x += [1.0 if b["class"] == c else 0.0 for c in ("A1", "A2", "B2")]
    x += [1.0 if tenji_rank == r else 0.0 for r in (1, 2, 5, 6)]
    x += [tenji_diff if tenji_diff is not None else 0.0]
    return x


def race_matrix(boats: dict, k: dict | None) -> tuple[list[int], np.ndarray]:
    """6艇の特徴量。k（競走成績）があれば展示と進入を使う（=展示後モデル）。"""
    wakus = sorted(boats)
    course = {w: w for w in wakus}
    trank, tdiff = {}, {}
    if k and len(k["tenji"]) >= 6:
        course = {w: k["course"].get(w, w) for w in wakus}
        times = k["tenji"]
        order = sorted(times, key=lambda w: times[w])
        trank = {w: i + 1 for i, w in enumerate(order)}
        avg = sum(times.values()) / len(times)
        tdiff = {w: (avg - times[w]) * 10 for w in times}  # 平均より速いほどプラス
    X = np.array([boat_features(boats[w], course[w], trank.get(w), tdiff.get(w)) for w in wakus])
    return wakus, X


def load(rng: str, cache: str, use_tenji: bool):
    a, b = rng.split(":")
    d, end = date.fromisoformat(a), date.fromisoformat(b)
    rows = []  # (date, jcd, rno, wakus, X, winner_index, trifecta[(combo,pay)], boats)
    while d <= end:
        bt = history.fetch_text("B", d, cache, 1.0)
        kt = history.fetch_text("K", d, cache, 1.0) if bt else None
        if bt and kt:
            ks = history.parse_k(kt)
            for r in history.parse_b(bt):
                k = ks.get((r["jcd"], r["rno"]))
                if not k or k["cancelled"] or len(k["tenji"]) < 6 or not k["trifecta"]:
                    continue
                win = k["order"].get(1)
                if win not in r["boats"]:
                    continue
                wakus, X = race_matrix(r["boats"], k if use_tenji else None)
                rows.append((d, r["jcd"], r["rno"], wakus, X, wakus.index(win),
                             [(c, p) for c, p, _ in k["trifecta"]], r["boats"], k))
        d += timedelta(days=1)
    return rows


def fit(rows, l2=1e-3, iters=400, lr=0.5):
    X = np.stack([r[4] for r in rows])          # (N, 6, F)
    y = np.array([r[5] for r in rows])          # (N,)
    mu = X.reshape(-1, X.shape[2]).mean(0)
    sd = X.reshape(-1, X.shape[2]).std(0) + 1e-9
    Z = (X - mu) / sd
    w = np.zeros(Z.shape[2])
    m = v = np.zeros_like(w)
    for t in range(1, iters + 1):  # Adam
        s = Z @ w
        s -= s.max(1, keepdims=True)
        p = np.exp(s)
        p /= p.sum(1, keepdims=True)
        onehot = np.zeros_like(p)
        onehot[np.arange(len(y)), y] = 1
        g = -np.einsum("nk,nkf->f", onehot - p, Z) / len(y) + l2 * w
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        w = w - lr * 0.1 * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return {"features": FEATURES, "mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist()}


def win_probs(model, X):
    Z = (X - np.array(model["mu"])) / np.array(model["sd"])
    s = Z @ np.array(model["w"])
    s -= s.max()
    p = np.exp(s)
    return p / p.sum()


def trifecta_probs(p: np.ndarray, wakus: list[int], l2: float = 0.8, l3: float = 0.7) -> dict[str, float]:
    out = {}
    for i, j, k in permutations(range(len(wakus)), 3):
        pi = p[i]
        rest = [x for x in range(len(wakus)) if x != i]
        q = np.array([p[x] ** l2 for x in rest])
        pj = p[j] ** l2 / q.sum()
        rest2 = [x for x in rest if x != j]
        r = np.array([p[x] ** l3 for x in rest2])
        pk = p[k] ** l3 / r.sum()
        out[f"{wakus[i]}-{wakus[j]}-{wakus[k]}"] = float(pi * pj * pk)
    return out


def combo_prob(p: np.ndarray, wakus: list[int], combo: str, l2: float, l3: float) -> float:
    """3連単1通りだけの確率（速い版）。"""
    try:
        i, j, k = (wakus.index(int(x)) for x in combo.split("-"))
    except ValueError:
        return 0.0
    q2 = p ** l2
    q2[i] = 0
    q3 = p ** l3
    q3[i] = q3[j] = 0
    return float(p[i] * (p[j] ** l2 / q2.sum()) * (p[k] ** l3 / q3.sum()))


def evaluate(model, rows, label, l2, l3, odds_dir=None):
    out = [f"■{label}（{len(rows):,}レース）"]
    ll = top1 = 0.0
    tri_ll = 0.0
    bins = defaultdict(lambda: [0, 0.0, 0])  # 予測確率帯 → [件数, 予測合計, 当たり]
    for d, jcd, rno, wakus, X, yi, tri, boats, k in rows:
        p = win_probs(model, X)
        ll += -math.log(max(p[yi], 1e-9))
        top1 += 1 if int(np.argmax(p)) == yi else 0
        b = min(int(p.max() * 10), 9)
        bins[b][0] += 1
        bins[b][1] += p.max()
        bins[b][2] += 1 if int(np.argmax(p)) == yi else 0
        tri_ll += -math.log(max(sum(combo_prob(p, wakus, c, l2, l3) for c, _ in tri), 1e-9))
    n = len(rows)
    out.append(f"  1着の対数損失 {ll / n:.4f}（ランダム {math.log(6):.4f}）  本命の1着的中 {top1 / n * 100:.1f}%")
    out.append(f"  3連単の対数損失 {tri_ll / n:.4f}（ランダム {math.log(120):.4f}）")
    out.append("  本命の予測確率 → 実際の1着率（ズレが小さいほど確率が正確）")
    for b in sorted(bins):
        c, ps, h = bins[b]
        if c >= 50:
            out.append(f"    {b * 10:>2}〜{b * 10 + 10}%: 予測{ps / c * 100:.1f}% 実際{h / c * 100:.1f}%（{c:,}R）")
    return out


def tune_lambda(model, rows):
    best = None
    for l2 in (0.6, 0.7, 0.8, 0.9, 1.0):
        for l3 in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
            s = 0.0
            for r in rows[::5]:
                p = win_probs(model, r[4])
                s += -math.log(max(sum(combo_prob(p, r[3], c, l2, l3) for c, _ in r[6]), 1e-9))
            if best is None or s < best[0]:
                best = (s, l2, l3)
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--test", required=True)
    ap.add_argument("--cache", default="history_cache")
    a = ap.parse_args()
    os.makedirs("reports", exist_ok=True)
    report = ["🧠 1着確率モデルの学習結果", ""]
    models = {}
    for kind, use_tenji in (("pre", False), ("post", True)):
        label = "事前（出走表のみ）" if kind == "pre" else "展示後（展示タイム・進入あり）"
        tr = load(a.train, a.cache, use_tenji)
        te = load(a.test, a.cache, use_tenji)
        model = fit([r[:6] for r in tr])
        l2, l3 = tune_lambda(model, tr)
        model.update({"l2": l2, "l3": l3})
        models[kind] = model
        report.append(f"■{label}  学習{len(tr):,}R / 検証{len(te):,}R  λ2={l2} λ3={l3}")
        report.append("  重み（標準化後。プラスほど1着になりやすい）:")
        for f, w in sorted(zip(FEATURES, model["w"]), key=lambda t: -abs(t[1])):
            report.append(f"    {f:<15} {w:+.3f}")
        report += evaluate(model, tr, "学習期間", l2, l3)
        report += evaluate(model, te, "検証期間（学習に使っていない年）", l2, l3)
        report.append("")
    json.dump(models, open("reports/model.json", "w"), ensure_ascii=False, indent=1)
    text = "\n".join(report)
    open("reports/model_report.txt", "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
