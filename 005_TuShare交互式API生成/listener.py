"""
鼠标事件监听模块，提供全局双击回调。
版本: 1.1.0
新增：支持Ctrl+双击退出回调。
可直接运行测试：python listener.py
"""
import threading
import time
import sys
from pynput import mouse, keyboard

class DoubleClickListener:
    """全局双击监听器，运行在独立线程。
    同时监听鼠标和键盘，支持普通双击回调，以及按住Ctrl时的双击退出回调。
    """
    def __init__(self, on_double_click_callback, on_ctrl_double_click_callback=None):
        self.on_double_click_callback = on_double_click_callback
        self.on_ctrl_double_click_callback = on_ctrl_double_click_callback
        self.last_click_time = 0
        self.double_click_interval = 0.3  # 300毫秒内算双击
        self.ctrl_pressed = False
        self.mouse_listener = None
        self.keyboard_listener = None

    def start(self):
        """启动监听线程（非阻塞）。"""
        # 启动键盘监听线程
        self.keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.keyboard_listener.daemon = True
        self.keyboard_listener.start()

        # 启动鼠标监听线程
        self.mouse_listener = mouse.Listener(on_click=self._on_click)
        self.mouse_listener.daemon = True
        self.mouse_listener.start()

    def _on_key_press(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.ctrl_pressed = True
        except AttributeError:
            pass

    def _on_key_release(self, key):
        try:
            if key in [keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                self.ctrl_pressed = False
        except AttributeError:
            pass

    def _on_click(self, x, y, button, pressed):
        if button == mouse.Button.left and pressed:
            current_time = time.time()
            if current_time - self.last_click_time < self.double_click_interval:
                # 检测到双击
                if self.ctrl_pressed and self.on_ctrl_double_click_callback:
                    self.on_ctrl_double_click_callback()
                else:
                    self.on_double_click_callback()
            self.last_click_time = current_time

def test_callback():
    """测试回调函数，在终端打印信息。"""
    print("检测到普通双击！")

def test_exit_callback():
    """测试退出回调，退出程序。"""
    print("检测到Ctrl+双击，程序退出。")
    sys.exit(0)

if __name__ == "__main__":
    print("双击监听器测试程序已启动，请在任意位置双击鼠标左键。")
    print("按住Ctrl键并快速双击左键可退出程序。")
    listener = DoubleClickListener(test_callback, test_exit_callback)
    listener.start()
    try:
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n程序已退出。")