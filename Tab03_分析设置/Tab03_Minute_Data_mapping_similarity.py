# -*- coding: utf-8 -*-
"""
Tab03_Minute_Data_mapping_similarity.py
======================================
读取本地 SQL Server 历史分时数据（表名 ``minute_data_<6位code>_<freq>``），
与 Tab03_Minute_Data_Display_Qt 当前展示的分时图进行形态匹配，
把最相似的 N 天历史分时曲线叠加到当前分时图上，并在图下方列出 OHLC/涨跌幅。

v1.2 修复（关键）：
  * 读取 SQL 时同时 SELECT open / high / low，用于统计计算。
  * _compute_similarity() 返回原始长度 y_plot（用于绘制"全天曲线"），
    并用插值后序列做相关性计算。
  * 每日 OHLC / pct_change 计算后随 data_list 传给 Tab03。
  * pct_change 优先"相对前收"，退化为"相对开盘"。
  * data_updated 触发时做轻量防抖，避免定时刷新引发过频重算。
  * 与 Tab03 v1.2 完整对接（set_mapping_lines / clear_mapping_lines /
    current_df / data_updated）。

相似度算法（效率与有效性平衡）
------------------------------
1. 把价格序列归一化为相对首条的涨跌幅收益率 r[i] = y[i]/y[0] - 1。
2. 长度不同则用 numpy.interp 线性插值对齐到当前长度；长度 < 当前 60% 的跳过。
3. 用 Pearson 相关系数计算相似度（numpy 向量化，~O(N)）。
4. 按相关系数降序取前 N，叠加时把历史曲线等比缩放到当前开盘价。

N 由下列 CheckBox 的末两位数字决定：
    checkBox_price_mapping_01 / 03 / 05 / 10 / 20 / 50
系统启动加载时默认选中 checkBox_price_mapping_03。
改选 CheckBox 会立即触发重新匹配。
"""

import os
import re
import sys
import time
import colorsys
import random
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from PySide6.QtCore import QObject, Signal

# ---------- 复用 Tab02 SQL 模块的常量 ----------
try:
    _proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _proj_root not in sys.path:
        sys.path.insert(0, _proj_root)
    from Tab02_数据下载.Tab02_minute_data_downloader_SQL import (  # type: ignore
        SQL_SERVER_INSTANCE,
        SQL_DATABASE_NAME,
        SQL_SCHEMA,
        ODBC_DRIVER_CANDIDATES,
        DEFAULT_SQL_DB_PATH,
    )
    print("[Tab03-Mapping] 已复用 Tab02 SQL 定义")
except Exception as _e:
    print(f"[Tab03-Mapping] 复用 Tab02 SQL 定义失败，使用内置默认值: {_e}")
    SQL_SERVER_INSTANCE = r"(localdb)\MSSQLLocalDB"
    SQL_DATABASE_NAME   = "股票数据"
    SQL_SCHEMA          = "dbo"
    ODBC_DRIVER_CANDIDATES = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]
    DEFAULT_SQL_DB_PATH = r"D:\ToolsInstall\SQL2025\myData\股票数据\股票数据.mdf"

try:
    import pyodbc  # type: ignore
    _PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None
    _PYODBC_AVAILABLE = False


# ==============================================================
# 常量
# ==============================================================
CHECKBOX_NAMES = [
    "checkBox_price_mapping_01",
    "checkBox_price_mapping_03",
    "checkBox_price_mapping_05",
    "checkBox_price_mapping_10",
    "checkBox_price_mapping_20",
    "checkBox_price_mapping_50",
]
DEFAULT_CHECKBOX = "checkBox_price_mapping_03"

HISTORY_LOOKBACK_DAYS = 730   # ≈ 2 年
HISTORY_CACHE_TTL_SEC = 300   # 5 分钟缓存
MIN_LEN_RATIO = 0.6           # 至少为当前长度 60%


