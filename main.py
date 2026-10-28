"""競艇予想note 自動生成

使い方:
  python main.py morning              # 朝: 事前予想を作って送る
  python main.py watch --from 10:00 --to 15:30   # 展示後予想を監視して送る
  python main.py results              # 夜: 的中・回収率をまとめて送る
  python main.py test                 # 通知とChatGPTの接続テスト
"""
import argparse
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from kyotei import config, ledger, notify, planner, scoring, scraper, writer

JST = ZoneInfo("Asia/Tokyo")


def now() -> datetime:
    return datetime.now(JST)


def at(hd: str, hhmm: str) -> datetime:
    return datetime.strptime(hd + hhmm, "%Y%m%d%H:%M").replace(tzinfo=JST)


def log(msg: str):
    # 公開リポジトリのログは誰でも見られるので、買い目や記事本文は出さない
    print(f"[{now():%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------------ 朝
def cmd_morning(hd: str):
    plan = planner.build_plan(hd, log)
    sent = 0
    sent_races = []
    # いちばん自信のあるレース（スコア最上位・締切まで余裕あり）はXで無料公開
    ok = [r for r in plan["pre"] if at(hd, r["deadline"]) > now() + timedelta(minutes=60)]
    free = max(ok, key=lambda r: r["score"]) if ok else None
    if free:
        bets = scoring.pre_bets(free["boats"])
        art = writer.build_article("pre", free, bets)
        notify.send(f"━━━━━━━━━━\n🆓 X無料予想用｜{free['venue']}{free['rno']}R（本日いちばん自信のあるレース）\n"
                    "↓1通目を投稿 → 2通目以降をその投稿へのリプライで続けてください")
        for post in writer.make_x_free(free, bets, art):
            notify.send(post)
        ledger.record(hd, "morning", free, "pre", bets)
    for race in plan["pre"]:
        if free and race is free:
            continue
        if at(hd, race["deadline"]) < now() + timedelta(minutes=10):
            log(f"{race['venue']}{race['rno']}R は締切が近いのでスキップ")
            continue
        bets = scoring.pre_bets(race["boats"])
        article = writer.build_article("pre", race, bets)
        notify.send_article(article, race["deadline"])
        ledger.record(hd, "morning", race, "pre", bets)
        sent_races.append(race)
        sent += 1
        log(f"事前予想 送信: {race['venue']}{race['rno']}R（{race['score']}点）")
    if sent_races:
        notify.send("🐦 ↓X投稿用（本日のまとめ）")
        notify.send(writer.make_x_roundup(hd, sent_races))
    presold = send_presale(hd, plan)
    lines = [f"☀️ 本日の事前予想 {sent}本を送りました。締切前に公開してください。"]
    if plan["post"]:
        lines.append(f"\n🕐 展示後予想（予約版）{presold}本も送りました。展示が出たら追記用が届きます")
        lines += [f"・{r['deadline']} {r['venue']}{r['rno']}R" for r in plan["post"]]
    notify.send("\n".join(lines))


def send_presale(hd: str, plan: dict) -> int:
    """展示後予想の「予約版」を送る（展示後に追記用の文が届く）。"""
    presold = 0
    for race in plan["post"]:
        if at(hd, race["deadline"]) < now() + timedelta(minutes=30):
            continue
        bets = scoring.pre_bets(race["boats"])
        article = writer.build_article("post", race, bets, presale=True)
        notify.send(f"━━━━━━━━━━\n🕐 展示後予想【予約版】｜{config.PRICE_POST}円｜締切 {race['deadline']}\n"
                    "朝のうちに公開OK。展示が出たら「🔄追記用」が届くので、記事の一番下に追記してください")
        notify.send_article(article, race["deadline"])
        presold += 1
    return presold


def cmd_presale(hd: str):
    n = send_presale(hd, planner.build_plan(hd, log))
    notify.send(f"🕐 展示後予想（予約版）を{n}本送りました。展示が出たら追記用が届きます")


# ------------------------------------------------------------------ 展示後
def cmd_watch(hd: str, t_from: str, t_to: str, only: str = "", full: bool = False):
    """only="13-11,13-12" で指定レースだけ監視。full=True なら追記用ではなく記事をまるごと送る。"""
    plan = planner.build_plan(hd, log)
    ov = _override(hd)
    if not only and ov:
        only, full = ov.get("only", ""), bool(ov.get("full"))
        log(f"今日だけの設定を適用: {ov}")
    if only:
        want = {tuple(x.split("-")) for x in only.split(",")}
        found = [r for r in plan["post"] + plan["pre"] if (r["jcd"], str(r["rno"])) in want]
        for jcd, rno in want - {(r["jcd"], str(r["rno"])) for r in found}:
            found.append(_race_direct(hd, jcd, int(rno)))
        plan["post"] = [r for r in found if r]
        log(f"指定レースだけ監視: {[(r['venue'], r['rno']) for r in plan['post']]}")
    pending = [r for r in plan["post"]
               if t_from <= r["deadline"] < t_to
               and at(hd, r["deadline"]) > now() + timedelta(minutes=config.WATCH_GIVEUP_MIN)]
    log(f"監視対象: {len(pending)}レース（締切 {t_from}〜{t_to}）")

    while pending:
        for race in list(pending):
            deadline = at(hd, race["deadline"])
            name = f"{race['venue']}{race['rno']}R"
            if now() < deadline - timedelta(minutes=config.WATCH_START_MIN):
                continue
            if now() > deadline - timedelta(minutes=config.WATCH_GIVEUP_MIN):
                notify.send(f"⚠️ {name}（締切{race['deadline']}）は展示データが間に合わず見送りました")
                log(f"{name}: 時間切れ")
                pending.remove(race)
                continue
            try:
                before = scraper.fetch_beforeinfo(race["jcd"], race["rno"], hd)
            except scraper.ScrapeError as e:
                log(f"{name}: 直前情報の取得失敗 {e}")
                continue
            if not before["ready"]:
                continue
            score, notes, _ = scoring.post_score(race["boats"], before)
            pending.remove(race)
            race = dict(race, score=score, now=f"{now():%H:%M}")
            final = scoring.post_bets(race["boats"], before)
            provisional = scoring.pre_bets(race["boats"])
            if full:
                article = writer.build_article("post", race, final, before, scoring.tenji_ranks(before), notes)
                notify.send_article(article, race["deadline"])
            else:
                notify.send(f"🔄 追記用｜{name}（締切{race['deadline']}）\n↓ 予約版の記事の一番下に追記してください")
                notify.send(writer.make_final_append(race, provisional, final, before, scoring.tenji_ranks(before)))
            ledger.record(hd, "watch" + t_from.replace(":", ""), race, "post", final)
            log(f"展示後の追記 送信: {name}（{score}点）")
        if pending:
            time.sleep(config.WATCH_INTERVAL_SEC)
    log("監視終了")


def _override(hd: str) -> dict:
    """daily_override.json に今日の日付があれば、その日だけの設定を返す。"""
    import json, os
    if os.path.exists("daily_override.json"):
        ov = json.load(open("daily_override.json"))
        if ov.get("date") == hd:
            return ov
    return {}


def _race_direct(hd: str, jcd: str, rno: int) -> dict | None:
    """厳選に入っていないレースを直接取りに行く。"""
    try:
        races = {r["rno"]: r for r in scraper.fetch_raceindex(jcd, hd)}
        rl = scraper.fetch_racelist(jcd, rno, hd)
    except scraper.ScrapeError as e:
        log(f"{jcd}-{rno}: 取得失敗 {e}")
        return None
    score, notes = scoring.pre_score(rl["boats"])
    return {"jcd": jcd, "venue": scraper.VENUES.get(jcd, jcd), "timeframe": "day", "grade": "", "hd": hd,
            "rno": rno, "deadline": races.get(rno, {}).get("deadline", "23:59"), "title": rl["title"],
            "boats": rl["boats"], "score": score, "notes": notes}


def cmd_resend(hd: str, venue: str, from_rno: int):
    """朝に送った事前予想のうち、指定した場・レースの記事から後ろを全部作り直して送る（買い目は同じ）。"""
    jcd = next((k for k, v in scraper.VENUES.items() if v == venue or k == venue.zfill(2)), venue)
    rows = [e for e in ledger.load(hd) if e["kind"] == "pre"]
    if rows:
        rows = rows[1:]  # 先頭はX無料予想用（noteの記事は送っていない）
        targets = [(e["jcd"], e["rno"], e["deadline"]) for e in rows]
    else:
        log("朝の記録が見つからないので厳選をやり直します")
        plan = planner.build_plan(hd, log)
        targets = [(r["jcd"], r["rno"], r["deadline"]) for r in plan["pre"]]
    targets = sorted(set(targets), key=lambda t: (t[2], t[0]))
    start = next((i for i, t in enumerate(targets) if t[0] == jcd and t[1] >= from_rno), None)
    if start is None:
        notify.send(f"⚠️ 今朝の事前予想に{venue}{from_rno}R以降が見つかりませんでした")
        return
    targets = targets[start:]
    log(f"送り直し対象: {len(targets)}レース")
    n = 0
    for t_jcd, rno, _ in targets:
        race = _race_direct(hd, t_jcd, rno)
        if not race:
            continue
        if at(hd, race["deadline"]) < now() + timedelta(minutes=10):
            log(f"{race['venue']}{rno}R は締切が近いのでスキップ")
            continue
        bets = scoring.pre_bets(race["boats"])
        notify.send_article(writer.build_article("pre", race, bets), race["deadline"])
        n += 1
    notify.send(f"✏️ {venue}{from_rno}R以降の事前予想 {n}本を、文章を直して送り直しました（買い目は朝と同じ）。")


# ------------------------------------------------------------------ 結果
def cmd_results(hd: str):
    entries = ledger.load(hd)
    kinds = {e["kind"] for e in entries}
    if kinds != {"pre", "post"}:  # 記録が無い分（手動実行など）は、同じ計算をやり直す
        log(f"記録が無い種類を計算し直します（記録あり: {sorted(kinds)}）")
        entries += [e for e in _recompute_entries(hd) if e["kind"] not in kinds]
    summary = {"pre": [0, 0, 0, 0], "post": [0, 0, 0, 0]}  # レース数, 的中, 投資, 払戻
    hits = []
    for e in entries:
        try:
            res = scraper.fetch_result(e["jcd"], e["rno"], hd)
        except scraper.ScrapeError:
            continue
        if not res or res["cancelled"]:
            continue
        s = summary[e["kind"]]
        s[0] += 1
        s[2] += len(scoring.flat(e["bets"])) * 100
        if scoring.is_hit(e["bets"], res["trifecta"]):
            s[1] += 1
            s[3] += res["payout"]
            hits.append((e, res))

    lines = [f"📊 {hd[4:6]}/{hd[6:]} の成績（各点100円で計算）"]
    for kind, label in (("pre", "事前予想"), ("post", "展示後予想")):
        n, hit, bet, ret = summary[kind]
        rate = f"{hit / n * 100:.0f}%" if n else "-"
        roi = f"{ret / bet * 100:.0f}%" if bet else "-"
        lines.append(f"{label}: {hit}/{n}的中（{rate}）回収率 {roi}")
    for e, res in hits:
        label = "事前" if e["kind"] == "pre" else "展示後"
        lines.append(f"🎯 {label} {e['venue']}{e['rno']}R {res['trifecta']} {res['payout']:,}円")
    notify.send("\n".join(lines))
    for e, res in hits:
        note, x = writer.make_hit_report(e, res)
        notify.send(f"━━━━━━━━━━\n🎯 的中報告｜{e['venue']}{e['rno']}R\n↓ note用 → X用の順に届きます")
        notify.send(note)
        notify.send("🐦 ↓X投稿用（URLを差し替えて投稿）")
        notify.send(x)
    log(f"成績を送信（的中{len(hits)}件）")


def _recompute_entries(hd: str) -> list[dict]:
    plan = planner.build_plan(hd, log)
    out = []
    for race in plan["pre"]:
        out.append(dict(kind="pre", jcd=race["jcd"], rno=race["rno"], venue=race["venue"],
                        grade=race.get("grade", ""), deadline=race["deadline"], hd=hd,
                        bets=scoring.pre_bets(race["boats"])))
    for race in plan["post"]:
        try:
            before = scraper.fetch_beforeinfo(race["jcd"], race["rno"], hd)
        except scraper.ScrapeError:
            continue
        if not before["ready"]:
            continue
        score, _, skip = scoring.post_score(race["boats"], before)
        if skip or score < config.POST_MIN_SCORE:
            continue
        out.append(dict(kind="post", jcd=race["jcd"], rno=race["rno"], venue=race["venue"],
                        grade=race.get("grade", ""), deadline=race["deadline"], hd=hd,
                        bets=scoring.post_bets(race["boats"], before)))
    return out


def cmd_test():
    notify.send("✅ テスト送信です。この通知が届けば設定OK！")
    log("Discordにテスト送信しました")
    if config.OPENAI_API_KEY:
        sample = {"venue": "サンプル", "rno": 1, "deadline": "10:00", "title": "", "score": 80,
                  "notes": ["テスト"], "boats": {
                      w: {"waku": w, "name": f"サンプル選手{w}", "class": "A1" if w == 1 else "B1",
                          "win_rate": 7.5 - w * 0.5, "local_win_rate": 7.0, "avg_st": 0.15,
                          "motor2": 40.0 - w, "F": 0} for w in range(1, 7)}}
        notify.send("👇 貼り付け練習用のサンプル記事です（noteで余白の位置に有料ラインが収まるか確認してください）")
        notify.send_article(writer.build_article("pre", sample, scoring.pre_bets(sample["boats"])), "10:00")
        facts = writer._facts("pre", sample, scoring.pre_bets(sample["boats"]))
        if writer._llm(facts):
            notify.send(f"✅ ChatGPT（{config.OPENAI_MODEL}）との接続もOK！")
        else:
            notify.send(f"⚠️ ChatGPT（{config.OPENAI_MODEL}）に接続できませんでした（記事は定型文で作られます）\n"
                        f"理由: {writer.LAST_ERROR}")
    else:
        notify.send("ℹ️ OpenAIのキーは未設定です（記事は定型文で作られます）")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["morning", "presale", "watch", "results", "test", "resend"])
    p.add_argument("--date", help="YYYYMMDD（省略で今日）")
    p.add_argument("--from", dest="t_from", default="00:00")
    p.add_argument("--to", dest="t_to", default="24:00")
    p.add_argument("--only", default="", help="例: 13-11,13-12（場コード-レース番号）")
    p.add_argument("--full", action="store_true", help="展示後に記事をまるごと送る")
    p.add_argument("--venue", default="", help="resend用: 場名（例: 尼崎）")
    p.add_argument("--from-rno", type=int, default=1, help="resend用: 何Rから")
    a = p.parse_args()
    hd = a.date or now().strftime("%Y%m%d")
    try:
        if a.command == "morning":
            cmd_morning(hd)
        elif a.command == "watch":
            cmd_watch(hd, a.t_from, a.t_to, a.only, a.full)
        elif a.command == "presale":
            cmd_presale(hd)
        elif a.command == "resend":
            cmd_resend(hd, a.venue, a.from_rno)
        elif a.command == "results":
            cmd_results(hd)
        else:
            cmd_test()
    except scraper.ScrapeError as e:
        notify.send(f"❌ 公式サイトからの取得に失敗しました（{a.command}）。時間をおいて再実行してください。")
        log(f"取得エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
