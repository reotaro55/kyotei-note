"""公式の過去データ（番組表・競走成績）を取得・解析する。

配布元: https://www1.mbrace.or.jp/od2/{B|K}/YYYYMM/{b|k}YYMMDD.lzh
  B = 番組表（出走表）  K = 競走成績（展示タイム・進入・結果・払戻）
LZHの展開には lhasa（lha コマンド）を使う。
"""
import os
import re
import subprocess
import time
import unicodedata
from datetime import date

import requests

from .scraper import VENUES

URL = "https://www1.mbrace.or.jp/od2/{kind}/{ym}/{k}{ymd}.lzh"


def _z2h(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


# ------------------------------------------------------------------ 取得
def fetch_text(kind: str, d: date, cache_dir: str, sleep: float = 1.0) -> str | None:
    """1日分のファイルを取得してテキストで返す（なければ None）。"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{kind.lower()}{d:%y%m%d}.lzh")
    if not os.path.exists(path):
        url = URL.format(kind=kind, ym=f"{d:%Y%m}", k=kind.lower(), ymd=f"{d:%y%m%d}")
        for i in range(3):
            try:
                time.sleep(sleep)
                r = requests.get(url, timeout=60, headers={"User-Agent": "kyotei-note-backtest/1.0"})
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                if r.content[2:5] != b"-lh":
                    return None
                open(path, "wb").write(r.content)
                break
            except requests.RequestException:
                time.sleep(5 * (i + 1))
        else:
            return None
    return _unlzh(path)


def _unlzh(path: str) -> str | None:
    """LZHを展開して中のテキストを返す。"""
    for args in (["lha", "pq", path], ["lha", "-pq", path]):
        out = subprocess.run(args, capture_output=True)
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("cp932", errors="replace")
    tmp = path + ".d"
    os.makedirs(tmp, exist_ok=True)
    subprocess.run(["lha", f"xqw={tmp}", path], capture_output=True)
    files = [os.path.join(tmp, f) for f in os.listdir(tmp)]
    if not files:
        return None
    return open(files[0], "rb").read().decode("cp932", errors="replace")


def _blocks(text: str, kind: str):
    """場ごとのブロック (jcd, 行リスト) に分ける。"""
    jcd, lines = None, []
    for line in text.splitlines():
        m = re.match(rf"^(\d\d){kind}BGN", line)
        if m:
            jcd, lines = m.group(1), []
            continue
        if re.match(rf"^\d\d{kind}END", line):
            if jcd:
                yield jcd, lines
            jcd = None
            continue
        if jcd:
            lines.append(line)


# ------------------------------------------------------------------ 番組表
B_RACE = re.compile(r"^[\s　]*([０-９0-9]+)[ＲR].*?締切予定([０-９0-9]{2})[：:]([０-９0-9]{2})")
B_BOAT = re.compile(
    r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12]) *"
    r"(\d+\.\d+) +(\d+\.\d+) +(\d+\.\d+) +(\d+\.\d+) +(\d+) +(\d+\.\d+) +(\d+) +(\d+\.\d+)"
)


def parse_b(text: str) -> list[dict]:
    """番組表 → レースのリスト。boats は scraper.parse_racelist と同じ形。"""
    races = []
    for jcd, lines in _blocks(text, "B"):
        cur = None
        for line in lines:
            m = B_RACE.match(line)
            if m:
                rno = int(_z2h(m.group(1)))
                cur = {"jcd": jcd, "venue": VENUES.get(jcd, jcd), "rno": rno,
                       "deadline": f"{_z2h(m.group(2))}:{_z2h(m.group(3))}", "boats": {}}
                races.append(cur)
                continue
            m = B_BOAT.match(line)
            if m and cur is not None:
                w = int(m.group(1))
                cur["boats"][w] = {
                    "waku": w, "racer_id": m.group(2), "name": m.group(3).replace("　", ""),
                    "class": m.group(7), "F": 0, "L": 0, "avg_st": None,
                    "win_rate": float(m.group(8)), "win2": float(m.group(9)),
                    "local_win_rate": float(m.group(10)),
                    "motor_no": int(m.group(12)), "motor2": float(m.group(13)),
                    "boat2": float(m.group(15)),
                }
    return [r for r in races if len(r["boats"]) == 6]


# ------------------------------------------------------------------ 競走成績
K_RACE = re.compile(r"^\s+(\d{1,2})R\s+\S")
K_ROW = re.compile(r"^\s+([0-9FLKSE０-９][0-9０-９]?)\s+([1-6])\s+(\d{4})\s.*?(\d\.\d\d)\s+([1-6])\s+(F?[\d.]+|L|K|\.)")
K_TRI = re.compile(r"^\s+３連単\s+(\d-\d-\d)\s+(\d+)\s+人気\s+(\d+)")


def parse_k(text: str) -> dict:
    """競走成績 → {(jcd, rno): {...}}。展示タイム・進入・3連単の払戻。"""
    out = {}
    for jcd, lines in _blocks(text, "K"):
        cur, last = None, None
        for line in lines:
            m = K_RACE.match(line)
            if m and ("H" in line or "m" in line):
                cur = {"tenji": {}, "course": {}, "order": {}, "trifecta": [], "cancelled": False}
                out[(jcd, int(m.group(1)))] = cur
                continue
            if cur is None:
                continue
            if "レース中止" in line:
                cur["cancelled"] = True
            m = K_ROW.match(line)
            if m:
                w = int(m.group(2))
                cur["tenji"][w] = float(m.group(4))
                cur["course"][w] = int(m.group(5))
                rank = _z2h(m.group(1))
                if rank.isdigit():
                    cur["order"][int(rank)] = w
                continue
            m = K_TRI.match(line)
            if m:
                cur["trifecta"].append((m.group(1), int(m.group(2)), int(m.group(3))))
                last = "tri"
                continue
            m = re.match(r"^\s{10,}(\d-\d-\d)\s+(\d+)\s+人気\s+(\d+)", line)
            if m and last == "tri":  # 同着で3連単が複数あるとき
                cur["trifecta"].append((m.group(1), int(m.group(2)), int(m.group(3))))
                continue
            last = None
    return out


def to_before(k: dict) -> dict:
    """競走成績の展示・進入を、直前情報(beforeinfo)と同じ形にする。

    展示STは成績ファイルに無いので入れない。進入は本番の進入（展示進入とほぼ同じ）。
    """
    start = {c: {"boat": w, "st": None, "flying": False} for w, c in k["course"].items()}
    boats = {w: {"tenji_time": t, "tilt": None, "parts": []} for w, t in k["tenji"].items()}
    return {"boats": boats, "start": start, "weather": {}, "ready": len(boats) >= 5}