# ==============================================================
# 工具函数
# ==============================================================
def _widget_get_text(widget):
    if widget is None:
        return ""
    try:
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText().strip()
        if hasattr(widget, "currentText"):
            return str(widget.currentText()).strip()
        if hasattr(widget, "text"):
            return str(widget.text()).strip()
    except Exception:
        pass
    return ""


def _normalize_ts_code(ts_code) -> str:
    if not ts_code:
        return ""
    s = str(ts_code).split(".")[0]
    s = re.sub(r"[^A-Za-z0-9]", "", s)
    return s[:6]


def _normalize_freq(freq) -> str:
    if freq is None:
        return "1min"
    s = re.sub(r"[^A-Za-z0-9]", "", str(freq))
    if not s:
        return "1min"
    if s[-1].isdigit() and "min" not in s.lower():
        s += "min"
    return s


def _make_table_name(ts_code: str, freq: str) -> str:
    code = _normalize_ts_code(ts_code)
    if not code:
        return ""
    freq_s = _normalize_freq(freq)
    return f"minute_data_{code}_{freq_s}"


def _generate_distinct_colors(n):
    """生成 n 个视觉上互异、偏深色的随机颜色。"""
    colors = []
    if n <= 0:
        return colors
    golden = 0.618033988749895
    h = random.random()
    for _ in range(n):
        h = (h + golden) % 1.0
        s = 0.70 + random.random() * 0.25
        v = 0.70 + random.random() * 0.25
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        colors.append((r, g, b))
    return colors


def _compute_similarity(current_series, groups, exclude_date, top_n):
    """计算当前序列与历史各组序列的相似度。

    返回 list[dict]：
        {
            'date', 'corr',
            'y_plot',   # 历史原始长度（用于绘制"全天曲线"）
            'open', 'close', 'high', 'low',
        }
    """
    L = len(current_series)
    if L < 10:
        return []

    r_cur = current_series.astype(float) / float(current_series[0]) - 1.0
    std_cur = float(np.std(r_cur))
    if std_cur < 1e-10:
        return []

    x_target = np.linspace(0.0, 1.0, L)
    min_len = max(10, int(L * MIN_LEN_RATIO))

    results = []
    for date, g in groups:
        if date == exclude_date:
            continue
        try:
            y_hist = g["close"].astype(float).values
        except Exception:
            continue
        if len(y_hist) < min_len:
            continue
        if not np.all(np.isfinite(y_hist)):
            continue
        if y_hist[0] == 0:
            continue

        # 比较时插值到当前长度
        if len(y_hist) != L:
            x_hist = np.linspace(0.0, 1.0, len(y_hist))
            y_compare = np.interp(x_target, x_hist, y_hist)
        else:
            y_compare = y_hist

        r_h = y_compare / float(y_compare[0]) - 1.0
        std_h = float(np.std(r_h))
        if std_h < 1e-10:
            continue

        try:
            corr = float(np.corrcoef(r_cur, r_h)[0, 1])
        except Exception:
            continue
        if not np.isfinite(corr):
            continue

        # ---- OHLC 统计 ----
        try:
            open_v = float(g["open"].iloc[0]) if "open" in g.columns else float(y_hist[0])
        except Exception:
            open_v = float(y_hist[0])
        try:
            high_v = float(g["high"].max()) if "high" in g.columns else float(np.nanmax(y_hist))
        except Exception:
            high_v = float(np.nanmax(y_hist))
        try:
            low_v = float(g["low"].min()) if "low" in g.columns else float(np.nanmin(y_hist))
        except Exception:
            low_v = float(np.nanmin(y_hist))
        close_v = float(y_hist[-1])

        results.append({
            "date": date,
            "corr": corr,
            "y_plot": y_hist,
            "open": open_v,
            "close": close_v,
            "high": high_v,
            "low": low_v,
        })

    results.sort(key=lambda it: -it["corr"])
    return results[:top_n]


