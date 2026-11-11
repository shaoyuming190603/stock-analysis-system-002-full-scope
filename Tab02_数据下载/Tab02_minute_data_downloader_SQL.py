# -*- coding: utf-8 -*-
"""
Tab02_minute_data_downloader_SQL.py
===================================
Tab02_数据下载 标签页：从 tushare pro 提取分钟数据 → 写入 SQL Server LocalDB。

数据库连接设置（业务规定）：
  服务器   ： (localdb)\\MSSQLLocalDB
  认证     ： Windows 身份验证 (Trusted_Connection=yes)
  数据库   ： 股票数据
  加密     ： 强制（客户端使用 TrustServerCertificate=yes 接受 LocalDB 自签名证书）
  MDF 文件 ： 由 txt_SQL_path_DB_name 指定
              例：D:\\ToolsInstall\\SQL2025\\myData\\股票数据\\股票数据.mdf

业务要点：
  1) 通过 stk_mins 获取 ts_code 的 1min / 5min / 15min / 30min / 60min 数据；
  2) 仅保留 8 个字段：ts_code, trade_time, close, open, high, low, vol, amount；
  3) 数据表名自动生成：minute_data_<ts_code[:6]>_<freq>；
  4) 表不存在→创建（trade_time 主键，DATETIME2(0)）；存在→逐行检查 trade_time 去重；
  5) 分批（5000 行/批）executemany 写入，加速插入；
  6) pushBttn_abort → 置中止标志，非关窗；
  7) pushBttn_SQL_InitialPath 由 main.py 统一处理（选 *.mdf → 写入 txt_SQL_path_DB_name
     并立即持久化到 app_persist.json）。本模块仅保留 on_sql_initial_path_clicked 作为
     备用接口，不在 _connect_signals 中自动连接，避免与 main.py 重复连接造成双弹窗；
  8) pushBttn_InitialPath_download_file   → 选文件夹，构造 minute_data_<code>_<freq>，
     写入 txt_path_file；
  9) txt_SQL_path_DB_name / txt_SQL_table_name / txt_path_file 由 main.py 持久化；
 10) txt_SQL_table_name 与 txt_path_file 的文件名部分随 ts_code / freq 自动联动。

进度提示（本次已加入）：
  * 主批次循环 —— 每批开始时输出日志形如：
      [180/181] 2026-10-01 ~ 2026-10-31  limit=155  |
      已运行1时23分45秒，预计剩余1分05秒，预计总计181个批次全部完成时间：15时30分完成。
  * 数据写入分块循环 —— 每块写完后输出日志形如：
      写入分块 [2/3] 已运行0分12秒，预计剩余0分06秒，预计总计3个写入分块全部完成时间：15时30分完成。
  * 主窗体左下方状态栏 —— 每批 / 每分块刷新：
      已用时0时12分34秒，预计完成时间15时30分45秒
  * 任务完成 / 中止的弹窗 —— 追加：
      总用时    ：0时15分22秒
"""

import os
import re
import json
import calendar
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import tushare as ts

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QMessageBox, QApplication, QFileDialog, QStatusBar,
)

# pyodbc 延迟导入（便于给出清晰错误提示）
try:
    import pyodbc  # type: ignore
    _PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None
    _PYODBC_AVAILABLE = False


# ==============================================================
# 常量
# ==============================================================
DEFAULT_LIMIT         = 7471
MAX_API_LIMIT         = 8000
SPAN_THRESHOLD_DAYS   = 31
INSERT_CHUNK_SIZE     = 5000

FREQ_FACTOR_MAP = {
    "1min":  241,
    "5min":  49,
    "15min": 17,
    "30min": 9,
    "60min": 5,
}

API_FIELDS = ["ts_code", "trade_time", "close", "open", "high", "low", "vol", "amount"]

# 需要随 Tab02 SQL 自身一起保存的输入项（txt_SQL_path_DB_name / txt_SQL_table_name /
# txt_path_file 由 main.py 的 app_persist.json 统一保存）
PERSIST_KEYS = [
    "txt_ts_code", "txt_freq", "txt_start_date", "txt_end_date",
    "txt_factor", "txt_limit", "txt_offset",
]

PERSIST_FILE_NAME = "Tab02_SQL_settings.json"
LOG_FILE_NAME     = "Tab02_SQL_download.log"

# 默认 MDF 路径（业务示例）
DEFAULT_SQL_DB_PATH = r"D:\ToolsInstall\SQL2025\myData\股票数据\股票数据.mdf"

# SQL Server 连接参数（业务规定）
SQL_SERVER_INSTANCE  = r"(localdb)\MSSQLLocalDB"
SQL_DATABASE_NAME    = "股票数据"
SQL_SCHEMA           = "dbo"

# 表名规则：minute_data_<6位 code>_<freq>
TABLE_NAME_RE = re.compile(r"^minute_data_[A-Za-z0-9]+_[A-Za-z0-9]+$")

# ODBC 驱动探测顺序
ODBC_DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]


# ==============================================================
# 小工具函数
# ==============================================================
def widget_get_text(widget):
    if widget is None:
        return ""
    if hasattr(widget, "toPlainText"):
        return widget.toPlainText().strip()
    if hasattr(widget, "text"):
        return str(widget.text()).strip()
    return ""


def widget_set_text(widget, value):
    if widget is None:
        return
    value = "" if value is None else str(value)
    if hasattr(widget, "setPlainText"):
        widget.setPlainText(value)
    elif hasattr(widget, "setText"):
        widget.setText(value)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def format_date(d):
    return d.strftime("%Y-%m-%d") if d else ""


