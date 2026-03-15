import os
import time
import logging
import webbrowser
import pytesseract
# 设置 tesseract 可执行文件路径
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from datetime import datetime

import cv2
import numpy as np
import pyautogui
import pytesseract
import uiautomation as auto
from PIL import Image, ImageGrab

# ==================== 配置日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('uiautomation_test.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 若Tesseract未加入系统PATH，请取消下一行注释并设置正确路径
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# ==================== 辅助函数 ====================
def get_browser_window():
    """
    启动默认浏览器并打开目标网页，返回浏览器窗口对象和客户区坐标。
    """
    url = "https://tushare.pro/webclient/"
    logger.info(f"正在打开URL: {url}")
    webbrowser.open(url)
    time.sleep(5) # 等待浏览器启动

    # 尝试通过窗口标题查找包含 'Tushare' 的窗口
    target_title = "Tushare"
    browser_window = None
    for _ in range(10): # 最多尝试10次
        windows = auto.GetRootControl().GetChildren()
        for w in windows:
            if w.Name and target_title.lower() in w.Name.lower():
                browser_window = w
                logger.info(f"找到浏览器窗口: {w.Name}")
                break
        if browser_window:
            break
        time.sleep(1)

    if not browser_window:
        # 若未找到，则使用当前活动窗口（需确保浏览器已激活）
        browser_window = auto.GetForegroundControl()
        logger.warning(f"未找到目标窗口，使用当前活动窗口: {browser_window.Name}")

    # 获取窗口边界
    rect = browser_window.BoundingRectangle
    logger.info(f"窗口边界: {rect}")

    # 估算客户区：简单去掉标题栏和地址栏（根据实际情况调整偏移量）
    # 更精确的方法可通过查找内部Pane控件，此处简化处理
    client_rect = (rect.left, rect.top + 80, rect.right, rect.bottom)
    return browser_window, client_rect

def capture_client_area(client_rect):
    """
    截取客户区图像。
    client_rect: (left, top, right, bottom)
    """
    screenshot = ImageGrab.grab(bbox=client_rect)
    return screenshot

def ocr_image(image):
    """
    对图像进行OCR，返回文字列表，每个元素为 (文本, (x, y, w, h))。
    """
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    # 二值化预处理（可根据实际图像调整阈值）
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    data = pytesseract.image_to_data(binary, lang='chi_sim+eng', output_type=pytesseract.Output.DICT)
    texts = []
    for i in range(len(data['text'])):
        conf = int(data['conf'][i])
        if conf > 60 and data['text'][i].strip():
            x = data['left'][i]
            y = data['top'][i]
            w = data['width'][i]
            h = data['height'][i]
            text = data['text'][i].strip()
            texts.append((text, (x, y, w, h)))
    return texts

def detect_boxes(image):
    """
    检测图像中的方框，返回每个方框的 (x, y, w, h, box_type)。
    box_type: 'plus', 'minus', 'check', 'solid', 'empty' 等。
    """
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for cnt in contours:
        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            x, y, w, h = cv2.boundingRect(cnt)
            if w < 10 or h < 10: # 过滤过小矩形
                continue
            aspect_ratio = w / h
            if 0.5 < aspect_ratio < 2.0: # 近似正方形
                roi = gray[y:y+h, x:x+w]
                box_type = classify_box(roi)
                boxes.append((x, y, w, h, box_type))
    return boxes

def classify_box(roi):
    """
    根据ROI灰度图判断方框类型。
    """
    _, thresh = cv2.threshold(roi, 200, 255, cv2.THRESH_BINARY_INV)
    total_pixels = roi.shape[0] * roi.shape[1]
    black_pixels = cv2.countNonZero(thresh)
    black_ratio = black_pixels / total_pixels

    # 高黑像素比可能是实心或包含线条
    if black_ratio > 0.8:
        # 检测直线
        lines = cv2.HoughLinesP(thresh, 1, np.pi/180, threshold=30, minLineLength=5, maxLineGap=3)
        if lines is not None:
            h_lines = 0
            v_lines = 0
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                if angle < 30 or angle > 150:
                    h_lines += 1
                elif 60 < angle < 120:
                    v_lines += 1
            if h_lines > 0 and v_lines > 0:
                return "plus" # 加号
            elif h_lines > 0:
                return "minus" # 减号
            else:
                return "solid" # 实心（无直线）
        else:
            return "solid"
    else:
        # 低黑像素比，可能是空心或勾号
        # 简单检测：若存在轮廓则视为勾号（需优化）
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 10:
                return "check" # 勾号
        return "empty" # 空心

