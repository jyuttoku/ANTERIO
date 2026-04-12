"""
引合い情報の対話フロー管理モジュール

Slackボットが1問ずつ質問し、回答を収集して引合い情報を構築します。
全項目入力後に確認画面を表示し、OKであればBoxへの保存処理へ移行します。
"""

from datetime import datetime
from typing import Optional

# 引合い入力項目の定義（順番に質問される）
QUESTIONS = [
    {
        "key": "company_name",
        "label": "会社名",
        "question": "📋 *会社名*を教えてください。",
        "hint": None,
        "required": True,
    },
    {
        "key": "contact_name",
        "label": "担当者名",
        "question": "👤 *担当者名*（先方）を教えてください。",
        "hint": None,
        "required": True,
    },
    {
        "key": "department",
        "label": "部署名",
        "question": "🏢 *部署名*を教えてください。\n（不明の場合は「不明」と入力）",
        "hint": None,
        "required": False,
    },
    {
        "key": "email",
        "label": "メールアドレス",
        "question": "📧 *メールアドレス*を教えてください。\n（なければ「なし」と入力）",
        "hint": None,
        "required": False,
    },
    {
        "key": "phone",
        "label": "電話番号",
        "question": "📞 *電話番号*を教えてください。\n（なければ「なし」と入力）",
        "hint": None,
        "required": False,
    },
    {
        "key": "inquiry_content",
        "label": "問い合わせ内容",
        "question": "💬 *問い合わせ内容*を教えてください。",
        "hint": "（製品・サービスへの要望、質問などを詳しく）",
        "required": True,
    },
    {
        "key": "budget",
        "label": "予算規模",
        "question": "💰 *予算規模*を教えてください。\n（例：100万円程度、未定、など）",
        "hint": None,
        "required": False,
    },
    {
        "key": "desired_date",
        "label": "希望納期",
        "question": "📅 *希望納期・スケジュール*を教えてください。\n（例：2025年3月末、なるべく早く、未定、など）",
        "hint": None,
        "required": False,
    },
    {
        "key": "sales_person",
        "label": "自社担当者",
        "question": "👥 *自社の対応担当者名*を教えてください。",
        "hint": None,
        "required": True,
    },
    {
        "key": "notes",
        "label": "備考",
        "question": "📝 *備考*があれば入力してください。\n（なければ「なし」と入力）",
        "hint": None,
        "required": False,
    },
]

# 確認・キャンセルのキーワード
YES_WORDS = {"はい", "yes", "y", "ok", "OK", "Yes", "YES"}
NO_WORDS = {"いいえ", "no", "n", "No", "NO", "やり直す", "修正"}


class InquiryFlow:
    """ユーザーごとの引合い入力セッションを管理するクラス"""

    def __init__(self):
        # sessions: {user_id: session_data}
        self.sessions: dict = {}

    # ------------------------------------------------------------------
    # セッション管理
    # ------------------------------------------------------------------

    def start_session(self, user_id: str) -> None:
        """新しい入力セッションを開始する"""
        self.sessions[user_id] = {
            "step": 0,
            "answers": {},
            "state": "questioning",  # "questioning" | "confirming"
            "started_at": datetime.now(),
        }

    def has_active_session(self, user_id: str) -> bool:
        return user_id in self.sessions

    def end_session(self, user_id: str) -> None:
        self.sessions.pop(user_id, None)

    def get_inquiry_data(self, user_id: str) -> dict:
        session = self.sessions.get(user_id)
        return session["answers"].copy() if session else {}

    # ------------------------------------------------------------------
    # 質問・回答処理
    # ------------------------------------------------------------------

    def get_current_question(self, user_id: str) -> str:
        """現在のステップの質問文を返す（進捗付き）"""
        session = self.sessions.get(user_id)
        if not session:
            return ""
        step = session["step"]
        if step >= len(QUESTIONS):
            return ""
        q = QUESTIONS[step]
        total = len(QUESTIONS)
        text = f"[{step + 1}/{total}] {q['question']}"
        if q.get("hint"):
            text += f"\n{q['hint']}"
        return text

    def process_answer(self, user_id: str, answer: str) -> dict:
        """
        ユーザーの回答を処理する。

        Returns:
            dict with keys:
                status: "next_question" | "confirm" | "confirmed" |
                        "restarted" | "invalid_confirm" | "no_session"
                message: 次に送るメッセージ（該当する場合）
                summary: 入力内容サマリ（confirm時）
        """
        session = self.sessions.get(user_id)
        if not session:
            return {"status": "no_session"}

        # --- 確認待ち状態の処理 ---
        if session["state"] == "confirming":
            return self._handle_confirmation(user_id, answer)

        # --- 質問回答の処理 ---
        step = session["step"]
        key = QUESTIONS[step]["key"]
        session["answers"][key] = answer
        session["step"] += 1

        if session["step"] >= len(QUESTIONS):
            # 全質問完了 → 確認画面へ
            session["state"] = "confirming"
            summary = self._build_summary(session["answers"])
            return {
                "status": "confirm",
                "summary": summary,
                "message": (
                    f"{summary}\n\n"
                    "この内容でBoxのExcelに保存しますか？\n"
                    "✅ 保存する場合は「*はい*」\n"
                    "🔄 やり直す場合は「*いいえ*」\n"
                    "と入力してください。"
                ),
            }
        else:
            return {
                "status": "next_question",
                "message": self.get_current_question(user_id),
            }

    def _handle_confirmation(self, user_id: str, answer: str) -> dict:
        """確認（はい/いいえ）への回答を処理する"""
        if answer in YES_WORDS:
            return {"status": "confirmed"}
        elif answer in NO_WORDS:
            # 最初からやり直し
            self.sessions[user_id]["step"] = 0
            self.sessions[user_id]["answers"] = {}
            self.sessions[user_id]["state"] = "questioning"
            return {
                "status": "restarted",
                "message": (
                    "🔄 最初からやり直します。\n\n"
                    + self.get_current_question(user_id)
                ),
            }
        else:
            return {
                "status": "invalid_confirm",
                "message": "「*はい*」または「*いいえ*」で答えてください。",
            }

    # ------------------------------------------------------------------
    # サマリ生成
    # ------------------------------------------------------------------

    def _build_summary(self, answers: dict) -> str:
        lines = ["*【入力内容の確認】*"]
        for q in QUESTIONS:
            value = answers.get(q["key"], "（未入力）")
            lines.append(f"• *{q['label']}*: {value}")
        return "\n".join(lines)
