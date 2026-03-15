import os
import time
import logging
import webbrowser
import pytesseract
import json
from datetime import datetime
from enum import Enum
from typing import List, Tuple, Dict, Optional

# 尝试导入keyboard，如果失败则给出友好提示并退出
try:
    import keyboard  # 用于检测双击/三击信号
except ImportError:
    print("错误: 缺少 'keyboard' 模块。请运行以下命令安装：")
    print("pip install keyboard")
    exit(1)

import cv2
import numpy as np
import pyautogui
import uiautomation as auto
from PIL import Image, ImageGrab

# 设置 tesseract 可执行文件路径（请根据实际安装路径修改）
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# ==================== 枚举定义 ====================
class BoxType(Enum):
    """方框类型枚举"""
    PLUS = "plus"           # 加号
    MINUS = "minus"         # 减号
    CHECKED = "checked"     # 打勾选中
    UNCHECKED = "unchecked" # 空心未选中
    FILLED = "filled"       # 实心方框
    UNKNOWN = "unknown"     # 未知

class ProgramState(Enum):
    """程序状态枚举"""
    INITIALIZING = "initializing"
    WAITING_FOR_CONTROL = "waiting_for_control"
    PROCESSING = "processing"
    PAUSED = "paused"
    FINISHED = "finished"

