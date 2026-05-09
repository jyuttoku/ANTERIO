"""
引合い情報入力Slack Bot - メインアプリケーション

Slack Bolt (Socket Mode) で動作するBotです。
ユーザーが「引合い」などのキーワードを送信するか /inquiry コマンドを使うと
対話が始まり、全項目を入力後にBoxのExcelファイルへ保存します。

コマンド一覧:
  /inquiry        引合い情報の入力を開始
  /inquiry-list   最近の引合い一覧をBox Excelから表示
  /inquiry-help   使い方を表示

起動方法:
    python app.py

必要な環境変数 (.env ファイルに記載):
    SLACK_BOT_TOKEN  : Slack Bot Token (xoxb-...)
    SLACK_APP_TOKEN  : Slack App-Level Token (xapp-...)
    BOX_CONFIG_FILE_PATH または BOX_DEVELOPER_TOKEN
"""

import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from box_handler import BoxHandler
from inquiry_flow import InquiryFlow

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# アプリ・グローバルオブジェクトの初期化
# ------------------------------------------------------------------
app = App(token=os.environ["SLACK_BOT_TOKEN"])
inquiry_flow = InquiryFlow()
box_handler = BoxHandler()

# 入力を開始するトリガーワード（メッセージ）
START_TRIGGERS = {"引合い", "引き合い", "start", "新規", "登録", "引合登録"}

# キャンセルワード
CANCEL_WORDS = {"キャンセル", "cancel", "やめる", "中止", "止める"}

HELP_TEXT = (
    "*引合い情報入力Bot の使い方*\n\n"
    "*▶ 入力を開始する*\n"
    "　• 「引合い」とメッセージを送る\n"
    "　• または `/inquiry` コマンドを使う\n\n"
    "*📋 入力項目（10項目）*\n"
    "　会社名 / 担当者名 / 部署名 / メール / 電話\n"
    "　問い合わせ内容 / 予算 / 希望納期 / 自社担当者 / 備考\n\n"
    "*📊 最近の引合い一覧を見る*\n"
    "　• `/inquiry-list` コマンドを使う\n\n"
    "*❌ 入力をキャンセルする*\n"
    "　• 入力中に「キャンセル」と送る\n\n"
    "*💾 保存先*\n"
    "　BoxのExcelファイル（引合い情報.xlsx）"
)


# ------------------------------------------------------------------
# スラッシュコマンド
# ------------------------------------------------------------------

@app.command("/inquiry")
def slash_inquiry(ack, body, say):
    """引合い入力を開始するスラッシュコマンド"""
    ack()
    user = body["user_id"]

    if inquiry_flow.has_active_session(user):
        say(
            text="⚠️ すでに入力中です。終わらせる場合は「キャンセル」と入力してください。",
            channel=body["channel_id"],
        )
        return

    inquiry_flow.start_session(user)
    say(
        text=(
            f"<@{user}> 引合い情報の入力を開始します。\n"
            "途中でやめたい場合は「*キャンセル*」と入力してください。\n\n"
            f"{inquiry_flow.get_current_question(user)}"
        ),
        channel=body["channel_id"],
    )


@app.command("/inquiry-list")
def slash_inquiry_list(ack, body, say):
    """BoxのExcelから最近の引合い一覧を表示するスラッシュコマンド"""
    ack()
    channel = body["channel_id"]

    try:
        rows = box_handler.get_recent_inquiries(limit=10)
        if not rows:
            say(text="📭 まだ引合い情報が登録されていません。", channel=channel)
            return

        lines = [f"📊 *直近の引合い情報（最大10件）*\n"]
        for i, row in enumerate(rows, start=1):
            lines.append(
                f"*{i}. {row.get('受付日時', '―')}*\n"
                f"　会社名: {row.get('会社名', '―')} ／ 担当: {row.get('担当者名', '―')}\n"
                f"　内容: {_truncate(row.get('問い合わせ内容', '―'), 40)}\n"
                f"　自社担当: {row.get('自社担当者', '―')}"
            )
        say(text="\n\n".join(lines), channel=channel)

    except Exception as exc:
        logger.exception("inquiry-list エラー")
        say(text=f"❌ 一覧取得中にエラーが発生しました。\n`{exc}`", channel=channel)


@app.command("/inquiry-help")
def slash_inquiry_help(ack, body, say):
    """使い方を表示するスラッシュコマンド"""
    ack()
    say(text=HELP_TEXT, channel=body["channel_id"])


# ------------------------------------------------------------------
# メッセージイベントハンドラ
# ------------------------------------------------------------------

@app.event("message")
def handle_message(body: dict, say, logger) -> None:
    event = body.get("event", {})

    # Bot自身やシステムメッセージは無視
    if event.get("bot_id") or event.get("subtype"):
        return

    user: str = event.get("user", "")
    text: str = (event.get("text") or "").strip()

    if not user or not text:
        return

    # ① ヘルプ
    if text in {"ヘルプ", "help", "使い方", "?", "？"}:
        say(HELP_TEXT)
        return

    # ② キャンセル処理（セッション中のみ）
    if text in CANCEL_WORDS and inquiry_flow.has_active_session(user):
        inquiry_flow.end_session(user)
        say("❌ 入力をキャンセルしました。再度「引合い」と入力すると登録を始められます。")
        return

    # ③ セッション開始
    if any(trigger in text for trigger in START_TRIGGERS):
        if inquiry_flow.has_active_session(user):
            say("⚠️ すでに入力中です。終わらせる場合は「キャンセル」と入力してください。")
            return
        inquiry_flow.start_session(user)
        say(
            f"<@{user}> 引合い情報の入力を開始します。\n"
            "途中でやめたい場合は「*キャンセル*」と入力してください。\n\n"
            f"{inquiry_flow.get_current_question(user)}"
        )
        return

    # ④ セッション中の回答処理
    if not inquiry_flow.has_active_session(user):
        return

    result = inquiry_flow.process_answer(user, text)
    status = result["status"]

    if status == "next_question":
        say(result["message"])

    elif status == "confirm":
        say(result["message"])

    elif status == "invalid_confirm":
        say(result["message"])

    elif status == "restarted":
        say(result["message"])

    elif status == "confirmed":
        inquiry_data = inquiry_flow.get_inquiry_data(user)
        say("⏳ Boxのエクセルに保存中です...")
        try:
            file_url = box_handler.save_inquiry(inquiry_data)
            say(
                f"✅ 保存が完了しました！\n"
                f"📊 <{file_url}|Boxのエクセルファイルを開く>"
            )
            logger.info(f"引合い情報を保存: user={user}, url={file_url}")
        except Exception as exc:
            logger.exception(f"Box保存エラー: user={user}")
            say(
                f"❌ 保存中にエラーが発生しました。\n"
                f"エラー内容: `{exc}`\n"
                "管理者にご連絡ください。"
            )
        finally:
            inquiry_flow.end_session(user)


# ------------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


# ------------------------------------------------------------------
# アプリ起動
# ------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("引合い情報入力Bot を起動します...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
