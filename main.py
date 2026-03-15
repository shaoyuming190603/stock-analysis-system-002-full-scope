import sys
import os
import time
from datetime import datetime # 新增导入
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog
from PySide6.QtCore import Qt, QThread, Signal, QObject # 新增导入

# 导入自定义模块
# from Tab01_数据设置 import Tab01_Specify_API_FileNamePath
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager
from Tab01_数据设置.Tab01_API_tuShare_接口参数爬虫 import TushareDocSpider
from Tab01_数据设置.Tab01_ui_manager import Tab01UIManager
from ui_mainwindow import Ui_MainWindow # 导入生成的 UI 文件

# ---------- 新增：后台工作线程类 ----------
class SpiderWorker(QObject):
    """后台工作线程类"""
    finished = Signal() # 完成信号
    error = Signal(str) # 错误信号（带错误信息）

    def __init__(self, spider):
        super().__init__()
        self.spider = spider

    def run(self):
        """在线程中执行爬虫"""
        try:
            self.spider.run()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
# -----------------------------------------

class MainWindow(QMainWindow):
    """主窗口类
    // class 版本：1.0.0
    描述：主窗口类，负责处理用户交互。
    描述：继承自 QMainWindow，负责初始化 UI 和处理用户交互。
    
    
    """
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.settings_manager = Tab01SettingsManager()
        self.ui_manager = Tab01UIManager(self.ui, self.settings_manager)
        # self.resize(2640, 480) # 动态调整窗口大小

        # 绑定tab切换信号
        self.ui.tabWidget_mainWindow.currentChanged.connect(self.on_tab_changed)
        self.on_tab_changed(self.ui.tabWidget_mainWindow.currentIndex()) # 初始化时设置一次

        # 绑定菜单动作
        self.ui.actionDataSub01_01.triggered.connect(self.show_hello_world)
        self.ui.menu02_Sub01_DataFolderSelect.triggered.connect(self.open_folder_dialog) # 关联菜单项“Data_Sub02”

        # 关联菜单项“pushButton”, 此处 “pushBttn_API_InitialPath”， 是UI设计界面控件object name。
        self.ui.pushBttn_API_InitialPath.pressed.connect(self.Tab01_API_InitialPath_dialog)

        # ***** 修改点：将原来两个连接合并为一个统一的槽函数 *****
        self.ui.pushBttn_API_GeneratList.pressed.connect(self.on_generate_list_clicked)

        # 设置控件初始值（原有注释保留）
        # self.ui.txt_Specify_API_list_Name.setPlainText("123")

    # 保存日志的按钮事件处理（保持不变）
    def handle_save_log(self):
        Tab01_Specify_API_FileNamePath.save_log(
            self.ui.txt_Specify_Initial_Path,
            self.ui.txt_Specify_API_log_Name,
            self.ui.pushBttn_API_GeneratList
        )

    # ***** 新增：按钮点击后的统一处理 *****
    def on_generate_list_clicked(self):
        # 先保存日志（同步操作，很快）
        self.handle_save_log()
        # 然后启动爬虫（后台运行）
        self.start_spider()

    # ***** 新增：启动后台爬虫 *****
    def start_spider(self):
        # 获取输出路径
        path = self.ui.txt_Specify_Initial_Path.toPlainText().strip()
        if not path:
            QMessageBox.warning(self, "警告", "请先选择输出路径！")
            return

        # 构造文件名（可根据需要修改）
        # 从控件获取文件名（假设控件为 QPlainTextEdit 或 QLineEdit）
        save_filename = self.ui.txt_Specify_API_list_Name.toPlainText().strip()
        if not save_filename:
            # 如果用户未输入，使用默认名称
            # save_filename = "tuShare接口输入输出参数清单.xlsx"
            # 或者您也可以弹出警告，要求用户输入
            QMessageBox.warning(self, "警告", "请输入API接口文件名！")
            return

        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        timestamp = datetime.now().strftime("%H%M%S")

        # log_filename = f"tuShare爬虫日志_{timestamp}.log"
        log_filename= self.ui.txt_Specify_API_log_Name.toPlainText().strip()
        if not log_filename:
            # 如果用户未输入，使用默认名称
            # log_filename = "tuShare接口日志文件.log"
            # 或者您也可以弹出警告，要求用户输入
            QMessageBox.warning(self, "警告", "请输入日志文件名！")
            return


        output_file = os.path.join(path, save_filename)
        log_file = os.path.join(path, log_filename)

        # 确保目录存在
        os.makedirs(path, exist_ok=True)

        # 创建爬虫实例
        spider = TushareDocSpider(
            start_url='https://tushare.pro/document/2',
            output_file=output_file,
            log_file=log_file,
            delay=1
        )

        # 创建线程和工作对象
        self.thread = QThread()
        self.worker = SpiderWorker(spider)
        self.worker.moveToThread(self.thread)

        # 连接信号
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.on_spider_finished)
        self.worker.error.connect(self.on_spider_error)

        # 禁用按钮，防止重复点击
        self.ui.pushBttn_API_GeneratList.setEnabled(False)
        # 启动线程
        self.thread.start()

    # ***** 新增：爬虫完成后的处理 *****
    def on_spider_finished(self):
        self.ui.pushBttn_API_GeneratList.setEnabled(True)
        QMessageBox.information(self, "完成", "爬虫任务已完成！")

    # ***** 新增：爬虫出错处理 *****
    def on_spider_error(self, msg):
        self.ui.pushBttn_API_GeneratList.setEnabled(True)
        QMessageBox.critical(self, "错误", f"爬虫运行出错：{msg}")

    # 以下方法保持不变 ------------------------------------
    def on_tab_changed(self, index):
        tab_bar = self.ui.tabWidget_mainWindow.tabBar()
        tab_count = self.ui.tabWidget_mainWindow.count()
        for i in range(tab_count):
            if i == index:
                tab_bar.setTabTextColor(i, Qt.red) # 当前tab红色
            else:
                tab_bar.setTabTextColor(i, Qt.green) # 其他tab绿色

    def show_hello_world(self):
        QMessageBox.information(self, "信息", "hello world")

    def open_folder_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if folder_path:
            self.ui.label_1.setText(folder_path)

    def Tab01_API_InitialPath_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹，作为输出文件的保存位置", "")
        if folder_path:
            self.ui.txt_Specify_Initial_Path.setPlainText(folder_path)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
