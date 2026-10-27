"""ボートレース公式サイト（boatrace.jp）からデータを取得する。

HTMLの読み取り方は pyjpboatrace（MIT License, (c) 2020 hmasdev）の
パーサーを参考にしています。サイトの見た目が変わると動かなくなるので、
エラーが出たらまずここを疑ってください。
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from . import config

BASE = "https://www.boatrace.jp/owpc/pc/race/"

VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川",
    "06": "浜名湖", "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国",
    "11": "びわこ", "12": "住之江", "13": "尼崎", "14": "鳴門", "15": "丸亀",
    "16": "児島", "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; kyotei-note-bot/1.0)",
    "Accept-Language": "ja",
})


class ScrapeError(Exception):
    pass


def _get(page: str, **params) -> BeautifulSoup:
    last = None
    for attempt in range(3):
        try:
            time.sleep(config.REQUEST_SLEEP_SEC)
            r = _session.get(BASE + page, params=params, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise ScrapeError(f"{page} {params}: {last}")


def _num(s, typ=float, default=None):
    try:
        return typ(str(s).strip())
    except (TypeError, ValueError):
        return default


def _clean(s: str) -> str:
    return "".join(str(s).split())


# ------------------------------------------------------------------ 開催一覧
def parse_index(soup: BeautifulSoup) -> list[dict]:
    """本日の開催場一覧。"""
    venues = []
    table = soup.select_one("div.table1")
    if table is None:
        return venues
    for tbody in table.select("table > tbody"):
        a = tbody.find("a", href=re.compile(r"jcd=\d\d"))
        if not a:
            continue
        jcd = re.search(r"jcd=(\d\d)", a["href"]).group(1)
        classes = " ".join(" ".join(td.get("class", [])) for td in tbody.select("td"))
        if "nighter" in classes:
            timeframe = "nighter"
        elif "midnight" in classes:
            timeframe = "midnight"
        elif "morning" in classes:
            timeframe = "morning"
        else:
            timeframe = "day"
        text = _clean(tbody.get_text())
        venues.append({
            "jcd": jcd,
            "name": VENUES.get(jcd, jcd),
            "timeframe": timeframe,
            "cancelled": "中止" in text,
            "grade": ("SG" if "is-SG" in classes else "G1" if "is-G1" in classes
                      else "G2" if "is-G2" in classes else "G3" if "is-G3" in classes else ""),
        })
    return venues


def fetch_index(hd: str) -> list[dict]:
    return parse_index(_get("index", hd=hd))


# --------------------------------------------------------------- 場ごとの12R
def parse_raceindex(soup: BeautifulSoup) -> list[dict]:
    """各レースの締切時刻と6人の級別。"""
    races = []
    for tbody in soup.select("div.table1 > table > tbody"):
        tds = tbody.select("tr > td")
        if len(tds) < 9:
            continue
        rno = _num(_clean(tds[0].get_text()).replace("R", ""), int)
        hhmm = _clean(tds[1].get_text())
        if not rno or not re.match(r"^\d{1,2}:\d{2}$", hhmm):
            continue
        h, m = hhmm.split(":")
        classes = []
        for td in tds[3:9]:
            divs = td.select("div")
            classes.append(_clean(divs[-1].get_text()) if divs else "")
        races.append({
            "rno": rno,
            "deadline": f"{int(h):02d}:{m}",
            "status": _clean(tds[2].get_text()),
            "classes": classes,
        })
    return races


def fetch_raceindex(jcd: str, hd: str) -> list[dict]:
    return parse_raceindex(_get("raceindex", jcd=jcd, hd=hd))


# ------------------------------------------------------------------ 出走表
def _split(td, sep=","):
    return [t for t in _clean(td.get_text(sep)).split(sep) if t != ""]


def parse_racelist(soup: BeautifulSoup) -> dict:
    boats = {}
    for tbody in soup.select("div.table1.is-tableFixed__3rdadd > table > tbody"):
        trs = tbody.select("tr")
        if not trs:
            continue
        tds = trs[0].select("td")
        try:
            waku = _num(_clean(tds[0].get_text()), int)
            info = []
            for div in tds[2].select("div"):
                info += [t for t in _clean(div.get_text("/")).split("/") if t]
            racer_id, cls, name = info[0], info[1], info[2]
            f_l_st = _split(tds[3])
            zenkoku = _split(tds[4])
            touchi = _split(tds[5])
            motor = _split(tds[6])
            boat = _split(tds[7])
        except (IndexError, AttributeError):
            continue
        if not waku:
            continue
        boats[waku] = {
            "waku": waku,
            "racer_id": racer_id,
            "class": cls,
            "name": name,
            "F": _num(re.sub(r"\D", "", f_l_st[0]) if f_l_st else "", int, 0),
            "L": _num(re.sub(r"\D", "", f_l_st[1]) if len(f_l_st) > 1 else "", int, 0),
            "avg_st": _num(f_l_st[2] if len(f_l_st) > 2 else None),
            "win_rate": _num(zenkoku[0] if zenkoku else None, float, 0.0),
            "win2": _num(zenkoku[1] if len(zenkoku) > 1 else None, float, 0.0),
            "local_win_rate": _num(touchi[0] if touchi else None, float, 0.0),
            "motor_no": _num(motor[0] if motor else None, int),
            "motor2": _num(motor[1] if len(motor) > 1 else None, float, 0.0),
            "boat2": _num(boat[1] if len(boat) > 1 else None, float, 0.0),
        }
    h3 = soup.select_one("h3")
    return {"title": _clean(h3.get_text()) if h3 else "", "boats": boats}


def fetch_racelist(jcd: str, rno: int, hd: str) -> dict:
    return parse_racelist(_get("racelist", rno=rno, jcd=jcd, hd=hd))


# ------------------------------------------------------------------ 直前情報
def parse_beforeinfo(soup: BeautifulSoup) -> dict:
    out = {"boats": {}, "start": {}, "weather": {}, "ready": False}
    units = soup.select("div.grid_unit")
    if len(units) < 2:
        return out
    for tbody in units[0].select("div.table1 > table > tbody"):
        trs = tbody.select("tr")
        if not trs:
            continue
        tds = trs[0].select("td")
        if len(tds) < 7:
            continue
        waku = _num(_clean(tds[0].get_text()), int)
        if not waku:
            continue
        out["boats"][waku] = {
            "tenji_time": _num(_clean(tds[4].get_text())),
            "tilt": _num(_clean(tds[5].get_text())),
            "parts": [_clean(li.get_text()) for li in tds[7].select("ul > li")] if len(tds) > 7 else [],
        }
    for course, tr in enumerate(units[1].select("div.table1 > table > tbody > tr"), 1):
        spans = tr.select("div > span")
        if len(spans) >= 3:
            st_text = _clean(spans[2].get_text())
            out["start"][course] = {
                "boat": _num(_clean(spans[0].get_text()), int),
                "st": _num(st_text.replace("F.", "-0.").replace("L", "")),
                "flying": st_text.startswith("F"),
            }
    w = units[1].select_one("div.weather1")
    if w:
        try:
            divs = w.select("div.weather1_body > div")
            out["weather"] = {
                "weather": _clean(divs[1].select_one("div > span").get_text()),
                "wind": _clean(divs[2].select("div > span")[-1].get_text()),
                "wave": _clean(divs[5].select("div > span")[-1].get_text()),
            }
        except (IndexError, AttributeError):
            pass
    times = [b["tenji_time"] for b in out["boats"].values()]
    out["ready"] = len(times) >= 5 and all(t for t in times)
    return out


def fetch_beforeinfo(jcd: str, rno: int, hd: str) -> dict:
    return parse_beforeinfo(_get("beforeinfo", rno=rno, jcd=jcd, hd=hd))


# ------------------------------------------------------------------ 結果
def parse_result(soup: BeautifulSoup) -> dict | None:
    """結果が出ていなければ None。中止なら {'cancelled': True}。"""
    if "レース中止" in soup.get_text():
        return {"cancelled": True}
    units = soup.select("div.grid.is-type2.h-clear > div.grid_unit")
    if len(units) < 3:
        return None
    order = []
    for tbody in units[0].select("div.table1 > table > tbody"):
        tds = tbody.select("tr > td")
        if len(tds) >= 2:
            order.append(_num(_clean(tds[1].get_text()), int))
    trifecta, payout = None, 0
    tbodys = units[2].select("div.table1 > table > tbody")
    if tbodys:
        tr = tbodys[0].select_one("tr")
        if tr:
            tds = tr.select("td")
            if len(tds) >= 3:
                trifecta = _clean(tds[-3].get_text())
                payout = _num(re.sub(r"[^\d]", "", tds[-2].get_text()), int, 0)
    if not order or not trifecta:
        return None
    return {"cancelled": False, "order": order, "trifecta": trifecta, "payout": payout}


def fetch_result(jcd: str, rno: int, hd: str) -> dict | None:
    return parse_result(_get("raceresult", rno=rno, jcd=jcd, hd=hd))
