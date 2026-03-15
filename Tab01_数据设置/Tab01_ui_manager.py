# Tab01_数据设置\Tab01_ui_manager.py
# This Python file uses the following encoding: utf-8
import os
import sys
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QButtonGroup
from PySide6.QtCore import Qt, QDate, Slot, Signal, QObject
from PySide6.QtGui import QTextCursor
from datetime import datetime

# 确保导入路径正确
sys.path.append("./Tab01_数据设置")
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager
from Tab01_数据设置.Tab01_API_tuShare_接口参数爬虫 import TushareDocSpider


class QtLogHandler(logging.Handler):
    """
    // class 版本：1.0.0 (自定义日志处理器，将日志记录通过 Qt 信号发送到主线程)
    
    所属文件名：Tab01_ui_manager.py
    功能：定义一个自定义的日志处理器，将日志消息通过 Qt 信号发送到主线程，以便在 UI 中显示。
    功能：
    1. 创建 QtLogHandler 类，继承 logging.Handler，用于将日志记录通过 Qt 信号发送到主线程。 
    2. 创建 QtLogHandler 类的实例，并设置格式。
    3. 重写 emit 方法，将格式化后的消息发送给 Qt 槽函数。
    4. 创建 QtLogHandler 实例，并设置格式。
    5. 在 Tab01UIManager 类中，定义一个 log_signal 信号，用于从子线程传递日志消息到主线程。
    6. 在 Tab01UIManager 类中，定义一个 append_log 槽函数，用于在 UI 中显示日志消息。
    7. 在 Tab01UIManager 类中，定义 append_log 槽函数，用于在 UI 中显示日志消息。
    8. 在 Tab01UIManager 类中，定义 append_log 槽函数，用于在 UI 中显示日志消息。
    9. 在 Tab01UIManager 类中，定义一个 _patch_tushare_spider_logging 方法，用于猴子补丁 TushareDocSpider 类，使其使用 QtLogHandler 进行日志记录。
    """
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

        # ----- 新增：猴子补丁，为 TushareDocSpider 添加 Qt 日志处理器，并修改 run 方法以捕获进度信息 -----
        self._patch_tushare_spider_logging()

        # 原有的界面初始化
        self.setup_group()
        self.update_ui_from_selected()

    def _patch_tushare_spider_logging(self):
        """
        猴子补丁：
        1. 替换 TushareDocSpider._setup_logging 方法，添加 QtLogHandler。
        2. 替换 TushareDocSpider.run 方法，将其中的 print 进度改为 logger.info，
           使得进度信息也能通过日志系统被 UI 捕获。
        """
        # 保存原始方法，以便在补丁中调用（实际上不需要调用原始 run，我们直接重写）
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

        # ----- 新增：替换 run 方法，将 print 进度改为 logger.info -----
        def patched_run(spider_instance):
            """
            重写的 run 方法，与原始逻辑完全一致，但将进度输出由 print 改为 logger.info。
            """
            spider_instance.logger.info("="*50)
            spider_instance.logger.info("爬虫程序开始运行（多线程模式）")
            spider_instance.logger.info(f"目标起始页：{spider_instance.start_url}")
            spider_instance.logger.info(f"输出文件：{spider_instance.output_file}")
            spider_instance.logger.info(f"日志文件：{spider_instance.log_file}")
            spider_instance.logger.info(f"线程池大小：{spider_instance.max_workers}")
            spider_instance.logger.info("="*50)

            doc_links = spider_instance.get_all_doc_links()
            if not doc_links:
                spider_instance.logger.error("未找到任何文档链接，程序退出。")
                return

            total_pages = len(doc_links)
            spider_instance.logger.info(f"开始遍历 {total_pages} 个接口页面...")

            # 进度统计变量
            start_time = time.time()
            processed = 0

            input_local, output_local, extra_local = [], [], []
            success_count = skipped_count = failed_count = 0

            with ThreadPoolExecutor(max_workers=spider_instance.max_workers) as executor:
                future_to_url = {executor.submit(spider_instance.parse_api_page, link): link for link in doc_links}
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    processed += 1

                    # 计算进度信息
                    elapsed = time.time() - start_time
                    avg_per_page = elapsed / processed
                    total_estimated = avg_per_page * total_pages
                    elapsed_mmss = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
                    total_hms = time.strftime("%H:%M:%S", time.gmtime(total_estimated))
                    progress = processed / total_pages * 100

                    # 原 print 改为 logger.info
                    spider_instance.logger.info(
                        f"当前解析第{processed}页，共{total_pages}页，"
                        f"当前已用时{elapsed_mmss}，预计总用时{total_hms}，当前进度{progress:.2f}%"
                    )

                    try:
                        status, data, extra = future.result()
                        if status == 'success':
                            api, title, url, inp, outp = data
                            input_local.append((api, title, url, inp))
                            output_local.append((api, title, url, outp))
                            extra_local.append(extra)
                            success_count += 1
                        elif status == 'skipped':
                            skipped_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        spider_instance.logger.error(f"处理任务结果时发生异常（URL: {url}）：{e}", exc_info=True)
                        failed_count += 1

            spider_instance.input_data = input_local
            spider_instance.output_data = output_local
            spider_instance.extra_data = extra_local

            spider_instance.logger.info("="*50)
            spider_instance.logger.info("爬取完成，统计信息：")
            spider_instance.logger.info(f"总页面数：{total_pages}")
            spider_instance.logger.info(f"成功解析：{success_count}")
            spider_instance.logger.info(f"跳过页面：{skipped_count}")
            spider_instance.logger.info(f"失败页面：{failed_count}")
            spider_instance.logger.info("="*50)

            if spider_instance.input_data or spider_instance.output_data:
                spider_instance._save_to_excel()
            else:
                spider_instance.logger.warning("没有成功解析任何数据，Excel 文件未生成。")

        # 替换原 run 方法
        TushareDocSpider.run = patched_run

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

        # from deepseek:
        # https://chat.deepseek.com/a/chat/s/420fb3f9-0cd2-4bf3-a043-14cb0bbf74dc
        # 获取当前脚本的绝对路径
        current_file = os.path.abspath(__file__)
        # 当前脚本所在目录
        current_dir = os.path.dirname(current_file)
        # 项目根目录：当前目录的上一级（根据实际情况可能需要向上多级）
        project_root = os.path.dirname(current_dir)


        # 根据选中ID设置对应文本
        if checked_id == 1:  # TuShare
            label_text1 = "TuShare API接口列表"
            label_text2 = "TuShare API日志文件"
            label_text3 = "TuShare API保存路径"
            label_text4 = "TuShare 网站 URL"
            plain_text1 = f"TuShare API接口列表_{today_str}.xlsx"
            plain_text2 = f"TuShare API日志文件_{today_str}.log"
            # plain_text3 = f"{current_dir}\Tab0101_TuShareAPI接口参数下载"
            plain_text3 = os.path.join(current_dir, "Tab0101_TuShareAPI接口参数下载")

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
        self.ui.txt_Specify_Initial_Path.setPlainText(plain_text3)