def split_by_month(start: date, end: date):
    segments = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        seg_end = min(month_end, end)
        segments.append((cursor, seg_end))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return segments


def make_table_name(ts_code: str, freq: str) -> str:
    """表名：minute_data_<6位 code>_<freq>"""
    code = (ts_code or "")[:6]
    code = re.sub(r"[^A-Za-z0-9]", "", code) or "unknown"
    freq_s = re.sub(r"[^A-Za-z0-9]", "", str(freq or "")) or "unknown"
    return f"minute_data_{code}_{freq_s}"


def make_create_table_sql(table_name: str) -> str:
    """SQL Server 建表语句（trade_time 主键，DATETIME2(0) 秒级足够分钟数据）。"""
    return (
        f"CREATE TABLE [{SQL_SCHEMA}].[{table_name}] ("
        f"  [ts_code]    NVARCHAR(20) NOT NULL, "
        f"  [trade_time] DATETIME2(0) NOT NULL, "
        f"  [close]      FLOAT NULL, "
        f"  [open]       FLOAT NULL, "
        f"  [high]       FLOAT NULL, "
        f"  [low]        FLOAT NULL, "
        f"  [vol]        FLOAT NULL, "
        f"  [amount]     FLOAT NULL, "
        f"  CONSTRAINT [PK_{table_name}] PRIMARY KEY CLUSTERED ([trade_time] ASC)"
        f")"
    )


def make_insert_sql(table_name: str) -> str:
    cols = ", ".join(f"[{c}]" for c in API_FIELDS)
    placeholders = ", ".join(["?"] * len(API_FIELDS))
    return (
        f"INSERT INTO [{SQL_SCHEMA}].[{table_name}] ({cols}) VALUES ({placeholders})"
    )