def associate_text_with_boxes(texts, boxes, image_width, image_height):
    """
    将文字与方框关联，分为左侧节点和右侧字段。
    返回 (left_nodes, right_fields)
    每个节点/字段为字典: {'box': (x,y,w,h), 'box_type': str, 'text': str, 'text_box': (x,y,w,h)}
    """
    left_region_x = image_width // 3
    right_region_x = 2 * image_width // 3

    left_nodes = []
    right_fields = []

    for (x, y, w, h, box_type) in boxes:
        if x < left_region_x: # 左侧方框
            best_text = None
            best_dist = float('inf')
            best_text_box = None
            for (text, (tx, ty, tw, th)) in texts:
                # 垂直对齐判断
                if abs((ty + th/2) - (y + h/2)) < h:
                    dist = tx - (x + w) # 文字左边缘到方框右边缘距离
                    if 0 < dist < best_dist:
                        best_dist = dist
                        best_text = text
                        best_text_box = (tx, ty, tw, th)
            left_nodes.append({
                'box': (x, y, w, h),
                'box_type': box_type,
                'text': best_text,
                'text_box': best_text_box
            })
        elif x > right_region_x: # 右侧方框
            best_text = None
            best_dist = float('inf')
            best_text_box = None
            for (text, (tx, ty, tw, th)) in texts:
                if abs((ty + th/2) - (y + h/2)) < h:
                    dist = tx - (x + w)
                    if 0 < dist < best_dist:
                        best_dist = dist
                        best_text = text
                        best_text_box = (tx, ty, tw, th)
            right_fields.append({
                'box': (x, y, w, h),
                'box_type': box_type,
                'text': best_text,
                'text_box': best_text_box
            })
    return left_nodes, right_fields

def click_at_screen(client_rect, x, y):
    """
    将客户区坐标(x,y)转换为屏幕坐标并模拟鼠标点击。
    """
    screen_x = client_rect[0] + x
    screen_y = client_rect[1] + y
    logger.info(f"点击屏幕坐标: ({screen_x}, {screen_y})")
    pyautogui.click(screen_x, screen_y)

def save_detected_elements(left_nodes, right_fields):
    """
    将识别出的元素信息保存到文件。
    """
    with open('detected_elements.txt', 'w', encoding='utf-8') as f:
        f.write("左侧节点:\n")
        for node in left_nodes:
            f.write(f"文本: {node['text']}, 方框类型: {node['box_type']}, 方框坐标: {node['box']}\n")
        f.write("\n右侧字段:\n")
        for field in right_fields:
            f.write(f"文本: {field['text']}, 方框类型: {field['box_type']}, 方框坐标: {field['box']}\n")

