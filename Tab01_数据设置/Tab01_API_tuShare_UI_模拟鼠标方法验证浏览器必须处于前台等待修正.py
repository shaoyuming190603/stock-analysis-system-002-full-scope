import os
import time
import logging
import webbrowser
import pytesseract
# 设置 tesseract 可执行文件路径 (请根据您的实际安装路径修改)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from datetime import datetime

import cv2
import numpy as np
import pyautogui
import uiautomation as auto
from PIL import Image, ImageGrab

# 尝试导入 win32gui，用于激活窗口
try:
    import win32gui
    HAS_WIN32GUI = True
except ImportError:
    HAS_WIN32GUI = False
    logging.warning("win32gui 未安装，窗口激活将使用 uiautomation.SetActive()，可能不够稳定。建议安装 pywin32。")

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

# ==================== 核心函数 ====================
def activate_window(window):
    """将指定窗口激活并置于前台"""
    if not window:
        return
    try:
        if HAS_WIN32GUI:
            handle = window.NativeWindowHandle
            win32gui.SetForegroundWindow(handle)
            logger.debug(f"已使用 win32gui 激活窗口，句柄: {handle}")
        else:
            window.SetActive()
            logger.debug("已使用 uiautomation.SetActive() 激活窗口")
        time.sleep(0.3)
    except Exception as e:
        logger.warning(f"激活窗口时出错: {e}")

def find_browser_window_efficiently():
    """
    高效查找浏览器窗口。
    改进点：缩短轮询间隔，优先匹配常见浏览器名称。
    """
    url = "https://tushare.pro/webclient/"
    logger.info(f"正在打开URL: {url}")
    webbrowser.open(url)
    logger.info("等待浏览器窗口出现...")

    max_wait = 20  # 缩短最大等待时间
    start_time = time.time()
    target_title = "Tushare"
    browser_window = None

    # 优先匹配的浏览器进程名称
    browser_keywords = ["Chrome", "Edge", "Firefox", "Opera", "Brave"]

    while time.time() - start_time < max_wait:
        windows = auto.GetRootControl().GetChildren()
        for w in windows:
            if w.Name and target_title in w.Name:
                # 进一步确认是浏览器窗口（通过名称包含常见浏览器关键字）
                if any(keyword in w.Name for keyword in browser_keywords):
                    browser_window = w
                    logger.info(f"找到浏览器窗口: {w.Name}")
                    break
        if browser_window:
            break
        # 缩短轮询间隔到0.2秒，提高响应速度
        time.sleep(0.2)

    if not browser_window:
        logger.warning(f"在 {max_wait} 秒内未自动找到目标窗口，请手动将浏览器窗口置于前台，然后按回车键继续...")
        input()
        browser_window = auto.GetForegroundControl()
        logger.info(f"已获取当前活动窗口: {browser_window.Name}")

    return browser_window

def locate_content_area_uia(browser_window):
    """
    使用UIAutomation尝试精确定位网页内容区域。
    返回 (success, content_rect) 元组。
    success为True时，content_rect是精确的 (left, top, right, bottom)。
    """
    logger.info("尝试使用UIAutomation定位内容区域...")
    content_pane = None
    # 扩大搜索范围，尝试更多可能的控件名称和类型
    pane_candidates = [
        {"Name": "网页内容", "ClassName": "Chrome_RenderWidgetHostHWND"},
        {"Name": "内容", "ClassName": "Chrome_RenderWidgetHostHWND"},
        {"Name": "Web Content", "ClassName": "Chrome_RenderWidgetHostHWND"},
        {"Name": "网页视图", "ClassName": "DirectUIHWND"},
        {"Name": "Pane", "ClassName": "Chrome_RenderWidgetHostHWND"},  # 通用名称
        {"ControlType": auto.ControlType.PaneControl},  # 按控件类型搜索
    ]

    # 从浏览器窗口开始深度搜索
    for cand in pane_candidates:
        try:
            if "ControlType" in cand:
                # 按控件类型搜索
                content_pane = browser_window.GetFirstChildControl(cand["ControlType"], searchDepth=5)
            else:
                # 按名称和类名搜索
                content_pane = browser_window.PaneControl(Name=cand["Name"], ClassName=cand["ClassName"], searchDepth=5)
            if content_pane and content_pane.Exists():
                logger.info(f"找到内容Pane: Name='{content_pane.Name}', ClassName='{content_pane.ClassName}'")
                rect = content_pane.BoundingRectangle
                return True, (rect.left, rect.top, rect.right, rect.bottom)
        except:
            continue

    logger.warning("UIAutomation未能定位到内容区域。")
    return False, None