# ==================== 配置日志 ====================
def setup_logging():
    """配置日志系统"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(f'uiautomation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', 
                              encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== 配置管理 ====================
class Config:
    """配置管理类"""
    def __init__(self):
        self.url = "https://tushare.pro/webclient/"
        self.max_wait_time = 30  # 最大等待时间（秒）
        self.poll_interval = 0.2  # 轮询间隔（秒）
        self.top_offset = 150  # 顶部偏移量（像素）
        self.ocr_confidence_threshold = 60  # OCR置信度阈值
        self.box_detection_margin = 10  # 方框检测边距
        self.min_box_size = 8  # 最小方框尺寸
        self.max_box_size = 30  # 最大方框尺寸
        self.double_click_interval = 0.5  # 双击间隔（秒）
        self.triple_click_interval = 1.0  # 三击间隔（秒）
        
        # 浏览器关键词
        self.browser_keywords = ["Chrome", "Edge", "Firefox", "Opera", "Brave", "Safari"]
        
        # UIAutomation搜索候选
        self.pane_candidates = [
            {"Name": "网页内容", "ClassName": "Chrome_RenderWidgetHostHWND"},
            {"Name": "内容", "ClassName": "Chrome_RenderWidgetHostHWND"},
            {"Name": "Web Content", "ClassName": "Chrome_RenderWidgetHostHWND"},
            {"Name": "网页视图", "ClassName": "DirectUIHWND"},
            {"Name": "Pane", "ClassName": "Chrome_RenderWidgetHostHWND"},
            {"ControlType": auto.ControlType.PaneControl},
        ]

config = Config()

# ==================== 核心数据结构 ====================
class DetectedElement:
    """检测到的页面元素"""
    def __init__(self, text: str, text_bbox: Tuple[int, int, int, int], 
                 box_bbox: Optional[Tuple[int, int, int, int]] = None,
                 box_type: BoxType = BoxType.UNKNOWN):
        self.text = text
        self.text_bbox = text_bbox  # (x, y, w, h)
        self.box_bbox = box_bbox    # (x, y, w, h)
        self.box_type = box_type
        self.global_coords = None   # 全局屏幕坐标
        
    def to_dict(self):
        """转换为字典"""
        return {
            "text": self.text,
            "text_bbox": self.text_bbox,
            "box_bbox": self.box_bbox,
            "box_type": self.box_type.value,
            "global_coords": self.global_coords
        }

class ProgramContext:
    """程序上下文，保存状态和数据"""
    def __init__(self):
        self.state = ProgramState.INITIALIZING
        self.browser_window = None
        self.client_rect = None
        self.detected_elements = []
        self.click_history = []
        self.api_functions = []
        self.last_click_time = 0
        self.click_count = 0
        
    def save_state(self, filename: str = "program_state.json"):
        """保存程序状态到文件"""
        state_data = {
            "timestamp": datetime.now().isoformat(),
            "state": self.state.value,
            "client_rect": self.client_rect,
            "detected_elements": [elem.to_dict() for elem in self.detected_elements],
            "click_history": self.click_history,
            "api_functions": self.api_functions
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        logger.info(f"程序状态已保存到 {filename}")

# ==================== 浏览器控制函数 ====================
def open_browser_with_url() -> Optional[auto.Control]:
    """打开浏览器并导航到指定URL"""
    logger.info(f"=== 开始测试程序 (混合模式) ===")
    logger.info(f"正在打开URL: {config.url}")
    
    # 使用webbrowser打开URL
    webbrowser.open(config.url)
    logger.info("等待浏览器窗口出现...")
    
    # 等待浏览器窗口
    start_time = time.time()
    browser_window = None
    
    while time.time() - start_time < config.max_wait_time:
        windows = auto.GetRootControl().GetChildren()
        for w in windows:
            if w.Name and "Tushare" in w.Name:
                # 检查是否为浏览器窗口
                if any(keyword in w.Name for keyword in config.browser_keywords):
                    browser_window = w
                    logger.info(f"找到浏览器窗口: {w.Name}")
                    break
        if browser_window:
            break
        time.sleep(config.poll_interval)
    
    if not browser_window:
        logger.warning(f"在 {config.max_wait_time} 秒内未自动找到目标窗口")
        logger.info("请手动将浏览器窗口置于前台，然后按回车键继续...")
        input()
        browser_window = auto.GetForegroundControl()
        if browser_window:
            logger.info(f"已获取当前活动窗口: {browser_window.Name}")
    
    return browser_window

def activate_window(window: auto.Control):
    """激活窗口到前台"""
    if not window:
        return
    
    try:
        # 尝试使用SetActive方法
        window.SetActive()
        time.sleep(0.5)
        
        # 额外尝试点击窗口确保焦点
        rect = window.BoundingRectangle
        center_x = (rect.left + rect.right) // 2
        center_y = (rect.top + rect.bottom) // 2
        pyautogui.click(center_x, center_y)
        time.sleep(0.3)
        
        logger.debug("窗口已激活并置前")
    except Exception as e:
        logger.warning(f"激活窗口时出错: {e}")

# ==================== 内容区域定位 ====================
def locate_content_area(browser_window: auto.Control) -> Tuple[bool, Optional[Tuple]]:
    """定位内容区域，优先使用UIAutomation，失败则使用回退方法"""
    
    # 方法1: 使用UIAutomation精确定位
    logger.info("尝试使用UIAutomation定位内容区域...")
    for cand in config.pane_candidates:
        try:
            if "ControlType" in cand:
                content_pane = browser_window.GetFirstChildControl(
                    cand["ControlType"], searchDepth=5
                )
            else:
                content_pane = browser_window.PaneControl(
                    Name=cand.get("Name"),
                    ClassName=cand.get("ClassName"),
                    searchDepth=5
                )
            
            if content_pane and content_pane.Exists(maxSearchSeconds=2):
                rect = content_pane.BoundingRectangle
                logger.info(f"UIAutomation定位成功: {rect}")
                return True, (rect.left, rect.top, rect.right, rect.bottom)
        except Exception as e:
            continue
    
    # 方法2: 回退到基于窗口坐标的方法
    logger.warning("UIAutomation未能定位到内容区域，使用回退方法")
    return False, get_fallback_client_rect(browser_window)

def get_fallback_client_rect(browser_window: auto.Control) -> Tuple:
    """回退方法：基于窗口坐标估算客户区"""
    rect = browser_window.BoundingRectangle
    client_rect = (
        rect.left,
        rect.top + config.top_offset,
        rect.right,
        rect.bottom
    )
    logger.info(f"使用回退方法估算客户区，顶部偏移: {config.top_offset}，结果: {client_rect}")
    return client_rect

# ==================== 图像处理与OCR ====================
def capture_and_preprocess(client_rect: Tuple) -> Tuple[np.ndarray, np.ndarray]:
    """截取并预处理图像"""
    # 截取屏幕
    image = ImageGrab.grab(bbox=client_rect)
    
    # 转换为OpenCV格式
    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    
    # 转换为灰度图
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    
    # 增强对比度
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    return enhanced, cv_image

def perform_ocr(gray_image: np.ndarray) -> List[Tuple]:
    """执行OCR识别"""
    logger.info("开始OCR识别文字")
    
    # 使用pytesseract进行OCR
    data = pytesseract.image_to_data(
        gray_image, 
        lang='chi_sim+eng', 
        config='--psm 6',
        output_type=pytesseract.Output.DICT
    )
    
    texts = []
    for i in range(len(data['text'])):
        conf = int(data['conf'][i])
        text = data['text'][i].strip()
        
        if conf > config.ocr_confidence_threshold and text:
            x = data['left'][i]
            y = data['top'][i]
            w = data['width'][i]
            h = data['height'][i]
            texts.append((text, (x, y, w, h)))
    
    logger.info(f"识别到 {len(texts)} 个文本块")
    return texts

# ==================== 方框检测与分类 ====================
def detect_and_classify_box(text_bbox: Tuple, gray_image: np.ndarray, 
                           color_image: np.ndarray) -> Tuple[Optional[Tuple], BoxType]:
    """
    检测文本左侧的方框并分类
    
    返回: (方框坐标, 方框类型)
    方框类型包括: PLUS, MINUS, CHECKED, UNCHECKED, FILLED
    """
    tx, ty, tw, th = text_bbox
    
    # 在文本左侧区域搜索方框
    search_left = max(0, tx - th - config.box_detection_margin)
    search_right = tx
    search_top = ty
    search_bottom = ty + th
    
    if search_right - search_left < config.min_box_size:
        return None, BoxType.UNKNOWN
    
    # 提取ROI区域
    roi_gray = gray_image[search_top:search_bottom, search_left:search_right]
    roi_color = color_image[search_top:search_bottom, search_left:search_right]
    
    if roi_gray.size == 0:
        return None, BoxType.UNKNOWN
    
    # 二值化处理
    _, binary = cv2.threshold(roi_gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # 查找轮廓
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, BoxType.UNKNOWN
    
    # 筛选可能的方框轮廓
    candidate_boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 尺寸过滤
        if (w < config.min_box_size or h < config.min_box_size or 
            w > config.max_box_size or h > config.max_box_size):
            continue
        
        # 宽高比过滤（接近正方形）
        aspect = w / h
        if 0.7 < aspect < 1.3:
            # 轮廓面积与边界矩形面积比
            area_ratio = cv2.contourArea(cnt) / (w * h)
            if area_ratio > 0.3:
                candidate_boxes.append((x, y, w, h))
    
    if not candidate_boxes:
        return None, BoxType.UNKNOWN
    
    # 选择最右侧的方框（最接近文本）
    candidate_boxes.sort(key=lambda b: b[0] + b[2], reverse=True)
    best_box = candidate_boxes[0]  # 取第一个
    
    # 计算全局坐标（相对于ROI，需加上search_left/ search_top）
    box_x = search_left + best_box[0]
    box_y = search_top + best_box[1]
    box_w, box_h = best_box[2], best_box[3]
    box_coords = (box_x, box_y, box_w, box_h)
    
    # 分类方框类型
    box_type = classify_box_type(best_box, roi_gray, roi_color)
    
    return box_coords, box_type

def classify_box_type(box_coords: Tuple, gray_roi: np.ndarray, 
                     color_roi: np.ndarray) -> BoxType:
    """分类方框类型（box_coords是相对于gray_roi的坐标）"""
    bx, by, bw, bh = box_coords
    
    # 提取方框内部区域（去掉边框）
    inner_margin = 3
    inner_left = bx + inner_margin
    inner_top = by + inner_margin
    inner_right = bx + bw - inner_margin
    inner_bottom = by + bh - inner_margin
    
    # 检查内部区域是否有效
    if (inner_right <= inner_left or inner_bottom <= inner_top or
        inner_left < 0 or inner_top < 0 or 
        inner_right >= gray_roi.shape[1] or inner_bottom >= gray_roi.shape[0]):
        return BoxType.UNKNOWN

    # 提取内部区域
    inner_gray = gray_roi[inner_top:inner_bottom, inner_left:inner_right]
    inner_color = color_roi[inner_top:inner_bottom, inner_left:inner_right]
    
    if inner_gray.size == 0:
        return BoxType.UNCHECKED  # 空心方框
    
    # 检测内部图案
    _, inner_binary = cv2.threshold(inner_gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # 1. 检测加号/减号（水平+垂直线条）
    lines = cv2.HoughLinesP(inner_binary, 1, np.pi/180, threshold=8, 
                           minLineLength=3, maxLineGap=2)
    
    if lines is not None:
        horizontal_count = 0
        vertical_count = 0
        
        for line in lines:
            x1, y1, x2, y2 = line[0]  # line是一个数组，需要取第一个元素
            angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            
            # 水平线（角度接近0或180度）
            if angle < 20 or angle > 160:
                horizontal_count += 1
            # 垂直线（角度接近90度）
            elif 70 < angle < 110:
                vertical_count += 1
        
        if horizontal_count >= 1 and vertical_count >= 1:
            # 进一步区分加号和减号
            if horizontal_count > vertical_count:
                return BoxType.MINUS  # 主要是水平线，可能是减号
            else:
                return BoxType.PLUS   # 有垂直线，可能是加号
    
    # 2. 检测打勾（V形图案）
    contours, _ = cv2.findContours(inner_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 5:  # 有一定面积
            # 计算凸包
            hull = cv2.convexHull(cnt)
            hull_area = cv2.contourArea(hull)
            if hull_area > 0:
                solidity = area / hull_area
                # 打勾通常不是实心的
                if 0.3 < solidity < 0.7:
                    return BoxType.CHECKED
    
    # 3. 检测实心方框
    inner_mean = np.mean(inner_gray)
    if inner_mean < 100:  # 颜色较深，可能是实心
        return BoxType.FILLED
    
    # 4. 空心方框
    inner_std = np.std(inner_gray)
    if inner_std < 20:  # 颜色均匀，可能是空心
        return BoxType.UNCHECKED
    
    return BoxType.UNKNOWN

# ==================== 交互控制 ====================
def wait_for_user_control(context: ProgramContext):
    """等待用户通过双击转移控制权"""
    logger.info("等待用户双击转移控制权...")
    logger.info("请在浏览器窗口上双击鼠标左键，将控制权交给程序")
    
    context.state = ProgramState.WAITING_FOR_CONTROL
    last_click_time = 0
    click_count = 0
    
    while True:
        # 检测鼠标左键点击（简化实现，使用Ctrl键模拟双击检测）
        if keyboard.is_pressed('ctrl'):
            current_time = time.time()
            
            if current_time - last_click_time < config.double_click_interval:
                click_count += 1
            else:
                click_count = 1
            
            last_click_time = current_time
            
            if click_count == 2:
                logger.info("检测到双击，程序接管控制权")
                context.state = ProgramState.PROCESSING
                time.sleep(1)  # 给用户时间释放按键
                break
            
            if click_count == 3:
                logger.info("检测到三击，终止程序")
                context.state = ProgramState.FINISHED
                return False
        
        time.sleep(0.1)
    
    return True

def process_left_sidebar(context: ProgramContext, gray_image: np.ndarray, 
                        color_image: np.ndarray, client_rect: Tuple):
    """处理左侧边栏，点击所有加号方框"""
    logger.info("开始处理左侧边栏...")
    
    # 筛选左侧区域的元素（假设左侧区域在屏幕左侧1/3）
    screen_width = client_rect[2] - client_rect[0]  # 修正索引
    left_threshold = screen_width // 3
    
    left_elements = []
    for elem in context.detected_elements:
        if elem.box_bbox and elem.box_bbox[0] < left_threshold:
            left_elements.append(elem)
    
    logger.info(f"左侧节点数: {len(left_elements)}")
    
    # 按垂直位置排序（从上到下）
    left_elements.sort(key=lambda e: e.text_bbox[1])
    
    # 点击所有加号方框（确保有box_bbox）
    plus_boxes = [elem for elem in left_elements if elem.box_type == BoxType.PLUS and elem.box_bbox is not None]
    
    if not plus_boxes:
        logger.info("没有检测到加号方框")
        return
    
    logger.info(f"开始第 1 轮加号点击，共 {len(plus_boxes)} 个加号")
    
    for i, elem in enumerate(plus_boxes, 1):
        if elem.box_bbox:
            # 计算全局点击坐标（方框中心）
            global_x = client_rect[0] + elem.box_bbox[0] + elem.box_bbox[2] // 2
            global_y = client_rect[1] + elem.box_bbox[1] + elem.box_bbox[3] // 2
            
            logger.info(f"点击左侧叶子节点: '{elem.text}' 位置 ({elem.box_bbox[0]},{elem.box_bbox[1]})")
            logger.info(f"点击屏幕坐标: ({global_x}, {global_y})")
            
            # 执行点击
            pyautogui.click(global_x, global_y)
            
            # 记录点击历史
            context.click_history.append({
                "timestamp": datetime.now().isoformat(),
                "element_text": elem.text,
                "coordinates": (global_x, global_y),
                "box_type": elem.box_type.value
            })
            
            # 短暂等待界面响应
            time.sleep(0.5)
            
            # 更新元素状态（假设点击后加号变减号）
            elem.box_type = BoxType.MINUS
    
    logger.info("所有加号方框点击完成")

# ==================== API函数生成 ====================
def generate_api_functions(context: ProgramContext):
    """根据检测到的元素生成API函数"""
    logger.info("开始生成API函数...")
    
    api_functions = []
    
    for elem in context.detected_elements:
        if elem.text and len(elem.text) >= 2:  # 至少两个字符
            # 生成函数名（去除特殊字符，使用下划线）
            func_name = elem.text.strip().replace(' ', '_').replace('-', '_')
            func_name = ''.join(c for c in func_name if c.isalnum() or c == '_')
            
            # 生成函数代码
            func_code = f"""def get_{func_name.lower()}_data():
    \"\"\"获取{elem.text}数据\"\"\"
    # TODO: 实现具体API调用
    import tushare as ts
    # 示例代码
    # pro = ts.pro_api()
    # data = pro.{func_name.lower()}()
    # return data
    return None
