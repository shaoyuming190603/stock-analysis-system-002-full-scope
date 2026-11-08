# -*- coding: utf-8 -*-
"""
Tab02_minute_data_downloader.py
================================
Tab02_数据下载 标签页的功能实现模块
"""

import os
import re
import json
import calendar
import logging
from datetime import date, datetime

import pandas as pd
import tushare as ts

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QApplication


# ==============================================================
# 常量
# ==============================================================
DEFAULT_LIMIT         = 7471
MAX_API_LIMIT         = 8000
SPAN_THRESHOLD_DAYS   = 31

FREQ_FACTOR_MAP = {
    "1min":  241,
    "5min":  49,
    "15min": 17,
    "30min": 9,
    "60min": 5,
}

PERSIST_KEYS = [
    "txt_ts_code",
    "txt_freq",
    "txt_start_date",
    "txt_end_date",
    "txt_factor",
    "txt_limit",
    "txt_offset",
]

PERSIST_FILE_NAME = "Tab02_settings.json"
LOG_FILE_NAME     = "Tab02_download.log"

API_FIELDS = [
    "ts_code",
    "trade_time",
    "close",
    "open",
    "high",
    "low",
    "vol",
    "amount",
    "freq",
    "exchange",
    "vwap",
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


def freq_to_label(freq):
    m = re.match(r"\s*(\d+)\s*min\s*", str(freq))
    if not m:
        return str(freq)
    return str(int(m.group(1)))


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


def _is_blank(v):
    """判断是否为 NaN / NaT / None 等空值"""
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return False


# ==============================================================
# 主控制器
# ==============================================================
class Tab02MinuteDataDownloader(QObject):
    log_signal      = Signal(str)
    finished_signal = Signal()
    error_signal    = Signal(str)

    def __init__(self, ui, parent_window=None, api_token=None):
        super().__init__(parent_window)
        self.ui             = ui
        self.parent_window  = parent_window
        self.api_token      = api_token or "8197a7e40501f6409bfc58a5af2e0fc70e4fac6da9df6ff82c28db61"
        self._orig_start_date = ""
        self._orig_end_date   = ""
        self._logger        = None

        self._persist_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            PERSIST_FILE_NAME,
        )

        self._connect_signals()
        self._load_settings()
        self._setup_initial_state()

    # ----------------------------------------------------------
    # 初始化
    # ----------------------------------------------------------
    def _connect_signals(self):
        btn = getattr(self.ui, "pushBttn_Generat_minute_List", None)
        if btn is not None:
            btn.pressed.connect(self.on_generate_clicked)

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

    def _setup_initial_state(self):
        self._orig_start_date = widget_get_text(self.ui.txt_start_date)
        self._orig_end_date   = widget_get_text(self.ui.txt_end_date)

        freq = widget_get_text(self.ui.txt_freq)
        if freq in FREQ_FACTOR_MAP:
            widget_set_text(self.ui.txt_factor, str(FREQ_FACTOR_MAP[freq]))

        widget_set_text(self.ui.txt_limit, str(DEFAULT_LIMIT))
        self._recalc_limit_for_current_dates()

    # ----------------------------------------------------------
    # 控件联动
    # ----------------------------------------------------------
    def _on_freq_changed(self, *args):
        freq = widget_get_text(self.ui.txt_freq)
        if freq in FREQ_FACTOR_MAP:
            widget_set_text(self.ui.txt_factor, str(FREQ_FACTOR_MAP[freq]))
        self._recalc_limit_for_current_dates()

    def _on_date_changed(self, *args):
        self._recalc_limit_for_current_dates()

    def _recalc_limit_for_current_dates(self):
        sd = parse_date(widget_get_text(self.ui.txt_start_date))
        ed = parse_date(widget_get_text(self.ui.txt_end_date))
        freq   = widget_get_text(self.ui.txt_freq)
        factor = FREQ_FACTOR_MAP.get(freq)

        if sd is None or ed is None or sd > ed or factor is None:
            widget_set_text(self.ui.txt_limit, str(DEFAULT_LIMIT))
            return

        span = (ed - sd).days + 1
        if span <= SPAN_THRESHOLD_DAYS:
            widget_set_text(self.ui.txt_limit, str(DEFAULT_LIMIT))
            return

        monthly = []
        for (ms, me) in split_by_month(sd, ed):
            days = (me - ms).days + 1
            monthly.append(days * factor)
        if monthly:
            widget_set_text(self.ui.txt_limit, str(max(monthly)))

    # ----------------------------------------------------------
    # 日志
    # ----------------------------------------------------------
    def _init_logger(self, folder):
        log_path = os.path.join(folder, LOG_FILE_NAME)
        logger = logging.getLogger("Tab02MinuteDataDownloader")
        logger.setLevel(logging.INFO)
        for h in list(logger.handlers):
            if isinstance(h, logging.FileHandler):
                logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
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
        print(f"[Tab02] {msg}")
        try:
            self.log_signal.emit(msg)
        except Exception:
            pass

    # ----------------------------------------------------------
    # 按钮回调
    # ----------------------------------------------------------
    def on_generate_clicked(self):
        # 下载开始时禁用按钮（避免重复触发）
        btn = getattr(self.ui, "pushBttn_Generat_minute_List", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            self._run_download()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            if self._logger:
                self._log(f"异常终止: {exc}")
            QMessageBox.critical(self.parent_window, "错误", f"下载失败：\n{exc}")
            try:
                self.error_signal.emit(str(exc))
            except Exception:
                pass
        finally:
            if btn is not None:
                btn.setEnabled(True)

    # ----------------------------------------------------------
    # 核心流程
    # ----------------------------------------------------------
    def _run_download(self):
        # ---------- 1. 校验输入 ----------
        folder = widget_get_text(self.ui.txt_Specify_Initial_Path)
        if not folder:
            QMessageBox.warning(self.parent_window, "警告",
                                "请先在 Tab01_数据设置 中选择输出路径")
            return
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self.parent_window, "错误", f"无法创建目录：\n{e}")
                return

        ts_code = widget_get_text(self.ui.txt_ts_code)
        freq    = widget_get_text(self.ui.txt_freq)
        start_s = widget_get_text(self.ui.txt_start_date)
        end_s   = widget_get_text(self.ui.txt_end_date)
        offset  = widget_get_text(self.ui.txt_offset)

        if not ts_code:
            QMessageBox.warning(self.parent_window, "警告", "请填写 txt_ts_code")
            return
        if freq not in FREQ_FACTOR_MAP:
            QMessageBox.warning(
                self.parent_window, "警告",
                f"freq 无效：{freq}\n可选：{', '.join(FREQ_FACTOR_MAP.keys())}"
            )
            return

        sd = parse_date(start_s)
        ed = parse_date(end_s)
        if sd is None or ed is None:
            QMessageBox.warning(self.parent_window, "警告",
                                "日期格式必须为 YYYY-MM-DD")
            return
        if sd > ed:
            QMessageBox.warning(self.parent_window, "警告",
                                "开始日期不能晚于结束日期")
            return

        # ---------- 2. 日志 ----------
        self._init_logger(folder)

        # ---------- 3. 记录原始输入 ----------
        self._orig_start_date = start_s
        self._orig_end_date   = end_s

        # ---------- 4. 文件名 ----------
        freq_label = freq_to_label(freq)
        today_str  = datetime.now().strftime("%Y-%m-%d")
        base_name  = f"TuShare {freq_label}分钟数据_{today_str}"
        csv_path   = os.path.join(folder, base_name + ".csv")
        xlsx_path  = os.path.join(folder, base_name + ".xlsx")

        # ★ 需求 2：把输出路径写入 txt_file_path
        widget_set_text(self.ui.txt_file_path, folder)
        # ★ 需求 3：把输出文件名（不含扩展名）写入 txt_file_name
        widget_set_text(self.ui.txt_file_name, base_name)

        self._log("=" * 60)
        self._log("开始下载分钟数据")
        self._log(f"  ts_code      = {ts_code}")
        self._log(f"  freq         = {freq}")
        self._log(f"  factor       = {FREQ_FACTOR_MAP[freq]}")
        self._log(f"  start_date   = {start_s}")
        self._log(f"  end_date     = {end_s}")
        self._log(f"  offset       = {offset!r}")
        self._log(f"  输出文件夹   = {folder}")
        self._log(f"  CSV  文件    = {os.path.basename(csv_path)}")
        self._log(f"  Excel 文件   = {os.path.basename(xlsx_path)}")

        # ---------- 5. 拆分任务 ----------
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
            self._log(f"日期跨度 {span} 天 > {SPAN_THRESHOLD_DAYS} 天 -> 拆分为 {len(tasks)} 个月度任务")

        # ---------- 6. 初始化 tushare ----------
        try:
            pro = ts.pro_api(self.api_token)
        except Exception as e:
            self._log(f"pro_api 初始化失败: {e}")
            QMessageBox.critical(self.parent_window, "错误",
                                 f"tushare 初始化失败：\n{e}")
            return

        # ---------- 7. 逐任务拉取 & 追加写入 ----------
        total_rows = 0
        for idx, (ms, me, lim) in enumerate(tasks, start=1):
            widget_set_text(self.ui.txt_start_date, format_date(ms))
            widget_set_text(self.ui.txt_end_date,   format_date(me))
            widget_set_text(self.ui.txt_factor,     str(factor))
            widget_set_text(self.ui.txt_limit,      str(lim))
            QApplication.processEvents()

            self._log(f"[{idx}/{len(tasks)}] {format_date(ms)} ~ {format_date(me)}  limit={lim}")

            params = {
                "ts_code":    ts_code,
                "freq":       freq,
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

            if df is None or df.empty:
                self._log("    返回数据为空")
                continue

            self._log(f"    返回 {len(df)} 行")
            total_rows += len(df)

            try:
                self._append_csv(df, csv_path)
            except Exception as e:
                self._log(f"    CSV 追加失败: {e}")
            try:
                self._append_xlsx(df, xlsx_path)
            except Exception as e:
                self._log(f"    Excel 追加失败: {e}")

        self._log(f"所有任务完成，累计 {total_rows} 行")

        # ---------- 8. 排序 & 去重 & 自适应列宽 ----------
        try:
            self._finalize_files(csv_path, xlsx_path)
        except Exception as e:
            self._log(f"排序/去重失败: {e}")

        # ---------- 9. 恢复原始日期 ----------
        widget_set_text(self.ui.txt_start_date, self._orig_start_date)
        widget_set_text(self.ui.txt_end_date,   self._orig_end_date)
        self._recalc_limit_for_current_dates()

        # ---------- 10. 保存控件值（Tab02 自身的设置文件） ----------
        self._save_settings()

        # ---------- 11. ★ 需求 8/9：打开 Excel 文件与输出文件夹 ----------
        try:
            # 需求 9：打开 txt_file_path 对应的文件夹
            folder_path = widget_get_text(self.ui.txt_file_path) or folder
            if folder_path and os.path.isdir(folder_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
                self._log(f"已打开文件夹: {folder_path}")

            # 需求 8：打开新生成的 Excel
            if os.path.exists(xlsx_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(xlsx_path))
                self._log(f"已打开 Excel 文件: {xlsx_path}")
        except Exception as e:
            self._log(f"打开文件/文件夹失败: {e}")

        self._log("=" * 60)
        self._log("全部完成")

        QMessageBox.information(
            self.parent_window, "完成",
            f"数据下载完成。\n\n"
            f"保存位置：{folder}\n"
            f"CSV  文件：{os.path.basename(csv_path)}\n"
            f"Excel 文件：{os.path.basename(xlsx_path)}\n"
            f"累计：{total_rows} 行"
        )
        try:
            self.finished_signal.emit()
        except Exception:
            pass

    # ----------------------------------------------------------
    # 文件追加
    # ----------------------------------------------------------
    def _append_csv(self, df, path):
        write_header = not os.path.exists(path) or os.path.getsize(path) == 0
        df.to_csv(
            path,
            mode="a",
            header=write_header,
            index=False,
            encoding="utf-8-sig",
        )

    def _append_xlsx(self, df, path):
        from openpyxl import load_workbook, Workbook

        if os.path.exists(path):
            wb = load_workbook(path)
            ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.append(list(df.columns))

        for row in df.itertuples(index=False, name=None):
            clean = [None if _is_blank(v) else v for v in row]
            ws.append(clean)

        wb.save(path)

    # ----------------------------------------------------------
    # 排序 + 去重 + 写 Excel（含列宽自适应）
    # ----------------------------------------------------------
    def _finalize_files(self, csv_path, xlsx_path):
        """按第 2 列升序排序，按第 2 列去重，并按自适应列宽写出 Excel"""
        if not os.path.exists(csv_path):
            self._log("CSV 文件不存在，跳过排序/去重")
            return

        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        if df.empty or df.shape[1] < 2:
            self._log("数据为空或列数不足，跳过排序/去重")
            return

        second_col = df.columns[1]
        self._log(f"排序/去重：第 2 列 = {second_col}")

        # ★ 需求 6：按第 2 列升序排序
        try:
            df = df.sort_values(by=second_col, ascending=True, kind="mergesort")
        except Exception as e:
            self._log(f"排序失败（保持原顺序）：{e}")

        before = len(df)
        df = df.drop_duplicates(subset=[second_col], keep="first")
        df = df.reset_index(drop=True)
        after = len(df)
        self._log(f"去重：{before} -> {after}（移除 {before - after} 行冗余）")

        # 覆盖 CSV
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # ★ 需求 7：写出 Excel 并自适应列宽
        self._write_xlsx_with_column_width(df, xlsx_path)
        self._log(f"已重新写出 CSV 与 Excel：{after} 行")

    def _write_xlsx_with_column_width(self, df, path):
        """把 DataFrame 写成 Excel，并按每列最长内容自适应列宽"""
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        # 表头
        ws.append(list(df.columns))
        # 数据行
        for row in df.itertuples(index=False, name=None):
            clean = [None if _is_blank(v) else v for v in row]
            ws.append(clean)

        # 列宽自适应（+2 留余量）
        for col_idx, col_name in enumerate(df.columns, start=1):
            max_len = len(str(col_name))
            try:
                values = df[col_name].tolist()
            except Exception:
                values = []
            for value in values:
                if _is_blank(value):
                    continue
                for line in str(value).split("\n"):
                    if len(line) > max_len:
                        max_len = len(line)
            ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 2

        wb.save(path)

    # ----------------------------------------------------------
    # 控件值持久化（Tab02 自身的设置文件）
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
            print(f"[Tab02] 已加载上次保存的参数：{self._persist_path}")
        except Exception as e:
            print(f"[Tab02] 加载参数失败: {e}")

    def _save_settings(self):
        try:
            data = {}
            for key in PERSIST_KEYS:
                if hasattr(self.ui, key):
                    data[key] = widget_get_text(getattr(self.ui, key))
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[Tab02] 参数已保存：{self._persist_path}")
        except Exception as e:
            print(f"[Tab02] 保存参数失败: {e}")