def get_client_rect_fallback(browser_window):
    """
    回退方法：基于窗口坐标和固定偏移估算客户区。
    """
    rect = browser_window.BoundingRectangle
    # 估算客户区：去掉标题栏、地址栏、书签栏等。根据您的截图，顶部偏移可能需要更大。
    # 在您的截图中，从窗口顶部到左侧菜单顶部大约有150像素左右。
    estimated_top_offset = 150  # 根据您的实际界面调整此值
    client_rect = (rect.left, rect.top + estimated_top_offset, rect.right, rect.bottom)
    logger.info(f"使用回退方法估算客户区，顶部偏移: {estimated_top_offset}，结果: {client_rect}")
    return client_rect

def capture_client_area(client_rect):
    """截取客户区图像"""
    return ImageGrab.grab(bbox=client_rect)

def ocr_image(image):
    """OCR识别文字"""
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
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

def detect_box_for_text(text_box, gray_img):
    """
    在文本左侧区域检测是否存在方框，并判断是否为加号。
    (复用之前图像识别方法)
    """
    tx, ty, tw, th = text_box
    h = th
    search_left = max(0, tx - h - 10)
    search_top = ty
    search_right = tx
    search_bottom = ty + th
    if search_right - search_left < 10:
        return None, False

    roi = gray_img[search_top:search_bottom, search_left:search_right]
    if roi.size == 0:
        return None, False

    _, roi_bin = cv2.threshold(roi, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(roi_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidate_boxes = []
    for cnt in contours:
        x, y, w, h_box = cv2.boundingRect(cnt)
        if w < 8 or h_box < 8 or w > 30 or h_box > 30:
            continue
        aspect = w / h_box
        if 0.7 < aspect < 1.3:
            area = cv2.contourArea(cnt)
            if area / (w * h_box) > 0.3:
                candidate_boxes.append((x, y, w, h_box))

    if not candidate_boxes:
        return None, False

    candidate_boxes.sort(key=lambda b: b[0] + b[2], reverse=True)
    best = candidate_boxes[0]
    box_x = search_left + best[0]
    box_y = search_top + best[1]
    box_w, box_h = best[2], best[3]

    inner_roi = gray_img[box_y+2:box_y+box_h-2, box_x+2:box_x+box_w-2]
    if inner_roi.size == 0:
        return (box_x, box_y, box_w, box_h), False

    _, inner_bin = cv2.threshold(inner_roi, 200, 255, cv2.THRESH_BINARY_INV)
    lines = cv2.HoughLinesP(inner_bin, 1, np.pi/180, threshold=10, minLineLength=3, maxLineGap=2)
    has_horizontal = False
    has_vertical = False
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            if angle < 30 or angle > 150:
                has_horizontal = True
            elif 60 < angle < 120:
                has_vertical = True
    is_plus = has_horizontal and has_vertical
    return (box_x, box_y, box_w, box_h), is_plus

def associate_text_with_boxes(texts, gray_img, img_width):
    """关联文字与方框"""
    left_region_x = img_width // 3
    left_nodes = []
    for text, tb in texts:
        tx, ty, tw, th = tb
        if tx < left_region_x:
            box, is_plus = detect_box_for_text(tb, gray_img)
            left_nodes.append({
                'text': text,
                'text_box': tb,
                'box': box,
                'is_plus': is_plus
            })
    return left_nodes

def click_at_screen(client_rect, x, y, window=None):
    """点击屏幕坐标"""
    if window:
        activate_window(window)
    screen_x = client_rect[0] + x
    screen_y = client_rect[1] + y
    logger.info(f"点击屏幕坐标: ({screen_x}, {screen_y})")
    pyautogui.click(screen_x, screen_y)

def save_detected_elements(left_nodes):
    """保存识别结果"""
    with open('detected_elements.txt', 'w', encoding='utf-8') as f:
        f.write("左侧节点:\n")
        for node in left_nodes:
            box_info = f"方框坐标: {node['box']}, 是加号: {node['is_plus']}" if node['box'] else "无方框"
            f.write(f"文本: {node['text']}, {box_info}\n")

# ==================== 主程序 ====================
def main():
    logger.info("=== 开始测试程序 (混合模式) ===")

    # 1. 高效查找浏览器窗口
    browser_window = find_browser_window_efficiently()
    if not browser_window:
        logger.error("无法获取浏览器窗口")
        return
    activate_window(browser_window)
    time.sleep(1)

    # 2. 尝试使用UIAutomation定位内容区域
    success, content_rect = locate_content_area_uia(browser_window)
    if success:
        logger.info(f"使用UIAutomation精确定位内容区域: {content_rect}")
        client_rect = content_rect
    else:
        # 3. UIA失败，回退到基于固定偏移的方法
        logger.warning("回退到基于固定偏移的方法估算客户区")
        client_rect = get_client_rect_fallback(browser_window)

    logger.info(f"最终使用的客户区: {client_rect}")

    # 4. 截取图像并进行OCR和方框检测（复用您之前验证过的逻辑）
    logger.info("截取客户区图像")
    screenshot = capture_client_area(client_rect)
    screenshot.save("screenshot_debug.png")
    img = np.array(screenshot)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    logger.info("开始OCR识别文字")
    texts = ocr_image(screenshot)
    logger.info(f"识别到 {len(texts)} 个文本块")

    # 5. 关联文字和方框
    left_nodes = associate_text_with_boxes(texts, gray, screenshot.width)
    logger.info(f"左侧节点数: {len(left_nodes)}")
    save_detected_elements(left_nodes)

    # 6. 循环点击加号
    max_iterations = 10
    iteration = 0
    while iteration < max_iterations:
        logger.info(f"开始第 {iteration+1} 轮加号点击")
        # 重新截图分析
        screenshot = capture_client_area(client_rect)
        gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        texts = ocr_image(screenshot)
        left_nodes = associate_text_with_boxes(texts, gray, screenshot.width)

        plus_nodes = [node for node in left_nodes if node['box'] and node['is_plus']]
        if not plus_nodes:
            logger.info("没有检测到加号方框，结束循环")
            break

        logger.info(f"本轮检测到 {len(plus_nodes)} 个加号方框")
        plus_nodes.sort(key=lambda n: n['text_box'][1])
        for node in plus_nodes:
            box = node['box']
            x, y, w, h = box
            click_x = x + w // 2
            click_y = y + h // 2
            logger.info(f"点击加号方框: 文本='{node['text']}', 坐标({click_x},{click_y})")
            click_at_screen(client_rect, click_x, click_y, window=browser_window)
            time.sleep(1.5)
        iteration += 1
        time.sleep(2)

    # 7. 点击叶子节点
    leaf_nodes = [node for node in left_nodes if not node['box']]
    if leaf_nodes:
        leaf = leaf_nodes[0]
        tx, ty, tw, th = leaf['text_box']
        logger.info(f"点击左侧叶子节点: '{leaf['text']}' 位置 ({tx},{ty})")
        click_x = tx + tw // 2
        click_y = ty + th // 2
        click_at_screen(client_rect, click_x, click_y, window=browser_window)
    else:
        logger.warning("未找到左侧无方框文本")

    logger.info("=== 测试程序结束 ===")

if __name__ == "__main__":
    main()