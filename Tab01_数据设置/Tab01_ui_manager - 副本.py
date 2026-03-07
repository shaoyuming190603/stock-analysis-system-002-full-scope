# This Python file uses the following encoding: utf-8

import sys
import os
import logging
import threading
from datetime import datetime
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QButtonGroup
from PySide6.QtCore import Qt, QDate, Slot, Signal, QObject

# 确保导入路径正确
sys.path.append("./Tab01_数据设置")
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager
from Tab01_数据设置.Tab01_API_tuShare_接口参数爬虫 import TushareDocSpider


# 自定义日志信号类，用于跨线程发射日志消息
class LogSignals(QObject):
    log = Signal(str)


# 自定义 logging Handler，将日志消息通过信号发射到主线程
class QLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        # 通过信号发射，确保主线程接收
        self.signal.log.emit(msg)


class Tab01UIManager:
    def __init__(self, ui, settings_manager):
        self.ui = ui
        self.settings_manager = settings_manager
        self.setup_group()
        self.update_ui_from_selected()  # 初始化时根据加载的选择更新界面

        # 创建日志信号对象并连接槽
        self.log_signals = LogSignals()
        self.log_signals.log.connect(self._on_log_message)

        # 用于控制爬虫线程
        self.spider_thread = None

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

    @Slot(str)
    def _on_log_message(self, message):
        """将日志消息追加到 txt_logger 控件，并自动滚动到底部"""
        self.ui.txt_logger.appendPlainText(message)
        # 滚动到底部
        self.ui.txt_logger.verticalScrollBar().setValue(
            self.ui.txt_logger.verticalScrollBar().maximum()
        )

    def run_current_spider(self):
        """根据当前选择的 API 类型运行对应的爬虫（目前仅支持 TuShare）"""
        checked_id = self.group1.checkedId()
        if checked_id != 1:
            QMessageBox.information(self.ui, "提示", "目前仅支持 TuShare 爬虫。")
            return

        # 获取文件名
        excel_filename = self.ui.txt_Specify_API_list_Name.toPlainText().strip()
        log_filename = self.ui.txt_Specify_API_log_Name.toPlainText().strip()
        if not excel_filename or not log_filename:
            QMessageBox.warning(self.ui, "警告", "文件名不能为空。")
            return

        # 获取保存路径（这里假设从设置管理器中获取工作目录）
        base_dir = self.settings_manager.get_working_directory()
        if not base_dir:
            # 如果设置中没有，则使用当前目录
            base_dir = os.getcwd()

        full_excel_path = os.path.join(base_dir, excel_filename)
        full_log_path = os.path.join(base_dir, log_filename)

        # 清空日志显示
        self.ui.txt_logger.clear()

        # 创建爬虫实例
        spider = TushareDocSpider(
            start_url='https://tushare.pro/document/2',
            output_file=full_excel_path,
            log_file=full_log_path,
            delay=1,
            max_workers=5
        )

        # 配置自定义日志处理器，将日志重定向到 GUI
        # 创建 QLogHandler，设置格式（与爬虫原有格式保持一致）
        qhandler = QLogHandler(self.log_signals)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        qhandler.setFormatter(formatter)
        qhandler.setLevel(logging.INFO)

        # 将自定义 handler 添加到爬虫的 logger 中
        spider.logger.addHandler(qhandler)

        # 禁用爬虫原有的控制台 handler？可以保留，但为了避免重复输出到终端，可以选择移除控制台 handler
        # 如果希望终端仍然输出，则保留即可；如果希望只输出到 GUI，可以移除控制台 handler
        # 这里我们保留终端输出，让 GUI 和终端同时显示

        # 在单独线程中运行爬虫，避免阻塞 GUI
        def run_spider():
            try:
                spider.run()
            except Exception as e:
                spider.logger.error(f"爬虫运行异常: {e}", exc_info=True)
            finally:
                # 完成后可以移除自定义 handler（可选）
                spider.logger.removeHandler(qhandler)
                # 可在此发送一个完成信号（如果需要）
                self.log_signals.log.emit("爬虫运行结束。")

        self.spider_thread = threading.Thread(target=run_spider, daemon=True)
        self.spider_thread.start()

    # 可选：提供一个停止爬虫的方法（如果爬虫支持中断）
    # def stop_spider(self):
    #     if self.spider_thread and self.spider_thread.is_alive():
    #         # 需要爬虫内部支持停止标志，此处仅作示意
    #         pass
