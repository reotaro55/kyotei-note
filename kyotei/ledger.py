"""その日に実際に送った買い目の記録（的中判定・的中報告用）。

bets/YYYYMMDD_<label>.json に保存し、GitHub Actions のキャッシュで夜のジョブに渡す。
キャッシュは外部から中身を見られないので、公開リポジトリでも締切前の買い目は漏れない。
"""
import glob
import json
import os

DIR = "bets"


def record(hd: str, label: str, race: dict, kind: str, bets: dict):
    os.makedirs(DIR, exist_ok=True)
    path = os.path.join(DIR, f"{hd}_{label}.json")
    rows = json.load(open(path)) if os.path.exists(path) else []
    rows.append({
        "kind": kind, "jcd": race["jcd"], "rno": race["rno"], "venue": race["venue"],
        "grade": race.get("grade", ""), "deadline": race["deadline"], "hd": hd, "bets": bets,
    })
    json.dump(rows, open(path, "w"), ensure_ascii=False)


def load(hd: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(DIR, f"{hd}_*.json"))):
        rows += json.load(open(path))
    return rows
