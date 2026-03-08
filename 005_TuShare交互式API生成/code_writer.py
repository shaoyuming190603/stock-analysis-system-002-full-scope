"""
代码生成与文件写入模块，负责解析剪贴板并追加函数到目标文件。
版本: 1.3.0
新增：自动检查重复函数，避免重复添加。
"""
import os
import re
import pyperclip
from datetime import datetime
from version_utils import add_version_info

class CodeWriter:
    def __init__(self, target_file="TuShareAPI_FunctionList.py", token_env="TUSHARE_TOKEN"):
        self.target_file = target_file
        self.token = os.getenv(token_env)
        if not self.token:
            raise EnvironmentError(f"环境变量 {token_env} 未设置。")
        self._ensure_file_header()

    def _ensure_file_header(self):
        if not os.path.exists(self.target_file):
            header = f'''"""
Tushare API 函数列表（自动生成）
版本: 1.0.0
生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
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

'''
            with open(self.target_file, 'w', encoding='utf-8') as f:
                f.write(header)

    def read_clipboard_code(self):
        return pyperclip.paste()

    def parse_function_name(self, code_text):
        match = re.search(r'pro\.(\w+)\(', code_text)
        if match:
            return match.group(1)
        return None

    def generate_function_code(self, api_name, code_text):
        lines = code_text.strip().split('\n')
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('import ') or 'ts.pro_api' in stripped or stripped.startswith('pro ='):
                continue
            if stripped.startswith('print(df)'):
                line = line.replace('print(df)', 'return df')
            filtered_lines.append(line)
        cleaned_code = '\n'.join(filtered_lines)

        if not cleaned_code.strip().endswith('return df'):
            cleaned_code += '\n    return df'

        func_template = f'''
@add_version_info(version="1.0.0", author="AutoGen", description="从网页生成的 {api_name} 查询函数")
def fetch_{api_name}(**kwargs):
    """
    从 Tushare 获取 {api_name} 数据。
    参数：参照 Tushare API 文档。
    返回：DataFrame
    """
    {cleaned_code}
'''
        return func_template

    def _get_existing_function_names(self):
        """从目标文件中提取所有已存在的函数名（以 def fetch_ 开头）。"""
        if not os.path.exists(self.target_file):
            return set()
        with open(self.target_file, 'r', encoding='utf-8') as f:
            content = f.read()
        # 使用正则匹配 def fetch_xxx(...)
        pattern = r'def\s+(fetch_\w+)\s*\('
        matches = re.findall(pattern, content)
        return set(matches)

    def append_function(self, function_code):
        # 提取当前要添加的函数名
        func_name_match = re.search(r'def\s+(fetch_\w+)\s*\(', function_code)
        if not func_name_match:
            print("警告：无法从函数代码中提取函数名，跳过检查。")
            # 为安全起见，仍然写入？或者返回。这里选择继续写入但提示。
        else:
            func_name = func_name_match.group(1)
            existing = self._get_existing_function_names()
            if func_name in existing:
                print(f"\n函数 {func_name} 已存在于文件中，跳过添加。")
                return

        # 在终端打印生成的函数内容
        print("\n" + "="*50)
        print("新生成的函数内容：")
        print(function_code.strip())
        print("="*50 + "\n")

        # 写入文件
        with open(self.target_file, 'a', encoding='utf-8') as f:
            f.write("\n" + function_code + "\n")