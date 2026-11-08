import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib import font_manager
from mootdx.quotes import Quotes
from datetime import datetime, timedelta, time as dtime
import warnings
warnings.filterwarnings('ignore')

# ------------------- 中文字体配置 -------------------
def setup_chinese_font():
    preferred = [
        'Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'FangSong',
        'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((name for name in preferred if name in available), None)

    if chosen:
        plt.rcParams['font.sans-serif'] = [chosen] + plt.rcParams['font.sans-serif']
        print(f"已启用中文字体：{chosen}")
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
                print(f"已通过字体文件启用中文：{name} ({path})")
                break
            except Exception:
                continue
        else:
            print("警告：未找到可用中文字体，中文可能仍显示为方框。")

    plt.rcParams['axes.unicode_minus'] = False

setup_chinese_font()

# ------------------- 配置 -------------------
SYMBOL = "300274"
REFRESH_MS = 5000

TDX_SERVERS = [
    ('115.238.56.198', 7709),
    ('114.80.149.19', 7709),
    ('114.80.149.22', 7709),
    ('119.97.185.59', 7709),
    ('119.147.212.81', 7709),
    ('101.133.214.242', 7709),
]

def make_client():
    for ip, port in TDX_SERVERS:
        try:
            client = Quotes.factory(market='std', server=(ip, port), timeout=10)
            test = client.minute(symbol=SYMBOL)
            if test is not None and len(test) > 0:
                print(f"已连接 {ip}:{port}，分时快照数量：{len(test)}")
                print("minute() 返回列名：", test.columns.tolist())
                return client
            else:
                print(f"{ip}:{port} 连接成功，但返回 0 行，跳过。")
        except Exception as e:
            print(f"{ip}:{port} 不可用：{e}")
    raise ConnectionError("所有备选服务器均无法返回非空 minute() 数据。")

client = make_client()

# ------------------- 交易时段工具 -------------------
MORNING_OPEN = dtime(9, 30)
MORNING_CLOSE = dtime(11, 30)
AFTERNOON_OPEN = dtime(13, 0)
AFTERNOON_CLOSE = dtime(15, 0)
TOTAL_MINUTES = 240

def generate_trading_minutes(base_date, n):
    """生成交易分钟时间戳，午休跳过。"""
    times = []
    cur = datetime.combine(base_date, MORNING_OPEN)
    while cur <= datetime.combine(base_date, MORNING_CLOSE) and len(times) < n:
        times.append(cur)
        cur += timedelta(minutes=1)
    cur = datetime.combine(base_date, AFTERNOON_OPEN)
    while cur <= datetime.combine(base_date, AFTERNOON_CLOSE) and len(times) < n:
        times.append(cur)
        cur += timedelta(minutes=1)
    return times[:n]

def build_tick_positions_labels(datetimes):
    """挑出整点/半点作为刻度，返回 (positions, labels)。"""
    positions, labels = [], []
    for i, t in enumerate(datetimes):
        if t.minute in (0, 30):
            positions.append(i)
            labels.append(t.strftime('%H:%M'))
    return positions, labels

def apply_tick_alignment(ax, labels):
    """
    逐个设置刻度标签的水平对齐：
      - 11:30 → 右对齐（向左展开）
      - 13:00 → 左对齐（向右展开）
      - 其他   → 居中
    这样 11:30 与 13:00 在相邻位置也不会互相压盖。
    """
    for tl, lab in zip(ax.get_xticklabels(), labels):
        if lab == '11:30':
            tl.set_ha('right')
        elif lab == '13:00':
            tl.set_ha('left')
        else:
            tl.set_ha('center')

# ------------------- 获取并重构数据 -------------------
def fetch_and_align():
    raw = client.minute(symbol=SYMBOL)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()

    n = len(raw)
    today = datetime.now().date()
    df = raw.copy()
    df['datetime'] = generate_trading_minutes(today, n)
    df = df.sort_values('datetime').reset_index(drop=True)

    if 'price' in df.columns:
        df['close'] = df['price']
    elif 'close' not in df.columns:
        raise ValueError(f"找不到价格列，实际列：{df.columns.tolist()}")

    return df

# ------------------- 图表初始化 -------------------
fig, ax = plt.subplots(figsize=(13, 6))
fig.subplots_adjust(bottom=0.18, right=0.92)

line_price, = ax.plot([], [], lw=1.5, color='#1f77b4', label='价格（快照）')
line_vwap, = ax.plot([], [], lw=1.0, color='#ff7f0e', linestyle='--', label='累计均价')

ax.set_xlabel('时间')
ax.set_ylabel('价格 (元)')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)

# 固定交易分钟序号轴范围
ax.set_xlim(-1, TOTAL_MINUTES)

title = ax.set_title(f'{SYMBOL} 今日分时图（minute 快照）| 等待数据...')

# ------------------- 动画更新 -------------------
def update(frame):
    try:
        df = fetch_and_align()
        if df.empty:
            title.set_text(f'{SYMBOL} | 暂无数据')
            return line_price, line_vwap, title

        x = np.arange(len(df))
        y = df['close'].values
        line_price.set_data(x, y)

        vol_col = 'vol' if 'vol' in df.columns else ('volume' if 'volume' in df.columns else None)
        if vol_col and df[vol_col].sum() > 0:
            cum_vol = df[vol_col].cumsum().values
            cum_amount = (df['close'].values * df[vol_col].values).cumsum()
            vwap = cum_amount / cum_vol
            line_vwap.set_data(x, vwap)
            all_y = np.concatenate([y, vwap])
        else:
            line_vwap.set_data([], [])
            all_y = y

        y_min, y_max = float(np.nanmin(all_y)), float(np.nanmax(all_y))
        pad = (y_max - y_min) * 0.02 if y_max > y_min else max(abs(y_max) * 0.01, 0.1)
        ax.set_ylim(y_min - pad, y_max + pad)

        # 刻度位置与标签
        positions, labels = build_tick_positions_labels(df['datetime'].tolist())
        ax.set_xticks(positions)
        ax.set_xticklabels(labels)
        # 关键：11:30 右对齐、13:00 左对齐，避免相邻标签重叠
        apply_tick_alignment(ax, labels)

        latest, first = y[-1], y[0]
        chg = (latest / first - 1) * 100 if first else 0.0
        title.set_text(
            f'{SYMBOL} 分时图（minute 快照，已剔除午休）| 最新：{latest:.2f}  '
            f'较首条：{chg:+.2f}%  |  快照数：{len(df)}  '
            f'更新：{datetime.now().strftime("%H:%M:%S")}'
        )
        return line_price, line_vwap, title

    except Exception as e:
        print(f"更新失败：{e}")
        title.set_text(f'{SYMBOL} | 更新异常：{e}')
        return line_price, line_vwap, title

# ------------------- 启动 -------------------
ani = FuncAnimation(
    fig, update, interval=REFRESH_MS, blit=False, cache_frame_data=False
)

plt.ion()
plt.show(block=True=