# Tab01_数据设置\Tab01_ui_manager.py
# This Python file uses the following encoding: utf-8

import sys
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QButtonGroup
from PySide6.QtCore import Qt, QDate, Slot, Signal, QObject
from PySide6.QtGui import QTextCursor
from datetime import datetime

# 确保导入路径正确
sys.path.append("./Tab01_数据设置")
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager
from Tab01_数据设置.Tab01_API_tuShare_接口参数爬虫 import TushareDocSpider


class QtLogHandler(logging.Handler):
    """自定义日志处理器，将日志记录通过 Qt 信号发送到主线程"""
    def __init__(self, signal):
        super().__init__()
        self.signal = signal
        # 设置与爬虫相同的日志格式，保持一致性
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))

    def emit(self, record):
        """当有日志记录时，通过信号发送格式化后的消息"""
        msg = self.format(record)
        # 信号是线程安全的，可以在子线程中调用
        self.signal.emit(msg)


class Tab01UIManager(QObject):   # 修改：继承 QObject 以便使用信号
    # 定义信号，用于从子线程传递日志消息到主线程
    log_signal = Signal(str)

    def __init__(self, ui, settings_manager):
        super().__init__()       # 必须调用父类初始化
        self.ui = ui
        self.settings_manager = settings_manager

        # ----- 新增：配置 UI 日志控件并连接信号 -----
        # 移除最大行数限制，以便显示所有日志（实现滚动播放）
        self.ui.txt_logger.setMaximumBlockCount(0)
        # 连接信号到槽函数（自动在主线程执行）
        self.log_signal.connect(self.append_log)

        # ----- 新增：猴子补丁，为 TushareDocSpider 添加 Qt 日志处理器 -----
        self._patch_tushare_spider_logging()

        # 原有的界面初始化
        self.setup_group()
        self.update_ui_from_selected()

    def _patch_tushare_spider_logging(self):
        """
        猴子补丁：替换 TushareDocSpider._setup_logging 方法，
        在保留原有文件和控制台日志的基础上，添加一个 QtLogHandler。
        """
        # 保存原始方法，以便在补丁中调用
        original_setup = TushareDocSpider._setup_logging

        # 创建自定义的 Qt 日志处理器，并关联本类的信号
        self.qt_handler = QtLogHandler(self.log_signal)

        def patched_setup_logging(spider_instance):
            """
            新的 _setup_logging 方法：
            1. 调用原始方法（创建文件和控制台处理器）
            2. 获取 logger 并添加自定义的 QtLogHandler
            """
            # 先执行原始的设置（创建文件和控制台处理器）
            original_setup(spider_instance)

            # 再添加我们自己的 Qt 处理器
            # 注意：原始方法中会清空 handlers，所以此时 logger.handlers 只有刚添加的文件和控制台处理器
            spider_instance.logger.addHandler(self.qt_handler)

        # 替换原类的方法
        TushareDocSpider._setup_logging = patched_setup_logging

    @Slot(str)
    def append_log(self, message):
        """
        槽函数：将日志消息追加到 txt_logger 控件，并自动滚动到底部。
        该函数在主线程执行，因此可以安全地操作 UI。
        """
        # 追加文本
        self.ui.txt_logger.appendPlainText(message)
        # 滚动到底部，实现滚动播放效果
        cursor = self.ui.txt_logger.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.ui.txt_logger.setTextCursor(cursor)
        self.ui.txt_logger.ensureCursorVisible()

    # ========== 以下为原有代码，未作任何修改 ==========
    def setup_group(self):
        """初始化单选按钮组，加载上次选择，并连接信号"""
        # 组1 - 数据API接口来源
        self.group1 = QButtonGroup()
        self.group1.addButton(self.ui.radioBttn01_TuShare, 1)
        self.group1.addButton(self.ui.radioBttn02_AST, 2)
        self.group1.addButton(self.ui.radioBttn03_Choice, 3)
        self.group1.addButton(self.ui.radioBttn04_Other, 4)

        # 加载上次保存的选项(默认 ID 为 1，即TuShare)
        saved_id = int(self.settings_manager.load_group_choice('group1', 1))
        btn = self.group1.button(saved_id)
        if btn:
            btn.setChecked(True)

        # 方法1：使用idClicked信号（最简单直接）
        self.group1.idClicked.connect(self.on_group1_button_clicked)

    @Slot(int)
    def on_group1_button_clicked(self, button_id):
        """单选按钮点击时的处理：保存选择并更新界面"""
        self.settings_manager.save_group_choice('group1', button_id)
        self.update_ui_from_selected()

    def update_ui_from_selected(self):
        """根据当前选中的单选按钮更新标签和文本框内容"""
        checked_id = self.group1.checkedId()
        # 生成当前日期字符串，格式为YYYY_MM_DD
        today_str = QDate.currentDate().toString("yyyy_MM_dd")

        # 根据选中ID设置对应文本
        if checked_id == 1:  # TuShare
            label_text1 = "TuShare API接口列表"
            label_text2 = "TuShare API日志文件"
            label_text3 = "TuShare API保存路径"
            plain_text1 = f"TuShare API接口列表_{today_str}.xlsx"
            plain_text2 = f"TuShare API日志文件_{today_str}.log"

        elif checked_id == 2:  # AST
            label_text1 = "AST API接口列表"
            label_text2 = "AST API日志文件"
            label_text3 = "AST API保存路径"
            plain_text1 = f"AST API接口列表_{today_str}.xlsx"
            plain_text2 = f"AST API日志文件_{today_str}.log"
        elif checked_id == 3:  # Choice
            label_text1 = "东财CHOICE API接口列表"
            label_text2 = "东财CHOICE API日志文件"
            label_text3 = "东财CHOICE API保存路径"
            plain_text1 = f"东财CHOICE API接口列表_{today_str}.xlsx"
            plain_text2 = f"东财CHOICE API日志文件_{today_str}.log"
        else:
            label_text1 = "其他 API接口列表"
            label_text2 = "其他 API日志文件"
            label_text3 = "其他 API保存路径"
            plain_text1 = f"其他 API接口列表_{today_str}.xlsx"
            plain_text2 = f"其他 API日志文件_{today_str}.log"

        # 更新界面控件
        self.ui.lab_Specify_API_list_Name.setText(label_text1)
        self.ui.lab_Specify_API_log_Name.setText(label_text2)
        self.ui.lab_Specify_Initial_Path.setText(label_text3)
        self.ui.txt_Specify_API_list_Name.setPlainText(plain_text1)
        self.ui.txt_Specify_API_log_Name.setPlainText(plain_text2)