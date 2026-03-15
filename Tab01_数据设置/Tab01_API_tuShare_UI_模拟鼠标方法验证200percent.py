"""
浏览器自动化与特征识别程序（完整版）
功能：
1. 启动系统默认浏览器并打开指定网页（tushare）
2. 将网页缩放至200%
3. 识别网页中的方框（加号、减号、打勾、空心、实心）及其坐标
4. 识别“字段”字符串左侧方框的三种形态
5. 依次点击所有带加号的方框
6. 通过鼠标双击/三击切换控制权或退出程序
7. 从剪贴板读取数据并生成tushare API函数文件
8. 详细日志记录（终端+文件）

环境要求：
- Python 3.7+
- 安装依赖：pip install pyautogui opencv-python numpy pytesseract pyperclip pynput pillow
- 安装 Tesseract OCR：https://github.com/UB-Mannheim/tesseract/wiki
  安装时务必选择中文语言包（chi_sim）
"""

import pyautogui
import cv2
import numpy as np
import pytesseract
import pyperclip
import logging
import webbrowser
import time
import os
import sys
from pynput import mouse

# ==================== 配置区域（请根据实际情况修改）====================
# 如果Tesseract未添加到系统PATH，请在此指定完整路径（取消注释并修改）
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('automation.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
# ====================================================================

class BrowserAutomation:
    def __init__(self):
        self.running = False          # 自动化是否运行
        self.listener = None           # 鼠标监听器
        self.last_click_time = 0       # 上次点击时间（用于双击检测）
        self.double_click_count = 0    # 双击计数（用于三击检测）
        self.screen_width, self.screen_height = pyautogui.size()  # 屏幕尺寸
        self.ocr_lang = 'chi_sim'       # OCR语言（简体中文）

    def check_tesseract(self):
        """验证Tesseract是否可用，若不可用则退出程序"""
        try:
            # 尝试获取版本信息
            version = pytesseract.get_tesseract_version()
            logging.info(f"Tesseract OCR 版本: {version}")
            return True
        except Exception as e:
            logging.error("Tesseract OCR 未找到！请执行以下操作：")
            logging.error("1. 从 https://github.com/UB-Mannheim/tesseract/wiki 下载安装")
            logging.error("2. 安装时勾选中文语言包")
            logging.error("3. 安装后，将 Tesseract 路径添加到系统 PATH，")
            logging.error("   或在代码顶部取消注释并设置 pytesseract.pytesseract.tesseract_cmd")
            logging.error(f"详细错误: {e}")
            return False

    def start_listener(self):
        """启动鼠标监听器，检测双击/三击"""
        with mouse.Listener(on_click=self.on_click) as listener:
            self.listener = listener
            logging.info("鼠标监听已启动，请双击左键开始自动化，三击退出程序。")
            listener.join()

    def on_click(self, x, y, button, pressed):
        """鼠标点击事件回调"""
        if not pressed or button != mouse.Button.left:
            return

        current_time = time.time()
        # 双击检测（两次点击间隔<0.3秒）
        if current_time - self.last_click_time < 0.3:
            self.double_click_count += 1
            if self.double_click_count >= 2:  # 两次双击即为三击
                logging.info("检测到鼠标三击，程序终止。")
                return False  # 停止监听
            else:
                logging.info("检测到鼠标双击，切换控制权。")
                self.toggle_control()
        else:
            self.double_click_count = 0

        self.last_click_time = current_time

    def toggle_control(self):
        """切换自动化运行状态"""
        self.running = not self.running
        status = "启动" if self.running else "暂停"
        logging.info(f"自动化状态已切换为：{status}")

    def launch_browser(self, url):
        """启动系统默认浏览器并打开指定URL"""
        try:
            webbrowser.open(url)
            logging.info(f"已启动默认浏览器，打开网址：{url}")
            time.sleep(5)  # 等待浏览器加载

            # 缩放网页至200%（Ctrl + '+' 两次）
            pyautogui.hotkey('ctrl', '+')
            time.sleep(0.5)
            pyautogui.hotkey('ctrl', '+')
            logging.info("已将网页缩放比例调整为200%")

            # 激活浏览器窗口（点击屏幕左上角）
            pyautogui.click(100, 100)
            time.sleep(1)
            return True
        except Exception as e:
            logging.error(f"启动浏览器失败：{str(e)}")
            return False

    def capture_and_ocr(self, region=None):
        """
        截图并返回OpenCV图像和OCR文本
        :param region: (left, top, width, height) 截图区域，None为全屏
        :return: (img_bgr, text)
        """
        try:
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()

            # 转换为OpenCV BGR格式
            img_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

            # 图像预处理：灰度化、二值化（提高OCR准确率）
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

            # OCR识别
            text = pytesseract.image_to_string(binary, lang=self.ocr_lang)
            return img_bgr, text
        except Exception as e:
            logging.error(f"截图或OCR失败：{str(e)}")
            return None, ""

    def identify_square_type(self, roi_gray, ocr_text):
        """
        识别方框类型：加号/减号/打勾/空心/实心
        :param roi_gray: 灰度图像（方框区域）
        :param ocr_text: OCR识别出的文本
        :return: 类型字符串
        """
        # 优先根据OCR文本判断
        text = ocr_text.strip()
        if '+' in text or '＋' in text:
            return 'plus'
        if '-' in text or '－' in text:
            return 'minus'
        if '√' in text or '✓' in text or '勾' in text:
            return 'checked'

        # 如果OCR无结果，通过像素分析判断是否为实心
        if roi_gray.size == 0:
            return 'unknown'
        # 将图像缩放到统一大小以便比较
        resized = cv2.resize(roi_gray, (20, 20))
        # 统计暗像素（<128）的比例
        dark_ratio = np.sum(resized < 128) / resized.size
        if dark_ratio > 0.6:
            return 'solid'
        else:
            return 'empty'

    def detect_squares_and_text(self):
        """
        识别网页中的所有方框及其类型，并记录坐标
        :return: 元素列表，每个元素为字典：{'type':'square','subtype':..., 'x':, 'y':, 'w':, 'h':, 'text':}
        """
        # 全屏截图
        screenshot = pyautogui.screenshot()
        img_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # 二值化，寻找轮廓
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        elements = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 100:  # 忽略太小的轮廓
                continue

            x, y, w, h = cv2.boundingRect(contour)

            # 判断是否为近似正方形（方框）
            if 0.8 < w / h < 1.2 and 20 < w < 100:
                # 提取方框区域进行OCR
                roi = gray[y:y+h, x:x+w]
                # 放大区域以提高OCR小符号的准确率
                roi_big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
                roi_text = pytesseract.image_to_string(roi_big, config='--psm 10')  # 单字符模式

                # 识别类型
                square_type = self.identify_square_type(roi, roi_text)

                elements.append({
                    'type': 'square',
                    'subtype': square_type,
                    'x': x,
                    'y': y,
                    'w': w,
                    'h': h,
                    'text': roi_text.strip()
                })
                logging.info(f"识别到方框：类型={square_type}，坐标=({x},{y})，文字='{roi_text.strip()}'")

        return elements

    def detect_field_checkbox(self):
        """
        检测“字段”字符串及其左侧方框的形态（条件触发：需先点击左侧区域）
        :return: 字段坐标和方框形态，若未找到返回None
        """
        # 由于字段左侧方框需在点击左侧后才出现，我们先模拟点击左侧区域（特征3描述）
        left_click_x = self.screen_width // 4
        left_click_y = self.screen_height // 2
        pyautogui.click(left_click_x, left_click_y)
        logging.info(f"已点击左侧区域 ({left_click_x}, {left_click_y})，等待字段出现...")
        time.sleep(2)

        # 截取网页右侧区域（字段通常位于右侧）
        right_region = (self.screen_width // 2, 0, self.screen_width // 2, self.screen_height)
        img, text = self.capture_and_ocr(right_region)
        if img is None:
            return None

        # 使用pytesseract获取文字详细位置
        try:
            data = pytesseract.image_to_data(img, lang=self.ocr_lang, output_type=pytesseract.Output.DICT)
            for i, word in enumerate(data['text']):
                if '字段' in word:
                    left = data['left'][i]
                    top = data['top'][i]
                    width = data['width'][i]
                    height = data['height'][i]

                    # 字段左侧方框的大致区域（假设在文字左侧30-100像素，垂直对齐）
                    checkbox_left = left - 100
                    checkbox_top = top - 10
                    checkbox_width = 80
                    checkbox_height = height + 20

                    # 确保不越界
                    checkbox_left = max(0, checkbox_left)
                    checkbox_top = max(0, checkbox_top)

                    # 截图方框区域
                    checkbox_region = (checkbox_left, checkbox_top, checkbox_width, checkbox_height)
                    cb_img, cb_text = self.capture_and_ocr(checkbox_region)

                    if cb_img is not None:
                        # 判断方框形态（简化：通过OCR结果和像素分析）
                        gray_cb = cv2.cvtColor(cb_img, cv2.COLOR_BGR2GRAY)
                        # 先尝试OCR方框内字符
                        cb_text = pytesseract.image_to_string(gray_cb, config='--psm 10')
                        if '√' in cb_text or '勾' in cb_text:
                            shape = 'checked'
                        elif '■' in cb_text or '█' in cb_text or self.is_solid_checkbox(gray_cb):
                            shape = 'solid'
                        else:
                            shape = 'empty'

                        logging.info(f"检测到'字段'字符串，坐标({left+self.screen_width//2},{top})，左侧方框形态：{shape}")
                        return left + self.screen_width // 2, top, shape
        except Exception as e:
            logging.error(f"检测字段方框时出错：{str(e)}")
        return None

    def is_solid_checkbox(self, gray_img):
        """判断方框是否为实心（通过像素密度）"""
        if gray_img.size == 0:
            return False
        # 二值化
        _, binary = cv2.threshold(gray_img, 128, 255, cv2.THRESH_BINARY)
        # 计算黑色像素比例（实心框内大部分为黑色）
        black_ratio = np.sum(binary < 128) / binary.size
        return black_ratio > 0.4  # 阈值可调

    def read_clipboard_and_generate(self):
        """从剪贴板读取数据并生成tushare API函数文件"""
        try:
            clipboard_data = pyperclip.paste()
            if not clipboard_data.strip():
                logging.warning("剪贴板为空，无法生成代码。")
                return False

            logging.info(f"从剪贴板读取到数据（前200字符）：{clipboard_data[:200]}...")

            # 简单解析：假设剪贴板内容为逗号分隔的API名称列表
            lines = clipboard_data.strip().split('\n')
            api_names = []
            for line in lines:
                parts = line.strip().split(',')
                for part in parts:
                    name = part.strip()
                    if name and name.isidentifier():
                        api_names.append(name)

            if not api_names:
                logging.warning("未解析到有效的API名称。")
                return False

            # 生成Python文件
            output_file = 'tushare_api.py'
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write("# -*- coding: utf-8 -*-\n")
                f.write("# Generated by Browser Automation Tool\n")
                f.write("import tushare as ts\n\n")
                f.write("def init_pro():\n")
                f.write("    # 请在此处设置您的token\n")
                f.write("    ts.set_token('YOUR_TOKEN_HERE')\n")
                f.write("    pro = ts.pro_api()\n")
                f.write("    return pro\n\n")

                for api in api_names:
                    f.write(f"def get_{api}():\n")
                    f.write(f"    \"\"\"获取{api}数据\"\"\"\n")
                    f.write(f"    pro = init_pro()\n")
                    f.write(f"    # TODO: 根据实际参数调整\n")
                    f.write(f"    df = pro.{api}()\n")
                    f.write(f"    return df\n\n")

            logging.info(f"已成功生成API文件：{output_file}")
            return True
        except Exception as e:
            logging.error(f"生成代码失败：{str(e)}")
            return False

    def run_automation(self):
        """主自动化流程"""
        # 1. 启动浏览器
        url = "https://tushare.pro/webclient/"
        if not self.launch_browser(url):
            logging.error("浏览器启动失败，终止自动化。")
            return

        # 2. 等待用户双击启动自动化
        logging.info("请双击鼠标左键开始自动化流程...")
        while not self.running:
            time.sleep(0.1)

        # 3. 识别并点击所有加号方框
        logging.info("开始识别网页中的方框...")
        elements = self.detect_squares_and_text()
        plus_clicked = 0
        for elem in elements:
            if elem['type'] == 'square' and elem['subtype'] == 'plus':
                click_x = elem['x'] + elem['w'] // 2
                click_y = elem['y'] + elem['h'] // 2
                pyautogui.click(click_x, click_y)
                logging.info(f"点击加号方框，坐标=({click_x},{click_y})")
                plus_clicked += 1
                time.sleep(0.5)  # 等待展开动画

        if plus_clicked == 0:
            logging.info("未检测到加号方框。")
        else:
            logging.info(f"共点击 {plus_clicked} 个加号方框。")

        # 4. 检测字段方框形态
        field_info = self.detect_field_checkbox()
        if field_info:
            x, y, shape = field_info
            logging.info(f"字段左侧方框形态识别完成：{shape}，坐标({x},{y})")
        else:
            logging.info("未检测到'字段'字符串或其左侧方框。")

        # 5. 提示用户下一步操作
        logging.info("自动化第一阶段完成。您可以通过双击暂停/继续，或三击退出。")

        # 6. 等待用户通过双击控制剪贴板读取
        logging.info("当您准备好从剪贴板生成代码时，请双击继续...")
        # 暂停状态等待用户双击
        self.running = False
        while not self.running:
            time.sleep(0.1)

        # 7. 读取剪贴板并生成代码
        self.read_clipboard_and_generate()

        logging.info("所有任务完成，程序将继续监听鼠标事件。三击可退出。")

if __name__ == "__main__":
    # 设置DPI感知，解决Windows缩放问题
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    # 创建自动化实例
    bot = BrowserAutomation()

    # 首先检查Tesseract是否可用
    if not bot.check_tesseract():
        input("按回车键退出...")
        sys.exit(1)

    # 启动鼠标监听（阻塞，直到三击退出）
    bot.start_listener()