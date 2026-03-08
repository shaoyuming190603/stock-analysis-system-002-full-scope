"""
Tushare API 函数列表（自动生成）
版本: 1.0.0
生成时间: 2026-03-08 15:01:08
"""

import tushare as ts
import pandas as pd
import time
from datetime import datetime
import os

def init_tushare():
    """从环境变量初始化 Tushare API。"""
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise ValueError("环境变量 TUSHARE_TOKEN 未设置")
    ts.set_token(token)
    return ts.pro_api()

# 全局 pro 对象，供各函数复用
pro = init_tushare()



@add_version_info(version="1.0.0", author="AutoGen", description="从网页生成的 stock_basic 查询函数")
def fetch_stock_basic(**kwargs):
    """
    从 Tushare 获取 stock_basic 数据。
    参数：参照 Tushare API 文档。
    返回：DataFrame
    """
    # 导入tushare
# 初始化pro接口

# 拉取数据
df = pro.stock_basic(**{
    "ts_code": "",
    "name": "",
    "exchange": "",
    "market": "",
    "is_hs": "",
    "list_status": "",
    "limit": "",
    "offset": ""
}, fields=[
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "cnspell",
    "market",
    "list_date",
    "act_name",
    "act_ent_type"
])
return df



@add_version_info(version="1.0.0", author="AutoGen", description="从网页生成的 stk_premarket 查询函数")
def fetch_stk_premarket(**kwargs):
    """
    从 Tushare 获取 stk_premarket 数据。
    参数：参照 Tushare API 文档。
    返回：DataFrame
    """
    # 导入tushare
# 初始化pro接口

# 拉取数据
df = pro.stk_premarket(**{
    "ts_code": "",
    "trade_date": "",
    "start_date": "",
    "end_date": "",
    "limit": "",
    "offset": ""
}, fields=[
    "trade_date",
    "ts_code",
    "total_share",
    "float_share",
    "pre_close",
    "up_limit",
    "down_limit"
])
return df



@add_version_info(version="1.0.0", author="AutoGen", description="从网页生成的 trade_cal 查询函数")
def fetch_trade_cal(**kwargs):
    """
    从 Tushare 获取 trade_cal 数据。
    参数：参照 Tushare API 文档。
    返回：DataFrame
    """
    # 导入tushare
# 初始化pro接口

# 拉取数据
df = pro.trade_cal(**{
    "exchange": "",
    "cal_date": "",
    "start_date": "",
    "end_date": "",
    "is_open": "",
    "limit": "",
    "offset": ""
}, fields=[
    "exchange",
    "cal_date",
    "is_open",
    "pretrade_date"
])
return df

