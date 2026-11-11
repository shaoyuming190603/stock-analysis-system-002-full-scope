# -*- coding: utf-8 -*-
"""
Tab03MinuteDataDisplayQt.py

目标：严格提取 dateEdit 指定日期的 1min 分时数据，不用日线替代。

v1.2 变更：
  * 新增 data_updated 信号（供历史形态匹配模块订阅）
  * 新增 self.current_df 属性（当前展示的 DataFrame）
  * 新增 set_mapping_lines / clear_mapping_lines（叠加历史曲线）
  * 新增 _update_y_limits / _update_legend（自适应 / 图例）
  * 新增 QTableWidget 匹配列表（日期/开/收/高/低/涨跌幅）
  * 定时刷新不触发 data_updated（节流：_is_timer_refresh / _notify_on_next）
"""
import warnings
warnings.filterwarnings('ignore')

import threading
from datetime import datetime, timedelta, time as dtime, date as date_cls

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

# ---------- 绕过 tdxpy 的交易时间拦截 ----------
try:
    import tdxpy.hq
    tdxpy.hq.time_frame = lambda *args, **kwargs: True
    print("[Tab03] 已绕过 tdxpy.hq.time_frame 交易时间拦截")
except Exception as e:
    print(f"[Tab03] 绕过 time_frame 失败（不影响启动）: {e}")

try:
    from mootdx.quotes import Quotes
    HAS_MOOTDX = True
except Exception as _e:
    HAS_MOOTDX = False
    print(f"[Tab03] mootdx 导入失败: {_e}")


