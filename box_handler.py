"""
Box API + Excel 操作モジュール

BoxサーバーのExcelファイルに引合い情報を追記します。
- ファイルが存在しない場合は新規作成
- 存在する場合はダウンロード → 行追記 → 再アップロード

Box認証方式:
  1. JWT（本番推奨）: BOX_CONFIG_FILE_PATH に JSONファイルのパスを指定
  2. 開発者トークン（テスト用）: BOX_DEVELOPER_TOKEN を指定
"""

import io
import os
import logging
from datetime import datetime
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

logger = logging.getLogger(__name__)

# Excelのヘッダー定義（inquiry_flow.py の QUESTIONS と対応）
EXCEL_HEADERS = [
    "受付日時",
    "会社名",
    "担当者名",
    "部署名",
    "メールアドレス",
    "電話番号",
    "問い合わせ内容",
    "予算規模",
    "希望納期",
    "自社担当者",
    "備考",
]

# inquiry_flow の answers キーと EXCEL_HEADERS の対応
ANSWER_KEYS = [
    "company_name",
    "contact_name",
    "department",
    "email",
    "phone",
    "inquiry_content",
    "budget",
    "desired_date",
    "sales_person",
    "notes",
]

# ヘッダー行のスタイル
HEADER_BG_COLOR = "4472C4"   # 青
HEADER_FONT_COLOR = "FFFFFF"  # 白


class BoxHandler:
    """BoxのExcelファイルへ引合い情報を保存するクラス"""

    def __init__(self):
        self.client = self._build_client()
        self.folder_id: str = os.environ.get("BOX_FOLDER_ID", "0")  # "0" = ルートフォルダ
        self.file_name: str = os.environ.get("BOX_EXCEL_FILE_NAME", "引合い情報.xlsx")
        self._cached_file_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Box クライアント初期化
    # ------------------------------------------------------------------

    def _build_client(self):
        """
        環境変数に応じてBoxクライアントを生成する。
        BOX_DEVELOPER_TOKEN が設定されていればそちらを優先（テスト用）。
        なければ JWT 設定ファイルを使用（本番用）。
        """
        dev_token = os.environ.get("BOX_DEVELOPER_TOKEN")
        if dev_token:
            from boxsdk import OAuth2, Client
            auth = OAuth2(
                client_id=os.environ.get("BOX_CLIENT_ID", ""),
                client_secret=os.environ.get("BOX_CLIENT_SECRET", ""),
                access_token=dev_token,
            )
            logger.info("Box: 開発者トークンで認証")
            return Client(auth)
        else:
            from boxsdk import JWTAuth, Client
            config_path = os.environ.get("BOX_CONFIG_FILE_PATH", "box_config.json")
            auth = JWTAuth.from_settings_file(config_path)
            logger.info(f"Box: JWTで認証 (config: {config_path})")
            return Client(auth)

    # ------------------------------------------------------------------
    # ファイル管理
    # ------------------------------------------------------------------

    def _find_file_id(self) -> Optional[str]:
        """指定フォルダ内の Excel ファイルを探して ID を返す"""
        folder = self.client.folder(folder_id=self.folder_id)
        offset = 0
        limit = 1000
        while True:
            items = folder.get_items(limit=limit, offset=offset)
            item_list = list(items)
            for item in item_list:
                if item.type == "file" and item.name == self.file_name:
                    logger.info(f"既存ファイル発見: {item.name} (id={item.id})")
                    return item.id
            if len(item_list) < limit:
                break
            offset += limit
        return None

    def _create_new_excel(self) -> bytes:
        """ヘッダー付きの新規Excelファイルを生成してbytesで返す"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "引合い情報"

        # ヘッダー行を書き込み
        for col_idx, header in enumerate(EXCEL_HEADERS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = Font(bold=True, color=HEADER_FONT_COLOR)
            cell.fill = PatternFill(
                start_color=HEADER_BG_COLOR,
                end_color=HEADER_BG_COLOR,
                fill_type="solid",
            )
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # 列幅の自動調整（おおよそ）
        col_widths = [18, 20, 15, 15, 25, 15, 40, 15, 18, 15, 30]
        for col_idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[
                openpyxl.utils.get_column_letter(col_idx)
            ].width = width

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _get_or_create_file(self) -> str:
        """ファイルIDを返す。なければ新規作成してIDを返す"""
        if self._cached_file_id:
            return self._cached_file_id

        file_id = self._find_file_id()
        if file_id:
            self._cached_file_id = file_id
            return file_id

        # 新規作成
        logger.info(f"ファイルが存在しないため新規作成: {self.file_name}")
        excel_bytes = self._create_new_excel()
        folder = self.client.folder(folder_id=self.folder_id)
        buf = io.BytesIO(excel_bytes)
        uploaded = folder.upload_stream(buf, self.file_name)
        self._cached_file_id = uploaded.id
        logger.info(f"新規ファイル作成完了 (id={uploaded.id})")
        return uploaded.id

    # ------------------------------------------------------------------
    # 引合い情報の保存
    # ------------------------------------------------------------------

    def save_inquiry(self, answers: dict) -> str:
        """
        引合い情報を Box の Excel に追記する。

        Args:
            answers: inquiry_flow.get_inquiry_data() の戻り値

        Returns:
            BoxのファイルURL (https://app.box.com/file/<id>)
        """
        file_id = self._get_or_create_file()

        # 現在のファイルをダウンロード
        file_content: bytes = self.client.file(file_id).content()
        buf = io.BytesIO(file_content)
        wb = openpyxl.load_workbook(buf)
        ws = wb.active

        # 追記するデータ行を構築
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_data = [now_str] + [answers.get(key, "") for key in ANSWER_KEYS]
        ws.append(row_data)

        # データ行にも基本スタイルを適用
        last_row = ws.max_row
        for col_idx in range(1, len(EXCEL_HEADERS) + 1):
            cell = ws.cell(row=last_row, column=col_idx)
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        # 保存してBoxへアップロード
        upload_buf = io.BytesIO()
        wb.save(upload_buf)
        upload_buf.seek(0)

        updated_file = self.client.file(file_id).update_contents_with_stream(upload_buf)
        logger.info(f"Box保存完了: file_id={updated_file.id}, row={last_row}")

        # キャッシュを更新（IDは変わらないが念のため）
        self._cached_file_id = updated_file.id
        return f"https://app.box.com/file/{updated_file.id}"
