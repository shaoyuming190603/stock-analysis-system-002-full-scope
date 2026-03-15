import pyperclip
import re
import json
import os
import sys
import threading
from pynput import mouse

# 项目文件夹路径
PROJECT_DIR = r'C:\01_My_documents\01_pythonLearn\我的PNP_MCSD大项目\Tab01_数据设置'

# 文件名定义（绝对路径）
API_FILE = os.path.join(PROJECT_DIR, 'Tab01_TuShareAPI_RawListCreation.py')
LOG_FILE = os.path.join(PROJECT_DIR, 'Tab01_TuShareAPI_log.json')

# 全局变量
counter = 0
click_times = []
lock = threading.Lock()
log_list = []

# 日志加载
def load_log():
    global counter, log_list
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log_list = data.get('log_list', [])
            counter = len(log_list)
    else:
        log_list = []
        counter = 0

# 日志保存
def save_log():
    log_data = {
        'log_list': log_list
    }
    with open(LOG_FILE, 'w', encoding='utf-8') as log_file:
        json.dump(log_data, log_file, ensure_ascii=False, indent=2)

# 处理剪贴板数据
def process_data(data):
    global counter, log_list
    # 提取API名称
    match = re.search(r'df\s*=\s*pro\.([a-zA-Z_]+)\s*\(', data)
    if match:
        api_name = match.group(1)
    else:
        print("未找到API名称")
        return

    counter += 1

    # 替换API密钥
    data = re.sub(r"pro\s*=\s*ts\.pro_api\('.*?'\)", "pro = ts.pro_api('tushare_api')", data)

    # 包装成函数
    indent_data = '\n    '.join(data.splitlines())
    func_str = f"\ndef {api_name}_api():\n    {indent_data}\n"

    # 写入API文件
    with open(API_FILE, 'a', encoding='utf-8') as f:
        f.write('\n\n')
        f.write(func_str)

    # 日志追加
    log_list.append({'序号': counter, '函数名称': f'{api_name}_api'})
    save_log()

    print(f"已成功写入 {counter} 个 API接口函数，新增函数：\n{func_str}\n可以继续操作。")

# 处理剪贴板
def handle_clipboard():
    data = pyperclip.paste()
    if not data.strip():
        print("剪贴板无数据，重新复制数据。")
        return
    print(f"已读取剪贴板数据：{data}")
    process_data(data)
    pyperclip.copy('')  # 清空剪贴板

# 保存并退出
def save_and_exit():
    save_log()
    print(f"{API_FILE} 和日志文件已保存，即将退出程序。")
    sys.exit(0)

# 鼠标事件处理
def on_click(x, y, button, pressed):
    if not pressed:
        return
    with lock:
        import time
        now = time.time()
        click_times.append(now)
        # 保留最近3次点击
        if len(click_times) > 3:
            click_times.pop(0)
        # 判断双击
        if len(click_times) >= 2 and (click_times[-1] - click_times[-2]) < 0.5:
            print("监测到鼠标双击")
            handle_clipboard()
        # 判断三击
        if len(click_times) == 3 and (click_times[-1] - click_times[-3]) < 0.8:
            save_and_exit()

# 剪贴板监控线程
def clipboard_monitor():
    import time
    last_data = ''
    while True:
        data = pyperclip.paste()
        if data.strip() and data != last_data:
            handle_clipboard()
            last_data = ''
        else:
            last_data = data
        time.sleep(0.5)

def main():
    # 确保项目文件夹存在
    if not os.path.exists(PROJECT_DIR):
        os.makedirs(PROJECT_DIR)
    load_log()
    print("程序启动，等待鼠标操作...")
    # 启动剪贴板监控线程
    t = threading.Thread(target=clipboard_monitor, daemon=True)
    t.start()
    # 启动鼠标监听
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()

if __name__ == '__main__':
    main()