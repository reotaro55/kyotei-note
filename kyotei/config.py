"""設定まとめ。数字を変えたいときはここだけ触ればOK。"""
import os

# ---- 価格（記事のヘッダーに表示） ----
PRICE_PRE = 200    # 事前予想
PRICE_POST = 500   # 展示後予想

# ---- 本数 ----
PRE_MAX = 15       # 事前予想の最大本数
PRE_MIN = 10       # スコアが低くてもこの本数までは出す
POST_MAX = 15      # 展示後予想の最大本数（昼10〜12R＋ナイター合計）

# ---- 対象レースの振り分け ----
PRE_DEADLINE_LIMIT = "15:00"   # 事前予想はこの時刻までに締切のレース
POST_ROUNDS_DAY = (10, 11, 12) # 昼開催で展示後予想にするレース番号

# ---- スコアの足切り（0〜100点） ----
PRE_MIN_SCORE = 55
POST_MIN_SCORE = 55

# ---- 買い目 ----
# 本命3点＋穴3点の6点（kyotei/scoring.py の make_bets）

# ---- 展示後予想の監視 ----
WATCH_START_MIN = 40   # 締切の何分前から展示データを見に行くか
WATCH_GIVEUP_MIN = 4   # 締切の何分前までに出なければ諦めるか
WATCH_INTERVAL_SEC = 90
# False: 展示が出たら記事をまるごと1レース1本で送る（予約版は朝に送らない）
# True : 朝に予約版を送り、展示後は「追記用」だけ送る（旧方式）
POST_PRESALE = False

# ---- 通信 ----
REQUEST_SLEEP_SEC = 1.0   # 公式サイトへの負荷を抑えるための待ち時間

# ---- 外部サービス（GitHubのSecretsで設定） ----
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "") or "gpt-6-luna"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
# フォーラムチャンネルのウェブフック。設定すると展示後予想を1本ずつ別の投稿（スレッド）に分けて送る（事前予想はいつものチャンネル）
DISCORD_FORUM_WEBHOOK_URL = os.environ.get("DISCORD_FORUM_WEBHOOK_URL", "")
# 無料予想（X投稿用）を送るチャンネルのウェブフック。未設定ならいつものチャンネル
DISCORD_FREE_WEBHOOK_URL = os.environ.get("DISCORD_FREE_WEBHOOK_URL", "")

# ---- 記事末尾に必ず付ける注意書き ----
DISCLAIMER = (
    "※本予想は的中を保証するものではありません。"
    "舟券の購入はご自身の判断と責任で、20歳以上の方のみお願いします。"
)
