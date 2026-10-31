"""1場の全レースで、現行とルール版を事前・展示後の両方で試して結果まで判定する。
Discordには送らず、途中経過を trial ブランチの trial/<日付>_<場>.json に保存する。

  python venue_trial.py --jcd 13 --hd 20261031 --state trial_wt/trial --minutes 340

途中で止まっても、同じファイルから続きを再開できる。
"""
import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kyotei import rules, scoring, scraper

JST = ZoneInfo("Asia/Tokyo")


def now():
    return datetime.now(JST)


def judge(bets, res: dict) -> int:
    flat = bets if isinstance(bets, list) else scoring.flat(bets)
    return res["payout"] if res["trifecta"] in flat else 0


def save(path: str, state: dict, push_dir: str | None):
    with open(path + ".tmp", "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)
    os.replace(path + ".tmp", path)
    if push_dir:
        subprocess.run(f"cd {push_dir} && git add -A && git commit -qm 'trial update' && git push -q origin HEAD:trial",
                       shell=True)


KINDS = ("pre_cur", "pre_rule", "post_cur", "post_rule", "pre_big", "post_big")


def summary(state: dict) -> dict:
    s = {}
    for kind in KINDS:
        n = hit = ret = 0
        for r in state["races"].values():
            if r.get("result") and not r["result"].get("cancelled") and kind in r:
                n += 1
                if "payout" not in r[kind]:
                    continue
                p = r[kind]["payout"]
                hit += p > 0
                ret += p
        pts = 3 if kind.endswith("_big") else 6
        s[kind] = {"レース": n, "的中": hit, "投資": n * pts * 100, "払戻": ret,
                   "回収率": f"{ret / (n * pts * 100) * 100:.1f}%" if n else "-"}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jcd", required=True)
    ap.add_argument("--hd", required=True)
    ap.add_argument("--state", default="trial")
    ap.add_argument("--minutes", type=float, default=340)
    ap.add_argument("--push-dir", default="")
    a = ap.parse_args()
    os.makedirs(a.state, exist_ok=True)
    path = os.path.join(a.state, f"{a.hd}_{a.jcd}.json")
    state = json.load(open(path)) if os.path.exists(path) else {"jcd": a.jcd, "hd": a.hd, "races": {}}
    push = a.push_dir or None
    t_end = time.time() + a.minutes * 60

    index = scraper.fetch_raceindex(a.jcd, a.hd)
    for ri in index:
        r = state["races"].setdefault(str(ri["rno"]), {"deadline": ri["deadline"]})
        if "pre_cur" in r:
            if "pre_big" not in r and not r.get("result"):
                rl = scraper.fetch_racelist(a.jcd, ri["rno"], a.hd)
                r["pre_big"] = {"bets": rules.big_bets(dict(rl, jcd=a.jcd, rno=ri["rno"]))}
            continue
        rl = scraper.fetch_racelist(a.jcd, ri["rno"], a.hd)
        race = dict(rl, jcd=a.jcd, rno=ri["rno"])
        r["entry"] = {w: f"{b['name']}({b['class']} {b['win_rate']:.2f} M{b['motor2']:.1f})" for w, b in rl["boats"].items()}
        r["danger"] = rules.danger(race)
        r["pre_cur"] = {"bets": scoring.pre_bets(rl["boats"])}
        r["pre_rule"] = {"bets": rules.make_bets(race, None, scoring.PRE_P_FORM_W)}
        r["pre_big"] = {"bets": rules.big_bets(race)}
    save(path, state, push)

    while time.time() < t_end:
        changed = False
        pending = 0
        for rno, r in sorted(state["races"].items(), key=lambda x: int(x[0])):
            if r.get("result"):
                continue
            pending += 1
            h, m = map(int, r["deadline"].split(":"))
            dl = datetime.strptime(a.hd, "%Y%m%d").replace(hour=h, minute=m, tzinfo=JST)
            # 展示後: 締切40分前〜締切まで、展示がそろったら1回だけ予想する
            if "post_cur" not in r and dl - timedelta(minutes=40) <= now() < dl:
                bi = scraper.fetch_beforeinfo(a.jcd, int(rno), a.hd)
                if bi["ready"]:
                    rl = scraper.fetch_racelist(a.jcd, int(rno), a.hd)
                    race = dict(rl, jcd=a.jcd, rno=int(rno))
                    score, notes, skip = scoring.post_score(rl["boats"], bi)
                    sig = rules.signals(rl["boats"], bi)
                    r["tenji"] = {"進入とST": {c: [v["boat"], v["st"], v["flying"]] for c, v in bi["start"].items()},
                                  "展示タイム": {w: b["tenji_time"] for w, b in bi["boats"].items()},
                                  "天候": bi["weather"], "サイン": sig["notes"]}
                    r["post_cur"] = {"bets": scoring.post_bets(rl["boats"], bi), "score": score,
                                     "見送り": skip, "notes": notes}
                    r["post_rule"] = {"bets": rules.make_bets(race, bi), "強い順": rules.ranking(race, bi)}
                    r["post_big"] = {"bets": rules.big_bets(race, bi)}
                    r["posted_at"] = now().strftime("%H:%M")
                    changed = True
            # 結果: 締切8分後から
            if now() >= dl + timedelta(minutes=8):
                res = scraper.fetch_result(a.jcd, int(rno), a.hd)
                if res:
                    r["result"] = res
                    if not res.get("cancelled"):
                        for kind in KINDS:
                            if kind in r:
                                r[kind]["payout"] = judge(r[kind]["bets"], res)
                    changed = True
        if changed:
            state["summary"] = summary(state)
            save(path, state, push)
        if not pending:
            break
        time.sleep(60)
    state["summary"] = summary(state)
    save(path, state, push)
    print(json.dumps(state["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
