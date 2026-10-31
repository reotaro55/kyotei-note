"""1レースだけ、現行とルール版の予想を並べて表示する（Discordには送らない）。

  python try_race.py --jcd 13 --rno 1 --hd 20261031
"""
import argparse
import json

from kyotei import rules, scoring, scraper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jcd", required=True)
    ap.add_argument("--rno", type=int, required=True)
    ap.add_argument("--hd", required=True)
    a = ap.parse_args()
    rl = scraper.fetch_racelist(a.jcd, a.rno, a.hd)
    race = dict(rl, jcd=a.jcd, rno=a.rno)
    bi = scraper.fetch_beforeinfo(a.jcd, a.rno, a.hd)
    out = {"出走表": {w: {k: b.get(k) for k in ("name", "class", "win_rate", "local_win_rate", "motor2", "avg_st")}
                    for w, b in rl["boats"].items()},
           "展示": {"進入とST": bi["start"], "展示タイム": {w: b["tenji_time"] for w, b in bi["boats"].items()},
                  "天候": bi["weather"], "そろった": bi["ready"]}}
    sig = rules.signals(rl["boats"], bi)
    out["サイン"] = sig["notes"]
    out["1号艇の危うさ"] = rules.danger(race)
    out["現行_事前"] = scoring.pre_bets(rl["boats"])
    out["ルール版_事前"] = rules.make_bets(race, None, scoring.PRE_P_FORM_W)
    if bi["ready"]:
        out["現行_展示後"] = {"スコア": scoring.post_score(rl["boats"], bi), "買い目": scoring.post_bets(rl["boats"], bi)}
        out["ルール版_展示後"] = {"強い順": rules.ranking(race, bi), "買い目": rules.make_bets(race, bi)}
    print("RESULT_JSON " + json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
