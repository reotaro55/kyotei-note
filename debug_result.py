"""結果ページが読めないときの調査用。ページの構造を注釈に出す。"""
import sys
from kyotei import scraper

jcd, rno, hd = sys.argv[1], int(sys.argv[2]), sys.argv[3]
soup = scraper._get("raceresult", rno=rno, jcd=jcd, hd=hd)
units = soup.select("div.grid.is-type2.h-clear > div.grid_unit")
lines = [f"units={len(units)} parse={scraper.parse_result(soup)}"]
for i, u in enumerate(units[:4]):
    lines.append(f"[unit{i}] " + " ".join(u.get_text(" ").split())[:400])
for g in soup.select("div.grid")[:12]:
    lines.append("grid class=" + " ".join(g.get("class", [])) + " units=" + str(len(g.select(":scope > div.grid_unit"))))
print("::notice title=DEBUG::" + "%0A".join(l.replace("%", "%25") for l in lines))
