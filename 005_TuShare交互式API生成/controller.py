"""
主控制器，协调用户与程序的交替操作。
版本: 1.3.0
用户手动点击生成代码和复制按钮，双击后程序读取剪贴板生成函数。
"""
import time
import logging
import subprocess
import socket
from listener import DoubleClickListener
from browser_controller import BrowserController
from code_writer import CodeWriter

class WorkflowController:
    """控制整个工作流。"""
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.browser = BrowserController()
        self.writer = CodeWriter()
        self.listener = DoubleClickListener(
            on_double_click_callback=self.on_user_double_click,
            on_ctrl_double_click_callback=self.on_exit
        )
        self.user_turn = True   # 始终为用户操作阶段，双击仅触发程序动作
        self.running = True

    def start(self):
        """启动程序：启动调试模式的 Chrome，激活标签，开始监听双击。"""
        try:
            # 1. 启动 Chrome 调试实例
            self.logger.info("正在启动 Chrome 调试模式...")
            chrome_cmd = [
                "powershell",
                "-Command",
                '& "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --% --remote-debugging-port=9222 --user-data-dir="D:\\chrome-debug-profile" --remote-allow-origins=*'
            ]
            process = subprocess.Popen(chrome_cmd, shell=False)
            self.logger.info(f"Chrome 启动命令已执行，PID: {process.pid}")

            # 2. 等待远程调试端口可用
            if not self._wait_for_port(9222, timeout=30):
                self.logger.error("Chrome 远程调试端口 9222 未在 30 秒内就绪，程序退出。")
                return

            # 3. 连接到 Chrome 调试实例
            self.logger.info("正在连接到 Chrome 调试实例...")
            if not self.browser.connect_to_existing_browser(port=9222):
                self.logger.error("连接 Chrome 调试实例失败，程序退出。")
                return

            # 4. 激活目标标签页（如果未打开则新建）
            self.browser.activate_tab()

            # 5. 启动双击监听
            self.listener.start()
            self.logger.info("程序已启动，请在打开的浏览器中手动操作：")
            self.logger.info("1. 点击“生成代码”按钮，然后在弹出的窗口中点击“复制”按钮。")
            self.logger.info("2. 完成后，快速双击鼠标左键，程序将读取剪贴板生成函数。")
            self.logger.info("按住 Ctrl 键并快速双击鼠标可退出程序。")

            # 6. 主循环
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("用户中断程序。")
        except Exception as e:
            self.logger.exception("启动过程中发生异常: %s", e)
        finally:
            self.browser.close()
            self.logger.info("程序已退出。")

    def _wait_for_port(self, port, timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(1)
        return False

    def on_user_double_click(self):
        """用户双击回调：读取剪贴板并生成函数，无需控制浏览器点击。"""
        self.logger.info("检测到双击，程序开始工作...")
        try:
            # 读取剪贴板
            code = self.writer.read_clipboard_code()
            if code:
                api_name = self.writer.parse_function_name(code)
                if api_name:
                    func_code = self.writer.generate_function_code(api_name, code)
                    self.writer.append_function(func_code)
                    self.logger.info(f"函数 fetch_{api_name} 已追加到文件。")
                else:
                    self.logger.error("无法解析 API 名称。")
            else:
                self.logger.error("剪贴板为空。")
        except Exception as e:
            self.logger.exception("程序执行出错：%s", e)
        finally:
            self.logger.info("程序完成，请用户继续操作。")

    def on_exit(self):
        self.logger.info("收到退出信号，正在关闭程序...")
        self.running = False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    controller = WorkflowController()
    controller.start()