"""
            api_functions.append(func_code)
    
    # 保存到剪贴板
    all_code = "\n\n".join(api_functions)
    
    try:
        import pyperclip
        pyperclip.copy(all_code)
        logger.info(f"已生成 {len(api_functions)} 个API函数，并复制到剪贴板")
    except ImportError:
        logger.warning("pyperclip未安装，无法复制到剪贴板")
        print("\n" + "="*50)
        print("生成的API函数:")
        print("="*50)
        print(all_code)
    
    context.api_functions = api_functions

# ==================== 主程序 ====================
def main():
    """主程序"""
    context = ProgramContext()
    
    try:
        # 步骤1: 打开浏览器
        browser_window = open_browser_with_url()
        if not browser_window:
            logger.error("无法找到浏览器窗口，程序退出")
            return
        
        context.browser_window = browser_window
        
        # 步骤2: 激活窗口
        activate_window(browser_window)
        
        # 步骤3: 定位内容区域
        success, client_rect = locate_content_area(browser_window)
        if not client_rect:
            logger.error("无法定位内容区域，程序退出")
            return
        
        context.client_rect = client_rect
        logger.info(f"最终使用的客户区: {client_rect}")
        
        # 步骤4: 截取并预处理图像
        logger.info("截取客户区图像")
        gray_image, color_image = capture_and_preprocess(client_rect)
        
        # 步骤5: OCR识别
        texts = perform_ocr(gray_image)
        
        # 步骤6: 检测方框并关联文本
        logger.info("检测方框并关联文本")
        for text, text_bbox in texts:
            box_coords, box_type = detect_and_classify_box(text_bbox, gray_image, color_image)
            
            elem = DetectedElement(text, text_bbox, box_coords, box_type)
            
            # 计算全局坐标
            if box_coords:
                global_x = client_rect[0] + box_coords[0]
                global_y = client_rect[1] + box_coords[1]
                elem.global_coords = (global_x, global_y)
            
            context.detected_elements.append(elem)
            
            # 记录日志
            log_msg = f"文本: '{text}', 位置: {text_bbox}"
            if box_coords:
                log_msg += f", 方框: {box_coords}, 类型: {box_type.value}"
            logger.debug(log_msg)
        
        # 步骤7: 等待用户交互（双击授权）
        if not wait_for_user_control(context):
            logger.info("程序被用户终止")
            context.save_state()
            return
        
        # 步骤8: 处理左侧边栏
        process_left_sidebar(context, gray_image, color_image, client_rect)
        
        # 步骤9: 生成API函数
        generate_api_functions(context)
        
        # 步骤10: 等待用户三击终止
        logger.info("程序执行完成，等待用户三击终止程序...")
        logger.info("请按Ctrl键三次以终止程序")
        
        last_click_time = 0
        click_count = 0
        while True:
            if keyboard.is_pressed('ctrl'):
                current_time = time.time()
                if current_time - last_click_time < config.triple_click_interval:
                    click_count += 1
                else:
                    click_count = 1
                last_click_time = current_time
                if click_count == 3:
                    logger.info("检测到三击，程序终止")
                    break
            time.sleep(0.1)
        
        # 步骤11: 保存状态
        context.state = ProgramState.FINISHED
        context.save_state()
        logger.info("=== 测试程序结束 ===")
        
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序执行出错: {e}", exc_info=True)
    finally:
        if context.state != ProgramState.FINISHED:
            context.save_state("program_state_error.json")

# ==================== 安装说明 ====================
def check_dependencies():
    """检查依赖库"""
    required_packages = {
        'pytesseract': 'pytesseract',
        'opencv-python': 'cv2',
        'pyautogui': 'pyautogui',
        'uiautomation': 'auto',
        'Pillow': 'PIL',
        'keyboard': 'keyboard',
        'numpy': 'np'
    }
    
    missing = []
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.warning(f"缺少依赖包: {', '.join(missing)}")
        logger.info("请使用以下命令安装: pip install " + " ".join(missing))
        return False
    
    return True

if __name__ == "__main__":
    print("="*60)
    print("Tushare Web客户端自动化程序")
    print("="*60)
    print("功能说明:")
    print("1. 自动打开浏览器并导航到Tushare Web客户端")
    print("2. 识别页面左侧菜单结构")
    print("3. 自动展开所有加号菜单项")
    print("4. 生成对应的API函数代码")
    print("5. 支持交互式控制（双击转移控制权，三击终止）")
    print("="*60)
    
    if check_dependencies():
        main()
    else:
        print("请先安装缺失的依赖包，然后重新运行程序。")