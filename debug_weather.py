"""風向きアイコン（is-windN）がどの向きの矢印なのかをCSSから調べる。"""
import re
import sys
from kyotei import scraper

jcd, rno, hd = sys.argv[1], int(sys.argv[2]), sys.argv[3]
soup = scraper._get("beforeinfo", rno=rno, jcd=jcd, hd=hd)
out = []
for link in soup.select("link[rel=stylesheet]"):
    href = link.get("href", "")
    url = href if href.startswith("http") else "https://www.boatrace.jp" + href
    try:
        css = scraper._session.get(url, timeout=20).text
    except Exception as e:
        out.append(f"{url} 取得失敗 {e}")
        continue
    hits = re.findall(r"[^{}]*is-wind\d+[^{}]*\{[^}]*\}", css)
    if hits:
        out.append(url)
        out += [" ".join(h.split()) for h in hits[:40]]
text = "\n".join(out) or "is-wind のCSSが見つからない"
for i in range(0, len(text), 3000):
    print("::notice title=W%d::" % i + text[i:i + 3000].replace("%", "%25").replace("\n", "%0A"))