# ==============================================================
# 主控制器
# ==============================================================
class Tab03MappingSimilarity(QObject):
    """读取历史分时数据并与当前分时图匹配，把相似曲线叠加到 Tab03 图中。"""

    _results_ready = Signal(int, object, str)  # (gen, results_or_None, error_msg)

    def __init__(self, ui, tab03_display, parent_window=None):
        super().__init__()
        self.ui = ui
        self.tab03_display = tab03_display
        self.parent_window = parent_window

        self._checkboxes = {}
        self._gen = 0
        self._history_cache = {}       # key=(mdf_path, table_name) -> (ts, df)
        self._last_trigger_key = None  # 防抖

        self._results_ready.connect(self._apply_results)

        self._init_checkboxes()
        self._init_signals()

        print("[Tab03-Mapping] 初始化完成")

    # ----------------------------------------------------------
    # CheckBox 管理
    # ----------------------------------------------------------
    def _init_checkboxes(self):
        for name in CHECKBOX_NAMES:
            cb = getattr(self.ui, name, None)
            if cb is None:
                print(f"[Tab03-Mapping] 警告：未找到控件 {name}")
                continue
            self._checkboxes[name] = cb
            cb.toggled.connect(
                lambda checked, n=name: self._on_checkbox_toggled(n, checked)
            )

        default_cb = self._checkboxes.get(DEFAULT_CHECKBOX)
        if default_cb is not None and not default_cb.isChecked():
            default_cb.blockSignals(True)
            default_cb.setChecked(True)
            default_cb.blockSignals(False)
            print(f"[Tab03-Mapping] 默认选中 {DEFAULT_CHECKBOX}")

    def _on_checkbox_toggled(self, name, checked):
        if not checked:
            if not any(cb.isChecked() for n, cb in self._checkboxes.items() if n != name):
                try:
                    if self.tab03_display is not None:
                        self.tab03_display.clear_mapping_lines()
                except Exception as e:
                    print(f"[Tab03-Mapping] 清除叠加线失败: {e}")
                self._last_trigger_key = None
                print("[Tab03-Mapping] 所有 checkbox 均未选中，清除叠加")
            return

        for n, cb in self._checkboxes.items():
            if n != name and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

        print(f"[Tab03-Mapping] 选中 {name}，触发重新匹配")
        self._last_trigger_key = None
        self._trigger_mapping()

    # ----------------------------------------------------------
    # 与 Tab03 联动
    # ----------------------------------------------------------
    def _init_signals(self):
        if self.tab03_display is not None:
            try:
                self.tab03_display.data_updated.connect(self._on_data_updated)
                print("[Tab03-Mapping] 已连接 Tab03.data_updated")
            except Exception as e:
                print(f"[Tab03-Mapping] 连接 data_updated 失败: {e}")

    def _on_data_updated(self, df):
        if df is None or len(df) == 0:
            return
        # 轻量防抖：目标日 + 长度 + 首尾值
        target_date = self._get_target_date()
        try:
            first_val = float(df["close"].iloc[0])
            last_val = float(df["close"].iloc[-1])
        except Exception:
            first_val, last_val = 0.0, 0.0
        key = (target_date, len(df), round(first_val, 2), round(last_val, 2))
        if key == self._last_trigger_key:
            return
        self._last_trigger_key = key
        self._trigger_mapping()

    # ----------------------------------------------------------
    # 参数读取
    # ----------------------------------------------------------
    def _get_mdf_path(self):
        for wname in ("txt_SQL_path_DB_name", "txt_SQL_path"):
            w = getattr(self.ui, wname, None)
            v = _widget_get_text(w)
            if v:
                return v
        return ""

    def _get_ts_code(self):
        return _normalize_ts_code(_widget_get_text(getattr(self.ui, "txt_ts_code", None)))

    def _get_freq(self):
        return _normalize_freq(_widget_get_text(getattr(self.ui, "txt_freq", None)))

    def _get_target_date(self):
        if self.tab03_display is not None:
            d = getattr(self.tab03_display, "_current_target_date", None)
            if d is not None:
                return d
        return datetime.now().date()

    def _get_selected_count(self):
        for name in CHECKBOX_NAMES:
            cb = self._checkboxes.get(name)
            if cb is not None and cb.isChecked():
                try:
                    return int(name[-2:])
                except Exception:
                    return 0
        return 0

    # ----------------------------------------------------------
    # 触发匹配
    # ----------------------------------------------------------
    def _trigger_mapping(self):
        n = self._get_selected_count()
        if n <= 0:
            return

        if self.tab03_display is None:
            return
        current_df = getattr(self.tab03_display, "current_df", None)
        if current_df is None or len(current_df) == 0:
            print("[Tab03-Mapping] 当前无分时数据，跳过匹配")
            return

        mdf_path = self._get_mdf_path()
        ts_code  = self._get_ts_code()
        freq     = self._get_freq()
        target_date = self._get_target_date()

        if not ts_code or not freq:
            print(f"[Tab03-Mapping] 参数不完整 ts_code='{ts_code}', freq='{freq}'")
            return
        if not mdf_path:
            print("[Tab03-Mapping] 未设置 txt_SQL_path_DB_name（MDF 文件路径），跳过匹配")
            return

        table_name = _make_table_name(ts_code, freq)
        if not table_name:
            print(f"[Tab03-Mapping] 无法生成表名 ts_code='{ts_code}', freq='{freq}'")
            return

        print(f"[Tab03-Mapping] 触发匹配: table={table_name}, N={n}, "
              f"target_date={target_date}")

        self._gen += 1
        gen = self._gen
        current_series = current_df["close"].astype(float).values.copy()

        def worker():
            try:
                results = self._match_and_load(
                    mdf_path=mdf_path,
                    table_name=table_name,
                    current_series=current_series,
                    target_date=target_date,
                    top_n=n,
                )
                self._results_ready.emit(gen, results, "")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._results_ready.emit(gen, None, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ----------------------------------------------------------
    # 主线程回调
    # ----------------------------------------------------------
    def _apply_results(self, gen, results, error):
        if gen != self._gen:
            print(f"[Tab03-Mapping] 丢弃过期结果 gen={gen} (当前 {self._gen})")
            return

        if error:
            print(f"[Tab03-Mapping] 匹配失败: {error}")
            try:
                if self.tab03_display is not None:
                    self.tab03_display.clear_mapping_lines()
            except Exception:
                pass
            return

        if results is None or len(results) == 0:
            print("[Tab03-Mapping] 无相似历史日可叠加")
            try:
                if self.tab03_display is not None:
                    self.tab03_display.clear_mapping_lines()
            except Exception:
                pass
            return

        colors = _generate_distinct_colors(len(results))
        data_list = []
        for i, r in enumerate(results):
            data_list.append({
                "label": f"{r['date_str']} (r={r['corr']:.2f})",
                "y": r["y_scaled"],
                "color": colors[i],
                "date_str": r["date_str"],
                "open": r["open"],
                "close": r["close"],
                "high": r["high"],
                "low": r["low"],
                "pct_change": r["pct_change"],
            })
        try:
            if self.tab03_display is not None:
                self.tab03_display.set_mapping_lines(data_list)
                print(f"[Tab03-Mapping] 已叠加 {len(data_list)} 条历史曲线: "
                      f"{[it['date_str'] for it in data_list]}")
        except Exception as e:
            print(f"[Tab03-Mapping] 应用匹配结果失败: {e}")

    # ----------------------------------------------------------
    # 后台线程：读取 SQL + 匹配
    # ----------------------------------------------------------
    def _match_and_load(self, mdf_path, table_name,
                        current_series, target_date, top_n):
        hist_df = self._read_history_cached(mdf_path, table_name, target_date)
        if hist_df is None or hist_df.empty:
            print(f"[Tab03-Mapping] 表 {table_name} 无可用于匹配的历史数据")
            return []

        hist_df = hist_df.copy()
        hist_df["trade_date"] = hist_df["trade_time"].dt.date
        hist_df = hist_df.sort_values("trade_time")
        groups = hist_df.groupby("trade_date", sort=True)

        results = _compute_similarity(
            current_series=current_series,
            groups=groups,
            exclude_date=target_date,
            top_n=top_n,
        )
        if not results:
            return []

        # ---- 每日前收（用于日涨跌幅）----
        all_dates_sorted = sorted(hist_df["trade_date"].unique())
        prev_close_map = {}
        for i in range(1, len(all_dates_sorted)):
            prev_d = all_dates_sorted[i - 1]
            prev_g = hist_df[hist_df["trade_date"] == prev_d]
            if len(prev_g) > 0:
                prev_close_map[all_dates_sorted[i]] = float(prev_g["close"].iloc[-1])

        # ---- 缩放历史曲线到当前首条价格 ----
        y_cur_start = float(current_series[0])
        scaled = []
        for r in results:
            y_plot = np.asarray(r["y_plot"], dtype=float)
            if y_plot.size == 0 or y_plot[0] == 0:
                continue
            y_scaled = y_plot * (y_cur_start / float(y_plot[0]))

            d = r["date"]
            prev_close = prev_close_map.get(d, None)
            if prev_close is not None and prev_close != 0:
                pct_change = (r["close"] / prev_close - 1.0) * 100.0
            elif r["open"] != 0:
                # 退化：相对当日开盘
                pct_change = (r["close"] / r["open"] - 1.0) * 100.0
            else:
                pct_change = 0.0

            scaled.append({
                "date": d,
                "date_str": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
                "corr": r["corr"],
                "y_scaled": y_scaled,
                "open": r["open"],
                "close": r["close"],
                "high": r["high"],
                "low": r["low"],
                "pct_change": pct_change,
            })

        return scaled

    # ----------------------------------------------------------
    # 读取历史（带缓存，仅成功时缓存）
    # ----------------------------------------------------------
    def _read_history_cached(self, mdf_path, table_name, target_date):
        key = (mdf_path, table_name)
        now_ts = time.time()
        cached = self._history_cache.get(key)
        if cached is not None:
            cached_ts, cached_df = cached
            if now_ts - cached_ts < HISTORY_CACHE_TTL_SEC:
                print(f"[Tab03-Mapping] 命中缓存 {table_name} "
                      f"(age={now_ts - cached_ts:.1f}s)")
                return cached_df
        df = self._read_history(mdf_path, table_name, target_date)
        if df is not None and not df.empty:
            self._history_cache[key] = (now_ts, df)
        return df

    def _connect_sql(self, mdf_path):
        """建立连接（DATABASE 模式优先，失败回退 AttachDbFilename 模式）。"""
        if not _PYODBC_AVAILABLE:
            raise RuntimeError("缺少 pyodbc 库，请先 pip install pyodbc")

        try:
            installed = pyodbc.drivers() or []
        except Exception:
            installed = []
        drivers = [d for d in ODBC_DRIVER_CANDIDATES if d in installed]
        if not drivers:
            raise RuntimeError(
                "未找到 ODBC Driver for SQL Server。\n"
                "请安装 'ODBC Driver 17 for SQL Server' 或 'ODBC Driver 18 for SQL Server'。"
            )

        errors = []
        # 1) DATABASE 模式
        for drv in drivers:
            cs = (
                f"DRIVER={{{drv}}};"
                f"SERVER={SQL_SERVER_INSTANCE};"
                f"DATABASE={SQL_DATABASE_NAME};"
                f"Trusted_Connection=yes;"
                f"TrustServerCertificate=yes;"
            )
            try:
                conn = pyodbc.connect(cs, timeout=15)
                print(f"[Tab03-Mapping] 已连接 SQL Server (DATABASE 模式) [{drv}]")
                return conn
            except Exception as e:
                errors.append(f"[{drv}] DATABASE: {e}")

        # 2) AttachDbFilename 模式
        if mdf_path and os.path.exists(mdf_path):
            for drv in drivers:
                cs = (
                    f"DRIVER={{{drv}}};"
                    f"SERVER={SQL_SERVER_INSTANCE};"
                    f"AttachDbFilename={mdf_path};"
                    f"DATABASE={SQL_DATABASE_NAME};"
                    f"Trusted_Connection=yes;"
                    f"TrustServerCertificate=yes;"
                )
                try:
                    conn = pyodbc.connect(cs, timeout=15)
                    print(f"[Tab03-Mapping] 已连接 SQL Server (ATTACH 模式) [{drv}]")
                    return conn
                except Exception as e:
                    errors.append(f"[{drv}] ATTACH: {e}")

        raise RuntimeError("无法连接 SQL Server:\n" + "\n".join(errors[-4:]))

    @staticmethod
    def _table_exists(conn, table_name):
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                    (SQL_SCHEMA, table_name),
                )
                return cur.fetchone() is not None
            finally:
                cur.close()
        except Exception as e:
            print(f"[Tab03-Mapping] 检查表存在性失败: {e}")
            return False

    @staticmethod
    def _list_matching_tables(conn, code):
        """列出数据库中所有 minute_data_<code>_% 的表名，用于诊断。"""
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = ? AND TABLE_NAME LIKE ?",
                    (SQL_SCHEMA, f"minute_data_{code}_%"),
                )
                return [row[0] for row in cur.fetchall()]
            finally:
                cur.close()
        except Exception as e:
            print(f"[Tab03-Mapping] 列出候选表失败: {e}")
            return []

    def _read_history(self, mdf_path, table_name, target_date):
        conn = self._connect_sql(mdf_path)
        try:
            if not self._table_exists(conn, table_name):
                code = ""
                m = re.match(r"^minute_data_([A-Za-z0-9]+)_", table_name)
                if m:
                    code = m.group(1)
                candidates = self._list_matching_tables(conn, code) if code else []
                print(f"[Tab03-Mapping] !! 表 {SQL_SCHEMA}.{table_name} 在数据库中不存在")
                if candidates:
                    print(f"[Tab03-Mapping] !! 数据库中存在相似表: {candidates}")
                else:
                    print(f"[Tab03-Mapping] !! 数据库中不存在任何 minute_data_{code}_* 表，"
                          f"请先用 Tab02 下载该股票的历史分钟数据")
                return pd.DataFrame()

            start_dt = datetime.combine(
                target_date - timedelta(days=HISTORY_LOOKBACK_DAYS),
                datetime.min.time(),
            )
            end_dt = datetime.combine(
                target_date + timedelta(days=1),
                datetime.min.time(),
            )
            # ★ 关键：SELECT 同时带 open/high/low（用于统计）
            sql = (
                f"SELECT [trade_time], [open], [close], [high], [low] "
                f"FROM [{SQL_SCHEMA}].[{table_name}] "
                f"WHERE [trade_time] >= ? AND [trade_time] < ? "
                f"ORDER BY [trade_time]"
            )
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter("ignore")
                df = pd.read_sql(sql, conn, params=(start_dt, end_dt))
            print(f"[Tab03-Mapping] 读取 {table_name} 共 {len(df)} 行")
            if df is not None and not df.empty:
                df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
                for c in ("open", "close", "high", "low"):
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df.dropna(subset=["trade_time", "close"]).reset_index(drop=True)
            return df
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ----------------------------------------------------------
    # 清理
    # ----------------------------------------------------------
    def shutdown(self):
        try:
            self._gen += 1  # 让在途结果作废
            self._history_cache.clear()
            self._last_trigger_key = None
        except Exception:
            pass