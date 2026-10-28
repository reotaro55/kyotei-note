"""過去レースの確定3連単オッズを集める（期待値の検証用）。

  python collect_odds.py --start 2026-07-01 --end 2026-09-30 --out odds_data

対象は「1号艇がA1/A2」のレース（予想の候補になるレース）だけ。
1日1ファイル odds_data/YYYYMMDD.json.gz に {"jcd-rno": {"1-2-3": 5.6, ...}} で保存。
公式サイトへの負荷を抑えるため、1秒に1回まで。既にあるファイルは飛ばす。
"""
import argparse
import gzip
import json
import os
from datetime import date, timedelta

from kyotei import config, history, scraper

PREFILTER = ("A1", "A2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="odds_data")
    ap.add_argument("--cache", default="history_cache")
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    config.REQUEST_SLEEP_SEC = 1.0

    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if a.newest_first:
        days.reverse()
    total = 0
    for d in days:
        path = os.path.join(a.out, f"{d:%Y%m%d}.json.gz")
        if not os.path.exists(path):
            b_txt = history.fetch_text("B", d, a.cache, 1.0)
            races = history.parse_b(b_txt) if b_txt else []
            day = {}
            for r in races:
                if r["boats"][1]["class"] not in PREFILTER:
                    continue
                try:
                    o = scraper.fetch_odds3t(r["jcd"], r["rno"], f"{d:%Y%m%d}")
                except scraper.ScrapeError as e:
                    print(f"  {d} {r['jcd']}-{r['rno']}: 失敗 {e}", flush=True)
                    continue
                if o:
                    day[f"{r['jcd']}-{r['rno']}"] = o
            if day:
                with gzip.open(path, "wt") as f:
                    json.dump(day, f, separators=(",", ":"))
            total += len(day)
            print(f"{d}: {len(day)}レース", flush=True)
    print(f"完了: {total}レース分", flush=True)


if __name__ == "__main__":
    main()
