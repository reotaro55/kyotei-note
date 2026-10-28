"""その日の予想対象レースを決める。

朝・監視・結果集計のどのジョブから呼んでも同じ結果になるので、
有料の買い目をどこにも保存せずに済む（公開リポジトリでも安全）。
"""
from . import config, scraper, scoring

PREFILTER_CLASSES = ("A1", "A2")  # 1号艇がこの級別のレースだけ出走表を取りに行く


def _is_post(venue: dict, rno: int) -> bool:
    if venue["timeframe"] in ("nighter", "midnight"):
        return True
    return rno in config.POST_ROUNDS_DAY


def build_plan(hd: str, log=print) -> dict:
    venues = [v for v in scraper.fetch_index(hd) if not v["cancelled"]]
    log(f"開催場: {len(venues)}場")
    pre, post = [], []
    for v in venues:
        try:
            races = scraper.fetch_raceindex(v["jcd"], hd)
        except scraper.ScrapeError as e:
            log(f"  {v['name']}: 取得失敗 {e}")
            continue
        for r in races:
            if not r["classes"] or r["classes"][0] not in PREFILTER_CLASSES:
                continue
            post_race = _is_post(v, r["rno"])
            if not post_race and r["deadline"] > config.PRE_DEADLINE_LIMIT:
                continue
            try:
                rl = scraper.fetch_racelist(v["jcd"], r["rno"], hd)
            except scraper.ScrapeError as e:
                log(f"  {v['name']}{r['rno']}R: 取得失敗 {e}")
                continue
            score, notes = scoring.pre_score(rl["boats"])
            item = {
                "jcd": v["jcd"], "venue": v["name"], "timeframe": v["timeframe"],
                "grade": v.get("grade", ""), "hd": hd,
                "rno": r["rno"], "deadline": r["deadline"], "title": rl["title"],
                "boats": rl["boats"], "score": score, "notes": notes,
            }
            (post if post_race else pre).append(item)
    log(f"候補: 事前{len(pre)}レース / 展示後{len(post)}レース")
    boats = [b for r in pre + post for b in r["boats"].values()]
    if boats:
        ok = sum(1 for b in boats if b.get("form") is not None)
        log(f"今節成績を読めた選手: {ok}/{len(boats)}")

    pre.sort(key=lambda x: x["score"], reverse=True)
    chosen = [x for x in pre if x["score"] >= config.PRE_MIN_SCORE][: config.PRE_MAX]
    if len(chosen) < config.PRE_MIN:
        chosen = pre[: config.PRE_MIN]
    post.sort(key=lambda x: x["score"], reverse=True)
    post_chosen = [x for x in post if x["score"] >= config.POST_MIN_SCORE][: config.POST_MAX]

    by_time = lambda x: (x["deadline"], x["jcd"])
    return {"pre": sorted(chosen, key=by_time), "post": sorted(post_chosen, key=by_time)}
