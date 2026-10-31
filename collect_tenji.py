"""過去レースの直前情報（展示ST・展示F・展示進入・展示タイム・風）を集める。

  python collect_tenji.py --start 2026-10-01 --end 2026-10-30 --out tenji_data

成績ファイル（K）には展示STが無いので、公式サイトの直前情報ページから取る。
全レースが対象。1日1ファイル tenji_data/YYYYMMDD.json.gz に
  {"jcd-rno": {"st": {"1": [艇番, ST, F?], ...}, "tenji": {"1": 6.78, ...}, "wind": "3m", "wave": "2cm", "wind_dir": 13, "tail": -3.0}}
で保存する（キーはコース番号／艇番の文字列）。
公式サイトへの負荷を抑えるため1秒に1回まで。既にある日は飛ばす。
"""
import argparse
import gzip
import json
import os
import time
from datetime import date, timedelta

from kyotei import config, history, scraper


def pack(bi: dict) -> dict | None:
    if not bi.get("start"):
        return None
    return {
        "st": {str(c): [v.get("boat"), v.get("st"), bool(v.get("flying"))] for c, v in bi["start"].items()},
        "tenji": {str(w): b.get("tenji_time") for w, b in bi["boats"].items()},
        "wind": bi.get("weather", {}).get("wind"),
        "wave": bi.get("weather", {}).get("wave"),
        "wind_dir": bi.get("weather", {}).get("wind_dir"),   # 1〜16（5=追い風、13=向かい風）、17=無風
        "tail": bi.get("weather", {}).get("tail"),           # 追い風の強さ（マイナスは向かい風）
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="tenji_data")
    ap.add_argument("--cache", default="history_cache")
    ap.add_argument("--newest-first", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=0, help="この時間を超えたら次の日に進まず終わる")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    config.REQUEST_SLEEP_SEC = 1.0
    t0 = time.time()

    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if a.newest_first:
        days.reverse()
    total = 0
    for d in days:
        if a.max_minutes and time.time() - t0 > a.max_minutes * 60:
            print("時間切れ。続きは次回", flush=True)
            break
        path = os.path.join(a.out, f"{d:%Y%m%d}.json.gz")
        if os.path.exists(path):
            continue
        b_txt = history.fetch_text("B", d, a.cache, 1.0)
        races = history.parse_b(b_txt) if b_txt else []
        day, fail = {}, 0
        for r in races:
            try:
                p = pack(scraper.fetch_beforeinfo(r["jcd"], r["rno"], f"{d:%Y%m%d}"))
            except scraper.ScrapeError as e:
                fail += 1
                print(f"  {d} {r['jcd']}-{r['rno']}: 失敗 {e}", flush=True)
                continue
            if p:
                day[f"{r['jcd']}-{r['rno']}"] = p
        # 開催がない日は空ファイルで「済」にする。取得失敗が多い日は保存せず次回やり直す
        if b_txt and fail <= max(5, len(races) // 10):
            with gzip.open(path + ".tmp", "wt") as f:
                json.dump(day, f, separators=(",", ":"))
            os.replace(path + ".tmp", path)
        total += len(day)
        print(f"{d}: {len(day)}/{len(races)}レース（失敗{fail}）", flush=True)
    print(f"完了: {total}レース分", flush=True)


if __name__ == "__main__":
    main()
