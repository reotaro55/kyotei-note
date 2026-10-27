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

from kyotei import config, notify, planner, scoring, scraper, writer

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
    for race in plan["pre"]:
        if at(hd, race["deadline"]) < now() + timedelta(minutes=10):
            log(f"{race['venue']}{race['rno']}R は締切が近いのでスキップ")
            continue
        bets = scoring.pre_bets(race["boats"])
        article = writer.build_article("pre", race, bets)
        notify.send_article(article, race["deadline"])
        sent += 1
        log(f"事前予想 送信: {race['venue']}{race['rno']}R（{race['score']}点）")
    lines = [f"☀️ 本日の事前予想 {sent}本を送りました。締切前に公開してください。"]
    if plan["post"]:
        lines.append("\n🔍 展示後予想の対象（展示が出たら自動で届きます）")
        lines += [f"・{r['deadline']} {r['venue']}{r['rno']}R" for r in plan["post"]]
    notify.send("\n".join(lines))


# ------------------------------------------------------------------ 展示後
def cmd_watch(hd: str, t_from: str, t_to: str):
    plan = planner.build_plan(hd, log)
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
            score, notes, skip = scoring.post_score(race["boats"], before)
            pending.remove(race)
            if skip or score < config.POST_MIN_SCORE:
                reason = " / ".join(notes[-2:])
                notify.send(f"🙅 {name}（締切{race['deadline']}）は展示を見て見送り推奨。\n理由: {reason}")
                log(f"{name}: 見送り（{score}点）")
                continue
            race = dict(race, score=score)
            bets = scoring.post_bets(race["boats"], before)
            article = writer.build_article(
                "post", race, bets, before, scoring.tenji_ranks(before), notes)
            notify.send_article(article, race["deadline"])
            log(f"展示後予想 送信: {name}（{score}点）")
        if pending:
            time.sleep(config.WATCH_INTERVAL_SEC)
    log("監視終了")


# ------------------------------------------------------------------ 結果
def cmd_results(hd: str):
    plan = planner.build_plan(hd, log)
    summary = {}
    hits = []
    for kind in ("pre", "post"):
        n = bet = ret = hit = 0
        for race in plan[kind]:
            if kind == "pre":
                bets = scoring.pre_bets(race["boats"])
            else:
                try:
                    before = scraper.fetch_beforeinfo(race["jcd"], race["rno"], hd)
                except scraper.ScrapeError:
                    continue
                if not before["ready"]:
                    continue
                score, _, skip = scoring.post_score(race["boats"], before)
                if skip or score < config.POST_MIN_SCORE:
                    continue
                bets = scoring.post_bets(race["boats"], before)
            try:
                res = scraper.fetch_result(race["jcd"], race["rno"], hd)
            except scraper.ScrapeError:
                continue
            if not res or res["cancelled"]:
                continue
            n += 1
            bet += len(bets) * 100
            if scoring.is_hit(bets, res["trifecta"]):
                hit += 1
                ret += res["payout"]
                label = "事前" if kind == "pre" else "展示後"
                hits.append(f"🎯 {label} {race['venue']}{race['rno']}R {res['trifecta']} {res['payout']:,}円")
        summary[kind] = (n, hit, bet, ret)

    lines = [f"📊 {hd[4:6]}/{hd[6:]} の成績（各点100円で計算）"]
    for kind, label in (("pre", "事前予想"), ("post", "展示後予想")):
        n, hit, bet, ret = summary[kind]
        rate = f"{hit / n * 100:.0f}%" if n else "-"
        roi = f"{ret / bet * 100:.0f}%" if bet else "-"
        lines.append(f"{label}: {hit}/{n}的中（{rate}）回収率 {roi}")
    lines += hits
    notify.send("\n".join(lines))
    log("成績を送信")


def cmd_test():
    notify.send("✅ テスト送信です。この通知が届けば設定OK！")
    log("Discordにテスト送信しました")
    if config.OPENAI_API_KEY:
        sample = {"venue": "テスト", "rno": 1, "deadline": "10:00", "title": "", "score": 80,
                  "notes": ["テスト"], "boats": {
                      w: {"waku": w, "name": f"選手{w}", "class": "A1" if w == 1 else "B1",
                          "win_rate": 7.5 - w * 0.5, "local_win_rate": 7.0, "avg_st": 0.15,
                          "motor2": 40.0, "F": 0} for w in range(1, 7)}}
        facts = writer._facts("pre", sample, ["1-2-3"])
        if writer._llm(facts):
            notify.send(f"✅ ChatGPT（{config.OPENAI_MODEL}）との接続もOK！")
        else:
            notify.send(f"⚠️ ChatGPT（{config.OPENAI_MODEL}）に接続できませんでした。"
                        "キー・支払い設定・モデル名を確認してください（記事は定型文で作られます）")
    else:
        notify.send("ℹ️ OpenAIのキーは未設定です（記事は定型文で作られます）")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["morning", "watch", "results", "test"])
    p.add_argument("--date", help="YYYYMMDD（省略で今日）")
    p.add_argument("--from", dest="t_from", default="00:00")
    p.add_argument("--to", dest="t_to", default="24:00")
    a = p.parse_args()
    hd = a.date or now().strftime("%Y%m%d")
    try:
        if a.command == "morning":
            cmd_morning(hd)
        elif a.command == "watch":
            cmd_watch(hd, a.t_from, a.t_to)
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