def _to_py_value(v):
    """把 pandas/numpy 值规范成 pyodbc 可接受的 Python 值；NaN/NaT → None。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, pd.Timestamp):
        dt = v.to_pydatetime()
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            pass
    return v


# --------------------------------------------------------------
# 进度/耗时格式化工具
# --------------------------------------------------------------
def _format_duration(seconds: float) -> str:
    """把秒数格式化为 'X时X分X秒' / 'X分X秒' / 'X秒'（智能省略前导零）。"""
    try:
        seconds = int(max(0.0, round(float(seconds))))
    except Exception:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}时{m}分{s}秒"
    if m > 0:
        return f"{m}分{s}秒"
    return f"{s}秒"


def _format_hms(seconds: float) -> str:
    """强制输出 'X时XX分XX秒'，用于 '总用时' / 状态栏 '已用时'。"""
    try:
        seconds = int(max(0.0, round(float(seconds))))
    except Exception:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}时{m:02d}分{s:02d}秒"


def _format_eta(eta_dt: datetime, now_dt: datetime) -> str:
    """预计完成时间（用于日志行）：同一天用 'HH时MM分'，跨天加 'MM-DD ' 前缀。"""
    try:
        if eta_dt.date() == now_dt.date():
            return eta_dt.strftime("%H时%M分")
        return eta_dt.strftime("%m-%d %H时%M分")
    except Exception:
        return "未知"


# ==============================================================
# 主控制器
# ==============================================================
class Tab02MinuteDataDownloaderSQL(QObject):
    log_signal      = Signal(str)
    finished_signal = Signal()
    error_signal    = Signal(str)

    def __init__(self, ui, parent_window=None, api_token=None):
        super().__init__(parent_window)
        self.ui            = ui
        self.parent_window = parent_window
        self.api_token     = api_token or "8197a7e40501f6409bfc58a5af2e0fc70e4fac6da9df6ff82c28db61"

        self._orig_start_date = ""
        self._orig_end_date   = ""
        self._logger          = None
        self._abort_requested = False

        self._persist_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            PERSIST_FILE_NAME,
        )

        self._connect_signals()
        self._load_settings()
        self._setup_initial_state()
        # 加载持久化后，强制按 ts_code / freq 同步一次表名与 txt_path_file
        self._auto_generate_table_name()
        self._auto_generate_path_file()

    # ----------------------------------------------------------
    # 初始化
    # ----------------------------------------------------------
    def _connect_signals(self):
        btn = getattr(self.ui, "pushBttn_Generat_minute_List_SQL", None)
        if btn is not None:
            btn.pressed.connect(self.on_generate_clicked)

        abort_btn = getattr(self.ui, "pushBttn_abort", None)
        if abort_btn is not None:
            abort_btn.pressed.connect(self.on_abort_clicked)
        else:
            print("[Tab02-SQL] 警告：未找到 pushBttn_abort 控件")

        # ----------------------------------------------------------
        # 注意：pushBttn_SQL_InitialPath 已改由 main.py 统一处理
        #      （打开 *.mdf 文件 → 写入 txt_SQL_path_DB_name → 立即持久化），
        #      此处不再自动连接，避免双弹窗。
        #      self.on_sql_initial_path_clicked 保留为备用接口，可按需手动连接。
        # ----------------------------------------------------------

        # 需求：选择下载文件所在文件夹 → 写入 txt_path_file
        dl_path_btn = getattr(self.ui, "pushBttn_InitialPath_download_file", None)
        if dl_path_btn is not None:
            dl_path_btn.pressed.connect(self.on_initial_path_download_file_clicked)
        else:
            print("[Tab02-SQL] 警告：未找到 pushBttn_InitialPath_download_file 控件")

        # 联动：ts_code / freq 变化 → 同步 table_name 与 txt_path_file
        for wname in ("txt_ts_code", "txt_freq"):
            w = getattr(self.ui, wname, None)
            if w is not None and hasattr(w, "textChanged"):
                w.textChanged.connect(self._auto_generate_table_name)
                w.textChanged.connect(self._auto_generate_path_file)

        # 联动：freq / 日期
        freq_w = getattr(self.ui, "txt_freq", None)
        if freq_w is not None:
            if hasattr(freq_w, "textChanged"):
                freq_w.textChanged.connect(self._on_freq_changed)
            if hasattr(freq_w, "editingFinished"):
                freq_w.editingFinished.connect(self._on_freq_changed)

        for wname in ("txt_start_date", "txt_end_date"):
            w = getattr(self.ui, wname, None)
            if w is not None and hasattr(w, "editingFinished"):
                w.editingFinished.connect(self._on_date_changed)

        # 文本框内容变化时立即持久化（需求："内容更新后自动保存"）
        for wname in ("txt_SQL_path_DB_name", "txt_SQL_table_name", "txt_path_file"):
            w = getattr(self.ui, wname, None)
            if w is None and wname == "txt_SQL_path_DB_name":
                w = getattr(self.ui, "txt_SQL_path", None)
            if w is not None:
                if hasattr(w, "textChanged"):
                    w.textChanged.connect(self._persist_via_parent)
                elif hasattr(w, "textEdited"):
                    w.textEdited.connect(self._persist_via_parent)

    def _persist_via_parent(self, *args, **kwargs):
        if self.parent_window is not None and hasattr(self.parent_window, "_save_persist"):
            try:
                self.parent_window._save_persist()
            except Exception as e:
                print(f"[Tab02-SQL] 持久化失败: {e}")

    def _setup_initial_state(self):
        self._orig_start_date = widget_get_text(getattr(self.ui, "txt_start_date", None))
        self._orig_end_date   = widget_get_text(getattr(self.ui, "txt_end_date", None))

        freq = widget_get_text(getattr(self.ui, "txt_freq", None))
        if freq in FREQ_FACTOR_MAP:
            widget_set_text(getattr(self.ui, "txt_factor", None), str(FREQ_FACTOR_MAP[freq]))

        widget_set_text(getattr(self.ui, "txt_limit", None), str(DEFAULT_LIMIT))
        self._recalc_limit_for_current_dates()

        # txt_SQL_path_DB_name 为空时补默认值（兼容旧控件名 txt_SQL_path）
        # 注意：若 main.py 已从 app_persist.json 加载了用户上次选择，则此处不会被覆盖。
        for wname in ("txt_SQL_path_DB_name", "txt_SQL_path"):
            w = getattr(self.ui, wname, None)
            if w is not None and not widget_get_text(w):
                widget_set_text(w, DEFAULT_SQL_DB_PATH)
                break

    # ----------------------------------------------------------
    # 中止
    # ----------------------------------------------------------
    def on_abort_clicked(self):
        self._abort_requested = True
        self._log("*** 用户点击 pushBttn_abort，已置中止标志 ***")

    # ----------------------------------------------------------
    # 自动生成 txt_SQL_table_name
    # ----------------------------------------------------------
    def _auto_generate_table_name(self, *args):
        if not hasattr(self.ui, "txt_SQL_table_name"):
            return
        ts_code = widget_get_text(getattr(self.ui, "txt_ts_code", None))
        freq    = widget_get_text(getattr(self.ui, "txt_freq", None))
        if not ts_code or not freq:
            return
        new_name = make_table_name(ts_code, freq)
        current  = widget_get_text(self.ui.txt_SQL_table_name)
        if new_name != current:
            widget_set_text(self.ui.txt_SQL_table_name, new_name)

    # ----------------------------------------------------------
    # txt_path_file 联动（保留文件夹，替换文件名部分）
    # ----------------------------------------------------------
    def _auto_generate_path_file(self, *args):
        w = getattr(self.ui, "txt_path_file", None)
        if w is None:
            return
        ts_code = widget_get_text(getattr(self.ui, "txt_ts_code", None))
        freq    = widget_get_text(getattr(self.ui, "txt_freq", None))
        if not ts_code or not freq:
            return
        new_filename = make_table_name(ts_code, freq)
        current = widget_get_text(w)
        if current:
            folder = os.path.dirname(current)
            new_value = os.path.join(folder, new_filename) if folder else new_filename
        else:
            new_value = new_filename
        if new_value != current:
            widget_set_text(w, new_value)

    # ----------------------------------------------------------
    # pushBttn_InitialPath_download_file 选文件夹 → txt_path_file
    # ----------------------------------------------------------
    def on_initial_path_download_file_clicked(self):
        w = getattr(self.ui, "txt_path_file", None)
        if w is None:
            QMessageBox.warning(self.parent_window, "提示", "未找到 txt_path_file 控件")
            return

        ts_code = widget_get_text(getattr(self.ui, "txt_ts_code", None))
        freq    = widget_get_text(getattr(self.ui, "txt_freq", None))
        if not ts_code or not freq:
            QMessageBox.warning(
                self.parent_window, "提示",
                "请先填写 txt_ts_code 与 txt_freq，再选择下载文件夹。"
            )
            return

        current = widget_get_text(w)
        initial = os.path.dirname(current) if current else ""
        if not initial or not os.path.isdir(initial):
            initial = ""

        folder = QFileDialog.getExistingDirectory(
            self.parent_window,
            "选择下载文件所在文件夹",
            initial,
        )
        if not folder:
            return

        filename = make_table_name(ts_code, freq)
        full_path = os.path.join(folder, filename)
        widget_set_text(w, full_path)
        print(f"[Tab02-SQL] 下载文件完整路径：{full_path}")

        self._persist_via_parent()

    # ----------------------------------------------------------
    # pushBttn_SQL_InitialPath 选 MDF 文件 → txt_SQL_path_DB_name
    #   （备用接口；现已由 main.py 统一处理，此处不再自动连接）
    # ----------------------------------------------------------
    def on_sql_initial_path_clicked(self):
        target = getattr(self.ui, "txt_SQL_path_DB_name", None) \
                 or getattr(self.ui, "txt_SQL_path", None)
        if target is None:
            QMessageBox.warning(self.parent_window, "提示", "未找到 txt_SQL_path_DB_name 控件")
            return

        current = widget_get_text(target)
        if current and os.path.isfile(current):
            initial = current
        elif current and os.path.isdir(current):
            initial = os.path.join(current, "股票数据.mdf")
        else:
            initial = DEFAULT_SQL_DB_PATH

        fname, _ = QFileDialog.getOpenFileName(
            self.parent_window,
            "选择 SQL Server 数据文件（.mdf）",
            initial,
            "SQL Server 数据文件 (*.mdf);;所有文件 (*.*)",
        )
        if not fname:
            return

        widget_set_text(target, os.path.normpath(fname))
        print(f"[Tab02-SQL] 数据库文件路径已更新为：{fname}")
        self._persist_via_parent()

    # ----------------------------------------------------------
    # 控件联动：freq / 日期
    # ----------------------------------------------------------
    def _on_freq_changed(self, *args):
        freq = widget_get_text(getattr(self.ui, "txt_freq", None))
        if freq in FREQ_FACTOR_MAP:
            widget_set_text(getattr(self.ui, "txt_factor", None), str(FREQ_FACTOR_MAP[freq]))
        self._recalc_limit_for_current_dates()
        self._auto_generate_table_name()
        self._auto_generate_path_file()

    def _on_date_changed(self, *args):
        self._recalc_limit_for_current_dates()

    def _recalc_limit_for_current_dates(self):
        sd = parse_date(widget_get_text(getattr(self.ui, "txt_start_date", None)))
        ed = parse_date(widget_get_text(getattr(self.ui, "txt_end_date", None)))
        freq   = widget_get_text(getattr(self.ui, "txt_freq", None))
        factor = FREQ_FACTOR_MAP.get(freq)

        if sd is None or ed is None or sd > ed or factor is None:
            widget_set_text(getattr(self.ui, "txt_limit", None), str(DEFAULT_LIMIT))
            return

        span = (ed - sd).days + 1
        if span <= SPAN_THRESHOLD_DAYS:
            widget_set_text(getattr(self.ui, "txt_limit", None), str(DEFAULT_LIMIT))
            return

        monthly = []
        for (ms, me) in split_by_month(sd, ed):
            days = (me - ms).days + 1
            monthly.append(days * factor)
        if monthly:
            widget_set_text(getattr(self.ui, "txt_limit", None), str(max(monthly)))

    # ----------------------------------------------------------
    # 日志
    # ----------------------------------------------------------
    def _init_logger(self):
        log_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            pass
        log_path = os.path.join(log_dir, LOG_FILE_NAME)

        logger = logging.getLogger("Tab02MinuteDataDownloaderSQL")
        logger.setLevel(logging.INFO)
        for h in list(logger.handlers):
            if isinstance(h, logging.FileHandler):
                logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass

        try:
            fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        except Exception as e:
            print(f"[Tab02-SQL] 无法创建日志文件: {e}")
            self._logger = None
            return

        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)
        self._logger = logger
        self._log("=" * 60)
        self._log(f"log 文件位置: {log_path}")

    def _log(self, msg):
        if self._logger:
            try:
                self._logger.info(msg)
            except Exception:
                pass
        print(f"[Tab02-SQL] {msg}")
        try:
            self.log_signal.emit(msg)
        except Exception:
            pass

    # ----------------------------------------------------------
    # 主窗体左下方状态栏更新
    #   优先 QMainWindow.statusBar()（QStatusBar.showMessage 默认显示在左侧）
    #   若不存在，则回退到 QStatusBar 子控件查找，再回退到常见 label
    # ----------------------------------------------------------
    def _update_main_status(self, text: str):
        if self.parent_window is None:
            return
        try:
            sb = None
            if hasattr(self.parent_window, "statusBar"):
                try:
                    sb = self.parent_window.statusBar()
                except Exception:
                    sb = None
            if sb is None:
                try:
                    sb = self.parent_window.findChild(QStatusBar)
                except Exception:
                    sb = None
            if sb is not None:
                sb.showMessage(text)
                QApplication.processEvents()
                return

            # 退路：常见状态 label 名称
            for name in (
                "label_status", "lbl_status", "label_info_status",
                "status_label", "label_bottom_status", "label_progress",
                "label_message", "lbl_message",
            ):
                w = getattr(self.parent_window, name, None)
                if w is not None and hasattr(w, "setText"):
                    w.setText(text)
                    QApplication.processEvents()
                    return
        except Exception as e:
            print(f"[Tab02-SQL] 更新主窗体状态栏失败: {e}")

    def _clear_main_status(self, final_text: str = ""):
        if self.parent_window is None:
            return
        try:
            sb = None
            if hasattr(self.parent_window, "statusBar"):
                try:
                    sb = self.parent_window.statusBar()
                except Exception:
                    sb = None
            if sb is None:
                try:
                    sb = self.parent_window.findChild(QStatusBar)
                except Exception:
                    sb = None
            if sb is not None:
                if final_text:
                    sb.showMessage(final_text)
                else:
                    sb.clearMessage()
                QApplication.processEvents()
                return

            for name in (
                "label_status", "lbl_status", "label_info_status",
                "status_label", "label_bottom_status", "label_progress",
                "label_message", "lbl_message",
            ):
                w = getattr(self.parent_window, name, None)
                if w is not None and hasattr(w, "setText"):
                    w.setText(final_text or "")
                    QApplication.processEvents()
                    return
        except Exception as e:
            print(f"[Tab02-SQL] 清除主窗体状态栏失败: {e}")

    # ----------------------------------------------------------
    # 状态栏文案生成
    #   返回："已用时X时XX分XX秒，预计完成时间HH时MM分SS秒"
    # ----------------------------------------------------------
    def _build_status_bar_text(self, done, total, start_dt):
        now_dt = datetime.now()
        try:
            elapsed = (now_dt - start_dt).total_seconds()
        except Exception:
            elapsed = 0.0
        elapsed_str = _format_hms(elapsed)

        if done <= 0 or total <= 0:
            return f"已用时{elapsed_str}，预计完成时间正在估算"

        avg = elapsed / done
        remaining = max(0.0, avg * (total - done))
        eta_dt = now_dt + timedelta(seconds=remaining)
        if eta_dt.date() == now_dt.date():
            eta_str = eta_dt.strftime("%H时%M分%S秒")
        else:
            eta_str = eta_dt.strftime("%m-%d %H时%M分%S秒")
        return f"已用时{elapsed_str}，预计完成时间{eta_str}"

    # ----------------------------------------------------------
    # 日志用的进度信息
    #   返回："已运行...时间，预计剩余...，预计总计N个批次全部完成时间：...时...分完成。"
    # ----------------------------------------------------------
    def _build_progress_info(self, done, total, start_dt, unit_name="批次"):
        now_dt = datetime.now()
        try:
            elapsed = (now_dt - start_dt).total_seconds()
        except Exception:
            elapsed = 0.0
        elapsed_str = _format_duration(elapsed)

        if done <= 0 or total <= 0:
            return (
                f"已运行{elapsed_str}，预计剩余：正在估算，"
                f"预计总计{total}个{unit_name}全部完成时间：正在估算"
            )

        avg = elapsed / done
        remaining = max(0.0, avg * (total - done))
        remaining_str = _format_duration(remaining)
        eta_dt = now_dt + timedelta(seconds=remaining)
        eta_str = _format_eta(eta_dt, now_dt)
        return (
            f"已运行{elapsed_str}，预计剩余{remaining_str}，"
            f"预计总计{total}个{unit_name}全部完成时间：{eta_str}完成。"
        )

    # ----------------------------------------------------------
    # 触发按钮
    # ----------------------------------------------------------
    def on_generate_clicked(self):
        btn = getattr(self.ui, "pushBttn_Generat_minute_List_SQL", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            self._run_download()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._log(f"异常终止: {exc}")
            QMessageBox.critical(self.parent_window, "错误", f"SQL 写入失败：\n{exc}")
            try:
                self.error_signal.emit(str(exc))
            except Exception:
                pass
        finally:
            if btn is not None:
                btn.setEnabled(True)

    # ----------------------------------------------------------
    # 解析 MDF 路径
    # ----------------------------------------------------------
    def _resolve_db_path(self):
        for wname in ("txt_SQL_path_DB_name", "txt_SQL_path"):
            w = getattr(self.ui, wname, None)
            if w is not None:
                v = widget_get_text(w)
                if v:
                    return v.strip()
        return ""

    # ----------------------------------------------------------
    # 核心流程
    # ----------------------------------------------------------
    def _run_download(self):
        self._abort_requested = False
        # 记录整个任务的总开始时间（用于"总用时"统计）
        run_start_dt = datetime.now()

        # 0. 依赖检查
        if not _PYODBC_AVAILABLE:
            raise RuntimeError(
                "缺少 pyodbc 库。请先运行：pip install pyodbc\n"
                "并确保已安装 ODBC Driver for SQL Server（17 或 18）。"
            )

        # 1. 读取 UI
        db_path = self._resolve_db_path()
        if not db_path:
            QMessageBox.warning(
                self.parent_window, "警告",
                "请先指定 SQL Server 数据库文件（*.mdf）路径（txt_SQL_path_DB_name）",
            )
            return

        ts_code = widget_get_text(getattr(self.ui, "txt_ts_code", None))
        freq    = widget_get_text(getattr(self.ui, "txt_freq", None))
        start_s = widget_get_text(getattr(self.ui, "txt_start_date", None))
        end_s   = widget_get_text(getattr(self.ui, "txt_end_date", None))
        offset  = widget_get_text(getattr(self.ui, "txt_offset", None))

        if not ts_code:
            QMessageBox.warning(self.parent_window, "警告", "请填写 txt_ts_code")
            return

        if freq not in FREQ_FACTOR_MAP:
            QMessageBox.warning(
                self.parent_window, "警告",
                f"freq 无效：{freq}\n可选：{', '.join(FREQ_FACTOR_MAP.keys())}",
            )
            return

        sd = parse_date(start_s)
        ed = parse_date(end_s)
        if sd is None or ed is None:
            QMessageBox.warning(self.parent_window, "警告", "日期格式必须为 YYYY-MM-DD")
            return
        if sd > ed:
            QMessageBox.warning(self.parent_window, "警告", "开始日期不能晚于结束日期")
            return

        # 2. 表名（自动生成）
        table_name = make_table_name(ts_code, freq)
        widget_set_text(getattr(self.ui, "txt_SQL_table_name", None), table_name)
        if not TABLE_NAME_RE.match(table_name):
            QMessageBox.warning(
                self.parent_window, "警告",
                f"自动生成的表名不符合规范：{table_name}",
            )
            return

        # 3. 初始化日志
        self._init_logger()
        self._orig_start_date = start_s
        self._orig_end_date   = end_s

        self._log("=" * 60)
        self._log("开始从 tushare 提取分钟数据并写入 SQL Server LocalDB")
        self._log(f"  服务器       = {SQL_SERVER_INSTANCE}")
        self._log(f"  数据库       = {SQL_DATABASE_NAME}")
        self._log(f"  MDF 文件     = {db_path}")
        self._log(f"  数据表名     = {table_name}")
        self._log(f"  ts_code      = {ts_code}")
        self._log(f"  freq         = {freq}")
        self._log(f"  factor       = {FREQ_FACTOR_MAP[freq]}")
        self._log(f"  start_date   = {start_s}")
        self._log(f"  end_date     = {end_s}")
        self._log(f"  offset       = {offset!r}")

        total_api_rows    = 0
        total_inserted    = 0
        total_skipped_dup = 0
        aborted           = False

        conn = None
        try:
            conn = self._connect_sql_server(db_path)

            # 需求 1 & 2：检查/创建数据表
            self._ensure_table(conn, table_name)

            # 拆分任务（月度）
            factor = FREQ_FACTOR_MAP[freq]
            span   = (ed - sd).days + 1
            tasks  = []
            if span <= SPAN_THRESHOLD_DAYS:
                tasks.append((sd, ed, DEFAULT_LIMIT))
                self._log(f"日期跨度 {span} 天 ≤ {SPAN_THRESHOLD_DAYS} 天 -> 单次下载")
            else:
                for (ms, me) in split_by_month(sd, ed):
                    days = (me - ms).days + 1
                    lim  = days * factor
                    tasks.append((ms, me, lim))
                self._log(f"日期跨度 {span} 天 > {SPAN_THRESHOLD_DAYS} 天 "
                          f"-> 拆分为 {len(tasks)} 个月度任务")

            total_tasks = len(tasks)

            # 初始化 tushare
            try:
                pro = ts.pro_api(self.api_token)
            except Exception as e:
                self._log(f"pro_api 初始化失败: {e}")
                raise RuntimeError(f"tushare 初始化失败：\n{e}")

            # 逐任务下载 & 写入（主批次循环计时开始）
            cycle_start_dt = datetime.now()
            # 启动时先刷一次状态栏（估算中）
            self._update_main_status(
                self._build_status_bar_text(0, total_tasks, cycle_start_dt)
            )

            for idx, (ms, me, lim) in enumerate(tasks, start=1):
                if self._abort_requested:
                    self._log("检测到中止标志，停止后续任务")
                    aborted = True
                    break

                widget_set_text(getattr(self.ui, "txt_start_date", None), format_date(ms))
                widget_set_text(getattr(self.ui, "txt_end_date", None),   format_date(me))
                widget_set_text(getattr(self.ui, "txt_factor", None),     str(factor))
                widget_set_text(getattr(self.ui, "txt_limit", None),      str(lim))
                QApplication.processEvents()

                # 主循环进度提示（done = idx - 1，已完成的批次数）
                progress_info = self._build_progress_info(
                    done=idx - 1,
                    total=total_tasks,
                    start_dt=cycle_start_dt,
                    unit_name="批次",
                )
                self._log(
                    f"[{idx}/{total_tasks}] {format_date(ms)} ~ {format_date(me)}  "
                    f"limit={lim}  |  {progress_info}"
                )

                # 刷新主窗体左下方状态栏
                self._update_main_status(
                    self._build_status_bar_text(
                        done=idx - 1, total=total_tasks, start_dt=cycle_start_dt,
                    )
                )

                params = {
                    "ts_code": ts_code, "freq": freq,
                    "start_date": format_date(ms),
                    "end_date":   format_date(me),
                    "limit":      str(lim),
                    "offset":     offset,
                }
                try:
                    df = pro.stk_mins(**params, fields=API_FIELDS)
                except Exception as e:
                    self._log(f"    API 异常: {e}")
                    continue

                if self._abort_requested:
                    self._log("检测到中止标志，跳过本批数据写入")
                    aborted = True
                    break

                if df is None or df.empty:
                    self._log("    返回数据为空")
                    continue

                self._log(f"    返回 {len(df)} 行")
                total_api_rows += len(df)

                try:
                    inserted, skipped_dup = self._insert_dataframe(
                        conn=conn, df=df, ts_code=ts_code, table_name=table_name,
                        batch_idx=idx, batch_total=total_tasks,
                    )
                    total_inserted    += inserted
                    total_skipped_dup += skipped_dup
                    self._log(f"    本批新写入 {inserted} 行，已存在跳过 {skipped_dup} 行")
                except Exception as e:
                    self._log(f"    写入 SQL 失败: {e}")
                    continue

        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

            widget_set_text(getattr(self.ui, "txt_start_date", None), self._orig_start_date)
            widget_set_text(getattr(self.ui, "txt_end_date", None),   self._orig_end_date)
            self._recalc_limit_for_current_dates()

        self._save_settings()

        # 计算总用时
        total_elapsed = (datetime.now() - run_start_dt).total_seconds()
        total_elapsed_str = _format_hms(total_elapsed)

        self._log("=" * 60)
        self._log("任务被用户中止" if aborted else "全部完成")
        self._log(f"总用时: {total_elapsed_str}")

        # 结束时清空/固定主窗体状态栏
        if aborted:
            self._clear_main_status(f"已中止，总用时{total_elapsed_str}")
        else:
            self._clear_main_status(f"完成，总用时{total_elapsed_str}")

        msg_lines = [
            "下载已被用户中止。" if aborted else "分钟数据已写入 SQL Server LocalDB。",
            "",
            f"数据库名：{SQL_DATABASE_NAME}",
            f"MDF 文件：{db_path}",
            f"表名    ：{table_name}",
            f"API 返回累计：{total_api_rows} 行",
            f"新写入      ：{total_inserted} 行",
            f"已存在跳过  ：{total_skipped_dup} 行",
            "",
            f"总用时    ：{total_elapsed_str}",
        ]
        if aborted:
            QMessageBox.information(self.parent_window, "已中止", "\n".join(msg_lines))
        else:
            QMessageBox.information(self.parent_window, "完成", "\n".join(msg_lines))

        try:
            self.finished_signal.emit()
        except Exception:
            pass

    # ----------------------------------------------------------
    # SQL Server 连接（LocalDB + Windows 身份验证）
    # ----------------------------------------------------------
    def _find_odbc_drivers(self):
        try:
            installed = pyodbc.drivers() or []
        except Exception:
            installed = []
        found = [d for d in ODBC_DRIVER_CANDIDATES if d in installed]
        return found or []

    def _connect_sql_server(self, db_path: str):
        """
        连接策略：
          A) 优先 DATABASE=股票数据（若数据库已附加到 LocalDB）
          B) 若失败且 MDF 路径存在，用 AttachDbFilename 自动附加
          C) 若仍失败，抛出汇总异常
        """
        if not _PYODBC_AVAILABLE:
            raise RuntimeError("缺少 pyodbc 库，请先 pip install pyodbc")

        drivers = self._find_odbc_drivers()
        if not drivers:
            raise RuntimeError(
                "未找到 ODBC Driver for SQL Server。\n"
                "请安装 'ODBC Driver 17 for SQL Server' 或 'ODBC Driver 18 for SQL Server'。"
            )

        errors = []
        # A) 直接连接 DATABASE
        for drv in drivers:
            conn_str = (
                f"DRIVER={{{drv}}};"
                f"SERVER={SQL_SERVER_INSTANCE};"
                f"DATABASE={SQL_DATABASE_NAME};"
                f"Trusted_Connection=yes;"
                f"TrustServerCertificate=yes;"
            )
            try:
                conn = pyodbc.connect(conn_str, timeout=20, autocommit=False)
                self._log(f"已连接 SQL Server（DATABASE 模式）：{SQL_DATABASE_NAME}")
                return conn
            except Exception as e:
                errors.append(f"[{drv}] DATABASE 模式失败：{e}")

        # B) AttachDbFilename 附加
        if db_path and os.path.exists(db_path):
            for drv in drivers:
                conn_str = (
                    f"DRIVER={{{drv}}};"
                    f"SERVER={SQL_SERVER_INSTANCE};"
                    f"AttachDbFilename={db_path};"
                    f"DATABASE={SQL_DATABASE_NAME};"
                    f"Trusted_Connection=yes;"
                    f"TrustServerCertificate=yes;"
                )
                try:
                    conn = pyodbc.connect(conn_str, timeout=20, autocommit=False)
                    self._log(f"已连接 SQL Server（ATTACH 模式）：{db_path}")
                    return conn
                except Exception as e:
                    errors.append(f"[{drv}] ATTACH 模式失败：{e}")

        detail = "\n".join(errors[-6:])
        raise RuntimeError(
            "无法连接 SQL Server LocalDB。\n"
            f"服务器：{SQL_SERVER_INSTANCE}\n"
            f"数据库：{SQL_DATABASE_NAME}\n"
            f"MDF ：{db_path}\n\n"
            f"最后错误：\n{detail}\n\n"
            "排查建议：\n"
            "  1) 确认 LocalDB 已安装并启动：sqllocaldb info\n"
            "  2) 确认已安装 ODBC Driver 17/18 for SQL Server\n"
            "  3) 确认 MDF 文件存在且当前 Windows 用户有读写权限\n"
            "  4) 若数据库未附加，请在 SSMS 中附加一次，或检查 MDF 路径是否正确"
        )

    # ----------------------------------------------------------
    # 需求 1 & 2：检查/创建数据表
    # ----------------------------------------------------------
    def _ensure_table(self, conn, table_name):
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                (SQL_SCHEMA, table_name),
            )
            exists = cur.fetchone() is not None
            if exists:
                self._log(f"数据表已存在：{SQL_SCHEMA}.{table_name}"
                          f"（写入时将按 trade_time 主键去重）")
            else:
                cur.execute(make_create_table_sql(table_name))
                conn.commit()
                self._log(f"数据表不存在，已创建：{SQL_SCHEMA}.{table_name}"
                          f"（trade_time 为主键）")
        finally:
            cur.close()

    # ----------------------------------------------------------
    # 需求 3：按 trade_time 去重 + 分批写入
    # ----------------------------------------------------------
    def _insert_dataframe(self, conn, df, ts_code, table_name,
                          batch_idx=None, batch_total=None):
        """
        返回 (实际插入行数, 因 trade_time 已存在而跳过的行数)。

        实现：
          1) 把 trade_time 规范为 Python datetime（无时区）；
          2) 查询该时间窗口内已存在的 trade_time 集合，预先过滤；
          3) 分批 executemany 插入（fast_executemany=True）；
          4) 每批 commit；每批之间检查中止标志，并输出日志 + 刷新主窗体状态栏。
        """
        if df is None or df.empty:
            return 0, 0

        df2 = df.copy()
        for col in API_FIELDS:
            if col not in df2.columns:
                df2[col] = None
        df2 = df2[API_FIELDS]

        # trade_time → Python datetime
        df2["trade_time"] = df2["trade_time"].apply(
            lambda v: _to_py_value(pd.to_datetime(v, errors="coerce"))
            if v is not None else None
        )
        df2 = df2.dropna(subset=["trade_time"])
        if df2.empty:
            return 0, 0

        # 批内去重
        before = len(df2)
        df2 = df2.drop_duplicates(subset=["trade_time"], keep="first")
        in_batch_dup = before - len(df2)
        if in_batch_dup > 0:
            self._log(f"    本批内重复 trade_time 已去除 {in_batch_dup} 行")

        df2["ts_code"] = df2["ts_code"].where(df2["ts_code"].notna(), ts_code)

        # 查询已存在 trade_time（窗口内）
        min_tt = df2["trade_time"].min()
        max_tt = df2["trade_time"].max()
        existing = set()
        cur0 = conn.cursor()
        try:
            cur0.execute(
                f"SELECT [trade_time] FROM [{SQL_SCHEMA}].[{table_name}] "
                f"WHERE [trade_time] >= ? AND [trade_time] <= ?",
                (min_tt, max_tt),
            )
            for row in cur0.fetchall():
                v = row[0]
                if isinstance(v, datetime):
                    if v.tzinfo:
                        v = v.replace(tzinfo=None)
                    existing.add(v)
        finally:
            cur0.close()

        if existing:
            df2 = df2[~df2["trade_time"].isin(existing)]
            pre_skipped = before - in_batch_dup - len(df2)
            if pre_skipped > 0:
                self._log(f"    与表内已有 trade_time 冲突，预先跳过 {pre_skipped} 行")
        else:
            pre_skipped = 0

        if df2.empty:
            return 0, in_batch_dup + pre_skipped

        # 构造行
        rows = []
        for rec in df2.itertuples(index=False, name=None):
            rows.append(tuple(_to_py_value(v) for v in rec))
        if not rows:
            return 0, in_batch_dup + pre_skipped

        insert_sql = make_insert_sql(table_name)
        cur = conn.cursor()
        try:
            try:
                cur.fast_executemany = True
            except Exception:
                pass

            total_chunks = (len(rows) + INSERT_CHUNK_SIZE - 1) // INSERT_CHUNK_SIZE
            insert_start_dt = datetime.now()

            inserted = 0
            attempted = 0
            chunk_idx = 0
            for i in range(0, len(rows), INSERT_CHUNK_SIZE):
                if self._abort_requested:
                    self._log("    中止：跳过本批剩余写入")
                    break
                chunk = rows[i:i + INSERT_CHUNK_SIZE]
                cur.executemany(insert_sql, chunk)
                conn.commit()
                inserted += len(chunk)
                attempted += len(chunk)
                chunk_idx += 1

                # 写入分块循环进度提示（done = chunk_idx，已写块数）
                progress_info = self._build_progress_info(
                    done=chunk_idx,
                    total=total_chunks,
                    start_dt=insert_start_dt,
                    unit_name="写入分块",
                )
                self._log(f"    写入分块 [{chunk_idx}/{total_chunks}] {progress_info}")

                # 刷新主窗体左下方状态栏（含批次上下文）
                if batch_idx is not None and batch_total is not None:
                    status_prefix = f"批次 [{batch_idx}/{batch_total}] "
                else:
                    status_prefix = ""
                status_text = (
                    f"{status_prefix}写入分块 [{chunk_idx}/{total_chunks}]  "
                    + self._build_status_bar_text(
                        done=chunk_idx, total=total_chunks, start_dt=insert_start_dt,
                    )
                )
                self._update_main_status(status_text)

                QApplication.processEvents()

            if attempted < len(rows):
                self._log(f"    因中止未尝试写入 {len(rows) - attempted} 行")

            skipped_dup = in_batch_dup + pre_skipped + (len(rows) - attempted)
            return inserted, skipped_dup
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()

    # ----------------------------------------------------------
    # 持久化（Tab02 自身参数）
    # ----------------------------------------------------------
    def _load_settings(self):
        try:
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in PERSIST_KEYS:
                if key in data and hasattr(self.ui, key):
                    widget_set_text(getattr(self.ui, key), data[key])
            print(f"[Tab02-SQL] 已加载上次保存的参数：{self._persist_path}")
        except Exception as e:
            print(f"[Tab02-SQL] 加载参数失败: {e}")

    def save_settings(self):
        try:
            data = {}
            for key in PERSIST_KEYS:
                if hasattr(self.ui, key):
                    data[key] = widget_get_text(getattr(self.ui, key))
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[Tab02-SQL] 参数已保存：{self._persist_path}")
        except Exception as e:
            print(f"[Tab02-SQL] 保存参数失败: {e}")

    def _save_settings(self):
        self.save_settings()