# ==================== 主程序 ====================
def main():
    logger.info("=== 开始测试程序 ===")

    # 1. 启动浏览器并获取窗口
    browser_window, client_rect = get_browser_window()
    if not browser_window:
        logger.error("无法获取浏览器窗口")
        return

    # 2. 截取初始客户区图像
    logger.info("截取客户区图像")
    screenshot = capture_client_area(client_rect)
    screenshot.save("screenshot_initial.png")
    img = np.array(screenshot)

    # 3. OCR识别文字
    logger.info("开始OCR识别文字")
    texts = ocr_image(screenshot)
    logger.info(f"识别到 {len(texts)} 个文本块")
    for text, (x, y, w, h) in texts:
        logger.debug(f"文本: '{text}' 位置 ({x},{y},{w},{h})")

    # 4. 检测方框
    logger.info("检测方框")
    boxes = detect_boxes(screenshot)
    logger.info(f"检测到 {len(boxes)} 个方框")
    for x, y, w, h, box_type in boxes:
        logger.debug(f"方框: ({x},{y},{w},{h}) 类型: {box_type}")

    # 5. 关联文字和方框
    left_nodes, right_fields = associate_text_with_boxes(
        texts, boxes, screenshot.width, screenshot.height
    )
    logger.info(f"左侧节点数: {len(left_nodes)}")
    logger.info(f"右侧字段数: {len(right_fields)}")

    # 保存初步识别结果
    save_detected_elements(left_nodes, right_fields)

    # 6. 循环点击左侧所有带加号的方框，直至无加号
    max_iterations = 10
    iteration = 0
    while iteration < max_iterations:
        logger.info(f"开始第 {iteration+1} 轮加号点击")
        # 重新截图分析
        screenshot = capture_client_area(client_rect)
        texts = ocr_image(screenshot)
        boxes = detect_boxes(screenshot)
        left_nodes, right_fields = associate_text_with_boxes(
            texts, boxes, screenshot.width, screenshot.height
        )
        plus_boxes = [node for node in left_nodes if node['box_type'] == 'plus']
        if not plus_boxes:
            logger.info("没有检测到加号方框，结束循环")
            break
        logger.info(f"本轮检测到 {len(plus_boxes)} 个加号方框")
        # 按从上到下排序
        plus_boxes.sort(key=lambda node: node['box'][1])
        for node in plus_boxes:
            box = node['box']
            x, y, w, h = box
            click_x = x + w // 2
            click_y = y + h // 2
            logger.info(f"点击加号方框: 文本='{node['text']}', 坐标({click_x},{click_y})")
            click_at_screen(client_rect, click_x, click_y)
            time.sleep(1) # 等待页面响应
        iteration += 1
        time.sleep(2) # 等待展开完成

    # 7. 点击一个左侧无方框的文本（叶子节点），以触发右侧字段更新
    # 获取所有左侧文本中未被关联到方框的文本
    all_texts = texts
    left_texts_without_box = []
    for text, (tx, ty, tw, th) in all_texts:
        if tx < screenshot.width // 3: # 位于左侧区域
            associated = False
            for node in left_nodes:
                if node['text'] == text:
                    associated = True
                    break
            if not associated:
                left_texts_without_box.append((text, (tx, ty, tw, th)))
    if left_texts_without_box:
        text, (tx, ty, tw, th) = left_texts_without_box[0]
        logger.info(f"点击左侧无方框文本: '{text}' 位置 ({tx},{ty})")
        click_x = tx + tw // 2
        click_y = ty + th // 2
        click_at_screen(client_rect, click_x, click_y)
        time.sleep(2) # 等待右侧更新
    else:
        logger.warning("未找到左侧无方框文本，跳过此步")

    # 8. 重新截图，识别右侧字段及“字段”标题左侧方框形态
    screenshot = capture_client_area(client_rect)
    texts = ocr_image(screenshot)
    boxes = detect_boxes(screenshot)
    left_nodes, right_fields = associate_text_with_boxes(
        texts, boxes, screenshot.width, screenshot.height
    )

    # 查找“字段”文本
    field_text = None
    for text, (tx, ty, tw, th) in texts:
        if "字段" in text:
            field_text = (text, (tx, ty, tw, th))
            break
    if field_text:
        text, (tx, ty, tw, th) = field_text
        logger.info(f"找到'字段'文本，位置 ({tx},{ty})")
        # 查找字段左侧的方框
        field_box = None
        for x, y, w, h, box_type in boxes:
            if x + w < tx and abs((y + h/2) - (ty + th/2)) < h:
                field_box = (x, y, w, h, box_type)
                break
        if field_box:
            x, y, w, h, box_type = field_box
            logger.info(f"字段左侧方框类型: {box_type}, 坐标 ({x},{y},{w},{h})")
            # 记录下方所有字段的复选框状态
            for field in right_fields:
                if field['box'][1] > ty + th: # 位于“字段”下方
                    logger.info(f"字段 '{field['text']}' 方框类型: {field['box_type']}")
        else:
            logger.warning("未找到字段左侧方框")
    else:
        logger.warning("未找到'字段'文本")

    # 最终保存所有识别结果
    save_detected_elements(left_nodes, right_fields)
    logger.info("=== 测试程序结束 ===")

if __name__ == "__main__":
    main()