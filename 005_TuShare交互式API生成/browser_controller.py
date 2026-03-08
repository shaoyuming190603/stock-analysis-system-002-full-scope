"""
浏览器控制模块，封装 Selenium 操作。
版本: 1.3.0
简化：仅用于连接调试浏览器和激活标签页，不再自动点击。
"""
from selenium import webdriver
import logging

class BrowserController:
    def __init__(self, url="https://tushare.pro/webclient/"):
        self.url = url
        self.driver = None
        self.logger = logging.getLogger(__name__)

    def connect_to_existing_browser(self, port=9222):
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
            self.driver = webdriver.Chrome(options=options)
            self.logger.info("已连接到现有 Chrome 实例。")
            return True
        except Exception as e:
            self.logger.error(f"连接 Chrome 调试实例失败：{e}")
            return False

    def activate_tab(self):
        if not self.driver:
            self.logger.error("浏览器未连接，无法激活标签页。")
            return False
        try:
            handles = self.driver.window_handles
            for handle in handles:
                self.driver.switch_to.window(handle)
                if self.url in self.driver.current_url:
                    self.logger.info(f"已激活标签页：{self.driver.current_url}")
                    return True
            # 未找到则新建标签页
            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.driver.get(self.url)
            self.logger.info("新建标签页并打开目标网址。")
            return True
        except Exception as e:
            self.logger.error(f"激活标签页失败：{e}")
            return False

    def close(self):
        if self.driver:
            self.driver.quit()
            self.logger.info("浏览器驱动已关闭。")