# ------------------- 中文字体配置 -------------------
def _setup_chinese_font():
    preferred = [
        'Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'FangSong',
        'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((name for name in preferred if name in available), None)

    if chosen:
        plt.rcParams['font.sans-serif'] = [chosen] + plt.rcParams['font.sans-serif']
        print(f"[Tab03] 已启用中文字体：{chosen}")
    else:
        for path in [
            r'C:\Windows\Fonts\msyh.ttc',
            r'C:\Windows\Fonts\simhei.ttf',
            r'C:\Windows\Fonts\simsun.ttc',
        ]:
            try:
                font_manager.fontManager.addfont(path)
                name = font_manager.FontProperties(fname=path).get_name()
                plt.rcParams['font.sans-serif'] = [name] + plt.rcParams['font.sans-serif']
                print(f"[Tab03] 已通过字体文件启用中文：{name} ({path})")
                break
            except Exception:
                continue
    plt.rcParams['axes.unicode_minus'] = False


_setup_chinese_font()


# ------------------- 交易时段 -------------------
MORNING_OPEN = dtime(9, 30)
MORNING_CLOSE = dtime(11, 30)
AFTERNOON_OPEN = dtime(13, 0)
AFTERNOON_CLOSE = dtime(15, 0)
TOTAL_MINUTES = 240

MAX_BACK_DAYS = 15

TDX_SERVERS = [
    ('115.238.56.198', 7709),
    ('114.80.149.19', 7709),
    ('114.80.149.22', 7709),
    ('119.97.185.59', 7709),
    ('119.147.212.81', 7709),
    ('101.133.214.242', 7709),
]


# ------------------- 时间重建辅助函数 -------------------
def _build_trading_minutes(target_date, n):
    times = []
    cur = datetime.combine(target_date, dtime(9, 31))
    end_am = datetime.combine(target_date, dtime(11, 30))
    while cur <= end_am and len(times) < n:
        times.append(cur)
        cur += timedelta(minutes=1)
    cur = datetime.combine(target_date, dtime(13, 1))
    end_pm = datetime.combine(target_date, dtime(15, 0))
    while cur <= end_pm and len(times) < n:
        times.append(cur)
        cur += timedelta(minutes=1)
    return times[:n]


def _build_tick_positions_labels(datetimes):
    positions, labels = [], []
    for i, t in enumerate(datetimes):
        if t.minute in (0, 30):
            positions.append(i)
            labels.append(t.strftime('%H:%M'))
    return positions, labels


def _apply_tick_alignment(ax, labels):
    for tl, lab in zip(ax.get_xticklabels(), labels):
        if lab == '11:30':
            tl.set_ha('right')
        elif lab == '13:00':
            tl.set_ha('left')
        else:
            tl.set_ha('center')


# ------------------- 后台线程信号 -------------------
class _ClientSignals(QObject):
    ready = Signal(object)
    error = Signal(str)


class _FetchSignals(QObject):
    done = Signal(int, object, str)


# ============================================================
# 组件
# ============================================================
class Tab03MinuteDataDisplay(QWidget):
    """嵌入到 T302_实时行情历史匹配 页的分时图组件。"""

    # 对外信号：当前分时数据更新（供历史形态匹配模块订阅）
    data_updated = Signal(object)

    def __init__(self, ui, parent=None, persist_callback=None):
        super().__init__(parent)
        self.ui = ui
        self.parent_window = parent
        self.persist_callback = persist_callback

        self.symbol = ""
        self.client = None
        self.refresh_ms = 5000

        self._current_target_date = datetime.now().date()
        self._auto_adjust_on_empty = True
        self._adjust_count = 0
        self._pending_date_after_connect = None
        self._gen = 0
        self._stop_evt = None
        self._fetch_in_progress = False

        # ★ 当前展示的 DataFrame（供 mapping 组件读取）
        self.current_df = None
        # ★ 叠加的历史曲线 line 对象
        self._mapping_lines = []
        # ★ 是否在定时刷新（用于节流 data_updated）
        self._is_timer_refresh = False
        self._notify_on_next = True

        self._init_date_edit_today()

        self._timer = QTimer(self)
        self._timer.setInterval(self.refresh_ms)
        self._timer.timeout.connect(self._on_timer_tick)

        self._client_signals = _ClientSignals()
        self._client_signals.ready.connect(self._on_client_ready)
        self._client_signals.error.connect(self._on_client_error)

        self._fetch_signals = _FetchSignals()
        self._fetch_signals.done.connect(self._on_fetch_done)

        self._build_ui()

        QTimer.singleShot(1200, self._try_auto_start)

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        top_bar = QHBoxLayout()
        self.lab_symbol_info = QLabel("当前股票: (未设置)")
        self.lab_status = QLabel("状态: 等待初始化")
        self.btn_start = QPushButton("开始刷新")
        self.btn_stop = QPushButton("停止刷新")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        top_bar.addWidget(self.lab_symbol_info)
        top_bar.addStretch(1)
        top_bar.addWidget(self.lab_status)
        top_bar.addWidget(self.btn_start)
        top_bar.addWidget(self.btn_stop)
        layout.addLayout(top_bar)

        self.fig, self.ax = plt.subplots(figsize=(12, 5))
        self.fig.subplots_adjust(bottom=0.18, right=0.92)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=1)

        self.line_price, = self.ax.plot([], [], lw=1.5, color='#1f77b4', label='价格')
        self.line_vwap, = self.ax.plot([], [], lw=1.0, color='#ff7f0e',
                                       linestyle='--', label='累计均价')
        self.ax.set_xlabel('时间')
        self.ax.set_ylabel('价格 (元)')
        self.ax.legend(loc='upper left', fontsize=8)
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlim(-1, TOTAL_MINUTES)
        self.title = self.ax.set_title('分时图（1min K线）| 等待数据...')

        # ★ 匹配结果列表（价格曲线图下方）
        self.tbl_mapping = QTableWidget()
        self.tbl_mapping.setColumnCount(6)
        self.tbl_mapping.setHorizontalHeaderLabels(
            ["匹配日期", "开盘", "收盘", "最高", "最低", "涨跌幅(%)"]
        )
        self.tbl_mapping.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_mapping.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_mapping.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_mapping.verticalHeader().setVisible(False)
        self.tbl_mapping.setMaximumHeight(180)
        layout.addWidget(self.tbl_mapping)

    # ---------- dateEdit 读写 ----------
    def _init_date_edit_today(self):
        de = getattr(self.ui, 'dateEdit', None)
        if de is None:
            return
        try:
            try:
                qd = de.date()
                if qd.isValid() and qd.year() > 1900:
                    return
            except Exception:
                pass
            de.setDate(QDate.currentDate())
            print(f"[Tab03] dateEdit 已初始化为今天: "
                  f"{QDate.currentDate().toString('yyyy-MM-dd')}")
        except Exception as e:
            print(f"[Tab03] 初始化 dateEdit 失败: {e}")

    def _get_date_edit(self):
        pw = self.parent_window
        if pw is not None and hasattr(pw, 'get_date_edit_date'):
            try:
                d = pw.get_date_edit_date()
                if d is not None:
                    print(f"[Tab03] _get_date_edit 通过 parent_window 读取到: {d}")
                    return d
            except Exception as e:
                print(f"[Tab03] 调用 parent_window.get_date_edit_date 失败: {e}")

        de = getattr(self.ui, 'dateEdit', None)
        if de is None:
            print("[Tab03] _get_date_edit: ui 中不存在 dateEdit")
            return None
        try:
            qd = de.date()
            d = date_cls(qd.year(), qd.month(), qd.day())
            print(f"[Tab03] _get_date_edit 直接读取 dateEdit: {d}")
            return d
        except Exception as e:
            print(f"[Tab03] 读取 dateEdit 失败: {e}")
            return None

    def _set_date_edit(self, d):
        if d is None:
            return
        pw = self.parent_window
        if pw is not None and hasattr(pw, 'set_date_edit_date'):
            try:
                pw.set_date_edit_date(d)
                return
            except Exception as e:
                print(f"[Tab03] 调用 parent_window.set_date_edit_date 失败: {e}")

        de = getattr(self.ui, 'dateEdit', None)
        if de is None:
            return
        try:
            de.setDate(QDate(d.year, d.month, d.day))
            print(f"[Tab03] dateEdit 已调整为: {d.strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"[Tab03] 设置 dateEdit 失败: {e}")

    # ---------- 股票代码 ----------
    def _get_symbol_from_gui(self):
        txt = getattr(self.ui, 'txt_ts_code', None)
        if txt is None:
            return ""
        try:
            raw = txt.toPlainText().strip()
        except Exception:
            return ""
        if not raw:
            return ""
        return raw.split('.')[0].strip()[:6]

    def _prompt_for_symbol(self):
        code, ok = QInputDialog.getText(
            self, "需要股票代码",
            "检测到 txt_ts_code 为空。\n请输入股票代码（例如 300274 或 300274.SZ）："
        )
        if not ok or not code.strip():
            return ""
        code = code.strip()

        txt = getattr(self.ui, 'txt_ts_code', None)
        if txt is not None:
            try:
                txt.setPlainText(code)
            except Exception:
                pass

        if self.persist_callback:
            try:
                self.persist_callback()
            except Exception as e:
                print(f"[Tab03] 持久化失败: {e}")

        return code.split('.')[0].strip()[:6]

    def ensure_symbol(self, interactive=True):
        symbol = self._get_symbol_from_gui()
        if symbol:
            return symbol
        if not interactive:
            return ""
        return self._prompt_for_symbol()

    # ---------- 启停 ----------
    def _try_auto_start(self):
        symbol = self.ensure_symbol(interactive=True)
        if not symbol:
            self.lab_status.setText("状态: 未设置股票代码")
            return
        self.symbol = symbol
        self.lab_symbol_info.setText(f"当前股票: {symbol}")

        d = self._get_date_edit() or datetime.now().date()
        print(f"[Tab03] 自动启动，目标日期 = {d}")
        self._current_target_date = d
        self._adjust_count = 0
        self._auto_adjust_on_empty = True
        self._notify_on_next = True
        self._refresh_for_date(d, adjust_on_empty=True)

    def _on_start_clicked(self):
        symbol = self.ensure_symbol(interactive=True)
        if not symbol:
            QMessageBox.warning(self, "提示", "未填写 txt_ts_code")
            return
        if symbol != self.symbol:
            self.symbol = symbol
            self.client = None
        self.lab_symbol_info.setText(f"当前股票: {symbol}")

        d = self._get_date_edit() or datetime.now().date()
        self._current_target_date = d
        self._adjust_count = 0
        self._auto_adjust_on_empty = True
        self._notify_on_next = True
        self._refresh_for_date(d, adjust_on_empty=True)

    def _on_stop_clicked(self):
        self._timer.stop()
        if self._stop_evt is not None:
            self._stop_evt.set()
            self._stop_evt = None
        self._gen += 1
        self._fetch_in_progress = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lab_status.setText("状态: 已停止")

    def _start_client_async(self):
        self.lab_status.setText("状态: 连接 TDX 中...")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        def worker():
            try:
                c = self._make_client()
                if c is None:
                    self._client_signals.error.emit("所有 TDX 服务器均不可用")
                else:
                    self._client_signals.ready.emit(c)
            except Exception as e:
                self._client_signals.error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _make_client(self):
        if not HAS_MOOTDX:
            raise RuntimeError("mootdx 未安装")

        test_date = datetime.now().date()
        while test_date.weekday() >= 5:
            test_date -= timedelta(days=1)
        test_date_str = test_date.strftime('%Y%m%d')

        fallback_client = None
        for ip, port in TDX_SERVERS:
            try:
                c = Quotes.factory(market='std', server=(ip, port), timeout=10)
                if fallback_client is None:
                    fallback_client = c
                try:
                    test = c.minutes(symbol='000001', date=test_date_str)
                except Exception as e:
                    print(f"[Tab03] {ip}:{port} minutes 测试异常: {e}")
                    continue
                if test is not None and len(test) > 0:
                    print(f"[Tab03] 已连接 {ip}:{port}"
                          f"（minutes 测试 date={test_date_str} 返回 {len(test)} 条）")
                    return c
                print(f"[Tab03] {ip}:{port} minutes 测试返回 0 行（date={test_date_str}）")
            except Exception as e:
                print(f"[Tab03] {ip}:{port} 创建客户端异常: {e}")

        if fallback_client is not None:
            print("[Tab03] 警告：所有服务器 minutes 测试均失败，回退使用第一个可创建的客户端")
            return fallback_client
        print("[Tab03] 所有 TDX 服务器均不可用")
        return None

    def _on_client_ready(self, client):
        self.client = client
        self.lab_status.setText("状态: 已连接，获取数据中...")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        if self._pending_date_after_connect is not None:
            self._current_target_date = self._pending_date_after_connect
            self._pending_date_after_connect = None

        if not self._timer.isActive():
            self._timer.start()

        self._refresh_for_date(self._current_target_date,
                               adjust_on_empty=self._auto_adjust_on_empty)

    def _on_client_error(self, msg):
        self.lab_status.setText(f"状态: 错误 - {msg}")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        try:
            self._timer.stop()
        except Exception:
            pass
        print(f"[Tab03] 客户端错误: {msg}")

    # ---------- 数据提取 ----------
    def _fetch_minute_for_date(self, client, symbol, target_date, stop_evt):
        if stop_evt is not None and stop_evt.is_set():
            return pd.DataFrame()

        today = datetime.now().date()
        if target_date > today:
            print(f"[Tab03] target_date={target_date} 晚于 today={today}，返回空")
            return pd.DataFrame()

        if target_date.weekday() >= 5:
            print(f"[Tab03] 警告：target_date={target_date} 是周末"
                  f"（weekday={target_date.weekday()}），历史分时接口可能无数据")

        date_str = target_date.strftime('%Y%m%d')
        print(f"[Tab03] 调用 client.minutes(symbol='{symbol}', date='{date_str}')")

        try:
            raw = client.minutes(symbol=symbol, date=date_str)
        except Exception as e:
            print(f"[Tab03] client.minutes 调用异常: {e}")
            return pd.DataFrame()

        if raw is None or len(raw) == 0:
            print(f"[Tab03] client.minutes 返回空（date={date_str}）")
            return pd.DataFrame()

        print(f"[Tab03] client.minutes 返回 {len(raw)} 条，"
              f"columns={list(raw.columns)[:8]}, index_type={type(raw.index).__name__}")

        df = self._normalize_minutes(raw, target_date)
        if df.empty:
            print("[Tab03] minutes 数据 normalize 后为空")
            return pd.DataFrame()

        print(f"[Tab03] 最终 {len(df)} 条，时间范围 "
              f"{df['datetime'].min()} ~ {df['datetime'].max()}")
        return df

    @staticmethod
    def _normalize_minutes(raw, target_date):
        df = raw.copy()

        if isinstance(df.index, pd.DatetimeIndex):
            idx_name = df.index.name
            df = df.reset_index()
            if idx_name is None:
                df = df.rename(columns={df.columns[0]: 'datetime'})
            elif idx_name != 'datetime':
                df = df.rename(columns={idx_name: 'datetime'})
            print("[Tab03] _normalize_minutes: DatetimeIndex -> 'datetime' 列")
        else:
            df = df.reset_index(drop=True)

        dt_series = None
        for c in ('datetime', 'date', 'time'):
            if c in df.columns:
                try:
                    dt_series = pd.to_datetime(df[c])
                    print(f"[Tab03] _normalize_minutes: 使用列 '{c}'")
                    break
                except Exception:
                    dt_series = None

        if dt_series is None and {'year', 'month', 'day'}.issubset(df.columns):
            hour = df['hour'] if 'hour' in df.columns else 0
            minute = df['minute'] if 'minute' in df.columns else 0
            try:
                dt_series = pd.to_datetime(pd.DataFrame({
                    'year': df['year'], 'month': df['month'], 'day': df['day'],
                    'hour': hour, 'minute': minute,
                }))
                print("[Tab03] _normalize_minutes: 使用 year/month/day/hour/minute")
            except Exception:
                dt_series = None

        if dt_series is None:
            n = len(df)
            print(f"[Tab03] _normalize_minutes: 无时间列，根据 target_date={target_date} "
                  f"和 {n} 条记录重建交易分钟时间戳")
            rebuilt = _build_trading_minutes(target_date, n)
            if len(rebuilt) < n:
                print(f"[Tab03] _normalize_minutes: 重建时间不足 "
                      f"({len(rebuilt)} < {n})，可能不是完整交易日数据")
            dt_series = pd.Series(rebuilt[:n])

        df['datetime'] = pd.to_datetime(pd.Series(np.asarray(dt_series)))
        df = df.dropna(subset=['datetime']).reset_index(drop=True)
        if df.empty:
            print("[Tab03] _normalize_minutes: 时间重建/转换后为空")
            return pd.DataFrame()

        if 'close' not in df.columns:
            if 'price' in df.columns:
                df['close'] = df['price']
            else:
                raise ValueError(f"找不到价格列，实际列：{df.columns.tolist()}")
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close']).reset_index(drop=True)

        df = df[df['datetime'].dt.date == target_date].copy()
        df = df.sort_values('datetime').reset_index(drop=True)
        df = df.drop_duplicates(subset=['datetime']).reset_index(drop=True)

        return df

    # ---------- 刷新调度 ----------
    def _refresh_for_date(self, target_date, adjust_on_empty=False):
        self._current_target_date = target_date
        self._auto_adjust_on_empty = adjust_on_empty
        print(f"[Tab03] _refresh_for_date: target_date={target_date}, "
              f"adjust_on_empty={adjust_on_empty}")

        if self._stop_evt is not None:
            self._stop_evt.set()
        evt = threading.Event()
        self._stop_evt = evt
        self._gen += 1
        gen = self._gen

        if self.client is None:
            self._pending_date_after_connect = target_date
            if not self.symbol:
                sym = self.ensure_symbol(interactive=True)
                if not sym:
                    self.lab_status.setText("状态: 未设置股票代码")
                    return
                self.symbol = sym
                self.lab_symbol_info.setText(f"当前股票: {sym}")
            self._start_client_async()
            return

        self._fetch_in_progress = True
        self.lab_status.setText(
            f"状态: 获取 {target_date.strftime('%Y-%m-%d')} 1min 分时数据..."
        )

        client = self.client
        symbol = self.symbol

        def worker():
            try:
                df = self._fetch_minute_for_date(client, symbol, target_date, evt)
                if evt.is_set():
                    return
                self._fetch_signals.done.emit(gen, df, "")
            except Exception as e:
                if evt.is_set():
                    return
                self._fetch_signals.done.emit(gen, None, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_fetch_done(self, gen, df, err):
        if gen != self._gen:
            return
        self._fetch_in_progress = False

        if err:
            self.title.set_text(f'{self.symbol} | 获取异常：{err}')
            self.lab_status.setText(f"状态: 获取失败 - {err}")
            self.canvas.draw_idle()
            print(f"[Tab03] 更新失败：{err}")
            return

        if df is None or len(df) == 0:
            if self._auto_adjust_on_empty and self._adjust_count < MAX_BACK_DAYS:
                new_date = self._current_target_date - timedelta(days=1)
                self._adjust_count += 1
                print(f"[Tab03] {self._current_target_date} 无数据，自动回退到 {new_date}")
                self._set_date_edit(new_date)
                self._refresh_for_date(new_date, adjust_on_empty=True)
                return

            self.title.set_text(
                f'{self.symbol} | {self._current_target_date.strftime("%Y-%m-%d")} 无数据'
            )
            self.lab_status.setText(
                f"状态: {self._current_target_date.strftime('%Y-%m-%d')} 无数据"
            )
            self.canvas.draw_idle()
            return

        self._adjust_count = 0
        self._auto_adjust_on_empty = False

        notify = getattr(self, "_notify_on_next", True)
        self._notify_on_next = False
        self._render_df(df, notify=notify)

        self.lab_status.setText(
            f"状态: 已显示 {self._current_target_date.strftime('%Y-%m-%d')} "
            f"数据（{len(df)} 条）"
        )

    def _on_timer_tick(self):
        if self.client is None or self._fetch_in_progress:
            return
        today = datetime.now().date()
        if self._current_target_date != today:
            return
        # ★ 定时刷新不 emit data_updated
        self._is_timer_refresh = True
        self._refresh_for_date(today, adjust_on_empty=False)

    # ---------- 绘图 ----------
    def _render_df(self, df, notify=True):
        try:
            x = np.arange(len(df))
            y = df['close'].astype(float).values
            self.line_price.set_data(x, y)

            vol_col = 'vol' if 'vol' in df.columns else (
                'volume' if 'volume' in df.columns else None)
            if vol_col and df[vol_col].sum() > 0:
                cum_vol = df[vol_col].astype(float).cumsum().values
                cum_amount = (y * df[vol_col].astype(float).values).cumsum()
                with np.errstate(divide='ignore', invalid='ignore'):
                    vwap = np.where(cum_vol > 0, cum_amount / cum_vol, np.nan)
                self.line_vwap.set_data(x, vwap)
            else:
                self.line_vwap.set_data([], [])

            positions, labels = _build_tick_positions_labels(df['datetime'].tolist())
            self.ax.set_xticks(positions)
            self.ax.set_xticklabels(labels)
            _apply_tick_alignment(self.ax, labels)

            latest, first = y[-1], y[0]
            chg = (latest / first - 1) * 100 if first else 0.0
            self.title.set_text(
                f'{self.symbol} 分时图 {self._current_target_date.strftime("%Y-%m-%d")} '
                f'| 最新：{latest:.2f}  较首条：{chg:+.2f}%  '
                f'| K线数：{len(df)}  更新：{datetime.now().strftime("%H:%M:%S")}'
            )

            # ★ 更新 current_df（供匹配模块读取）
            self.current_df = df.copy()

            # ★ 统一刷新 y 范围（包含叠加曲线）
            self._update_y_limits()
            self._update_legend()

            self.canvas.draw_idle()

            # ★ 通知匹配模块（仅非定时刷新时）
            if notify:
                try:
                    self.data_updated.emit(self.current_df)
                except Exception as e:
                    print(f"[Tab03] emit data_updated 失败: {e}")

        except Exception as e:
            print(f"[Tab03] 绘图失败：{e}")
            self.title.set_text(f'{self.symbol} | 绘图异常：{e}')
            self.canvas.draw_idle()

    # ---------- 叠加历史曲线 ----------
    def set_mapping_lines(self, data_list):
        """把历史分时曲线叠加到 ax 上，并更新下方统计表格。

        data_list: list of dict
            {'label','y','color','date_str','open','close','high','low','pct_change'}
        """
        self.clear_mapping_lines()

        if not data_list:
            self.canvas.draw_idle()
            return

        for item in data_list:
            try:
                y = np.asarray(item["y"], dtype=float)
                x = np.arange(len(y))
                line, = self.ax.plot(
                    x, y,
                    lw=0.9,
                    color=item["color"],
                    alpha=0.75,
                    label=item["label"],
                )
                self._mapping_lines.append(line)
            except Exception as e:
                print(f"[Tab03] 叠加 {item.get('label')} 失败: {e}")

        self._update_y_limits()
        self._update_legend()
        self._update_stats_table(data_list)
        self.canvas.draw_idle()

    def clear_mapping_lines(self):
        for line in self._mapping_lines:
            try:
                line.remove()
            except Exception:
                pass
        self._mapping_lines = []
        self._update_stats_table([])
        self._update_legend()
        self._update_y_limits()
        self.canvas.draw_idle()

    def _update_legend(self):
        try:
            handles, labels = self.ax.get_legend_handles_labels()
            if handles:
                self.ax.legend(handles, labels, loc='upper left', fontsize=8)
            else:
                legend = self.ax.get_legend()
                if legend is not None:
                    legend.remove()
        except Exception as e:
            print(f"[Tab03] 更新图例失败: {e}")

    def _update_y_limits(self):
        try:
            arrays = []

            # 当前价格
            try:
                y_cur = self.line_price.get_ydata()
                if y_cur is not None and len(y_cur) > 0:
                    arr = np.asarray(y_cur, dtype=float)
                    arr = arr[np.isfinite(arr)]
                    if len(arr) > 0:
                        arrays.append(arr)
            except Exception:
                pass

            # VWAP
            try:
                y_v = self.line_vwap.get_ydata()
                if y_v is not None and len(y_v) > 0:
                    arr = np.asarray(y_v, dtype=float)
                    arr = arr[np.isfinite(arr)]
                    if len(arr) > 0:
                        arrays.append(arr)
            except Exception:
                pass

            # 叠加的历史曲线
            for line in self._mapping_lines:
                try:
                    arr = np.asarray(line.get_ydata(), dtype=float)
                    arr = arr[np.isfinite(arr)]
                    if len(arr) > 0:
                        arrays.append(arr)
                except Exception:
                    pass

            if not arrays:
                return

            flat = np.concatenate(arrays)
            if len(flat) == 0:
                return

            y_min, y_max = float(np.min(flat)), float(np.max(flat))
            pad = (y_max - y_min) * 0.02 if y_max > y_min else max(abs(y_max) * 0.01, 0.1)
            self.ax.set_ylim(y_min - pad, y_max + pad)
        except Exception as e:
            print(f"[Tab03] 更新 y 范围失败: {e}")

    def _update_stats_table(self, stats_list):
        try:
            if not stats_list:
                self.tbl_mapping.setRowCount(0)
                return
            self.tbl_mapping.setRowCount(len(stats_list))
            for i, s in enumerate(stats_list):
                self.tbl_mapping.setItem(i, 0, QTableWidgetItem(str(s.get("date_str", ""))))
                self.tbl_mapping.setItem(i, 1, QTableWidgetItem(f"{float(s.get('open', 0)):.2f}"))
                self.tbl_mapping.setItem(i, 2, QTableWidgetItem(f"{float(s.get('close', 0)):.2f}"))
                self.tbl_mapping.setItem(i, 3, QTableWidgetItem(f"{float(s.get('high', 0)):.2f}"))
                self.tbl_mapping.setItem(i, 4, QTableWidgetItem(f"{float(s.get('low', 0)):.2f}"))

                pct = float(s.get('pct_change', 0.0))
                item = QTableWidgetItem(f"{pct:+.2f}%")
                if pct > 0:
                    item.setForeground(QColor(214, 39, 40))     # 红：涨
                elif pct < 0:
                    item.setForeground(QColor(44, 160, 44))     # 绿：跌
                self.tbl_mapping.setItem(i, 5, item)
        except Exception as e:
            print(f"[Tab03] 更新统计表格失败: {e}")

    # ---------- 对外接口 ----------
    def change_date_reload(self):
        print("[Tab03] change_date_reload 被调用")

        if self._stop_evt is not None:
            self._stop_evt.set()
            self._stop_evt = None
        self._gen += 1
        self._fetch_in_progress = False

        d = self._get_date_edit() or datetime.now().date()
        print(f"[Tab03] change_date_reload 目标日期 = {d}")
        self._current_target_date = d
        self._adjust_count = 0
        self._auto_adjust_on_empty = False
        self._notify_on_next = True

        if not self.symbol:
            sym = self.ensure_symbol(interactive=True)
            if not sym:
                self.lab_status.setText("状态: 未设置股票代码")
                return
            self.symbol = sym
            self.lab_symbol_info.setText(f"当前股票: {sym}")

        if self.client is None:
            self._pending_date_after_connect = d
            self._start_client_async()
            return

        self._refresh_for_date(d, adjust_on_empty=False)

        if d == datetime.now().date() and not self._timer.isActive():
            self._timer.start()

    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            if self._stop_evt is not None:
                self._stop_evt.set()
                self._stop_evt = None
        except Exception:
            pass


# ============================================================
# 独立运行入口
# ============================================================
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QDateEdit, QPushButton,
        QTextEdit, QWidget, QLabel
    )

    class _StandaloneUI:
        def __init__(self):
            self.txt_ts_code = QTextEdit()
            self.txt_ts_code.setPlainText("000001.SZ")
            self.txt_ts_code.setMaximumHeight(38)
            self.txt_ts_code.setToolTip("股票代码（取前6位）")

            self.dateEdit = QDateEdit()
            self.dateEdit.setCalendarPopup(True)
            self.dateEdit.setDisplayFormat("yyyy-MM-dd")
            self.dateEdit.setDate(QDate.currentDate())

            self.pushBttn_ChangeDate = QPushButton("应用日期 (ChangeDate)")

    class _StandaloneWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Tab03 独立测试 | 1min 分时数据（按 dateEdit 提取）")
            self.resize(1200, 800)

            self.ui = _StandaloneUI()

            central = QWidget()
            self.setCentralWidget(central)
            root = QVBoxLayout(central)

            top = QHBoxLayout()
            top.addWidget(QLabel("股票代码："))
            top.addWidget(self.ui.txt_ts_code, stretch=1)
            top.addWidget(QLabel(" 日期："))
            top.addWidget(self.ui.dateEdit)
            top.addWidget(self.ui.pushBttn_ChangeDate)
            root.addLayout(top)

            self.tab03 = Tab03MinuteDataDisplay(self.ui, self)
            root.addWidget(self.tab03, stretch=1)

            self.ui.pushBttn_ChangeDate.clicked.connect(
                self.tab03.change_date_reload
            )

        def closeEvent(self, event):
            try:
                self.tab03.shutdown()
            except Exception:
                pass
            super().closeEvent(event)

    app = QApplication(sys.argv)
    win = _StandaloneWindow()
    win.show()
    sys.exit(app.exec())