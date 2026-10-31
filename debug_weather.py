"""直前情報の水面気象の部分のHTMLを注釈に出す（風向きの読み取り方の調査用）。"""
import sys
from kyotei import scraper

jcd, rno, hd = sys.argv[1], int(sys.argv[2]), sys.argv[3]
soup = scraper._get("beforeinfo", rno=rno, jcd=jcd, hd=hd)
w = soup.select_one("div.weather1")
html = str(w) if w else "weather1なし"
html = " ".join(html.split())
for i in range(0, len(html), 3000):
    print("::notice title=W%d::" % i + html[i:i + 3000].replace("%", "%25"))
