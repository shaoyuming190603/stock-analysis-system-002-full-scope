"""
Tushare API 函数列表（自动生成）
版本: 1.0.0
生成时间: 2026-04-10 09:07:55
"""

import tushare as ts
import pandas as pd
import time
from datetime import datetime
import os

def init_tushare():
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise ValueError("环境变量 TUSHARE_TOKEN 未设置")
    ts.set_token(token)
    return ts.pro_api()

pro = init_tushare()

