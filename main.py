# -*- coding: utf-8 -*-
import sys
import os
import re
import json
from datetime import datetime, date as date_cls

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QFileDialog,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, QDate

# 导入自定义模块
from Tab01_数据设置 import Tab01_Specify_API_FileNamePath  # noqa: F401
from ui_mainwindow import Ui_MainWindow
from Tab01_数据设置.Tab01_API_tuShare_接口参数爬虫 import TushareDocSpider
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager
from Tab01_数据设置.Tab01_ui_manager import Tab01UIManager

# Tab02 分钟数据下载器（原 CSV/Excel 备用方案）
from Tab02_数据下载.Tab02_minute_data_downloader import Tab02MinuteDataDownloader

# Tab02 分钟数据下载器（SQL Server LocalDB 方案）
from Tab02_数据下载.Tab02_minute_data_downloader_SQL import Tab02MinuteDataDownloaderSQL

# Tab03 分时图组件（位于子目录 Tab03_分析设置 内）
from Tab03_分析设置.Tab03_Minute_Data_Display_Qt import Tab03MinuteDataDisplay

# === MOD: Tab03 历史分时形态匹配 / 叠加 ===
from Tab03_分析设置.Tab03_Minute_Data_mapping_similarity import Tab03MappingSimilarity


# ============================================================
# 持久化临时文件配置
# ============================================================
PERSIST_FILE_NAME = "app_persist.json"

PERSIST_KEYS = [
    "txt_Specify_Initial_Path",
    "txt_file_path",
    "txt_file_name",
    "txt_ts_code",
    "txt_SQL_path_DB_name",
    "txt_SQL_table_name",
    "txt_path_file",
]


# ============================================================
# 【关键修复】不可见字符正则（与 Tab02 SQL 下载器保持一致）
# 覆盖：C0/C1 控制字符、NBSP、欧甘/蒙古空格、
#       \u2000-\u200f 各种空格 + 零宽字符、
#       \u2028-\u202f、\u205f-\u206f、全角空格、BOM
# ============================================================
_INVISIBLE_RE = re.compile(
    "[\u0000-\u0008\u000b-\u001f\u007f-\u009f"
    "\u00a0\u1680\u180e"
    "\u2000-\u200f"
    "\u2028-\u202f"
    "\u205f-\u206f"
    "\u3000"
    "\ufeff\ufff9-\ufffb]"
)


# ---------- 后台爬虫线程 ----------
class SpiderWorker(QObject):
    finished = Signal()
    error    = Signal(str)

    def __init__(self, spider):
        super().__init__()
        self.spider = spider

    def run(self):
        try:
            self.spider.run()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """主窗口类"""

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self._persist_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            PERSIST_FILE_NAME,
        )

        self._load_persist()
        self._init_date_edit_today()

        # Tab01 设置 / UI 管理
        self.settings_manager = Tab01SettingsManager()
        self.ui_manager = Tab01UIManager(self.ui, self.settings_manager)

        # Tab02 下载器（原 CSV/Excel 备用方案）
        self.tab02_downloader = Tab02MinuteDataDownloader(self.ui, self)
        try:
            self.tab02_downloader.finished_signal.connect(self.on_tab02_finished)
            self.tab02_downloader.error_signal.connect(self.on_tab02_error)
            self.tab02_downloader.log_signal.connect(self.on_tab02_progress)
        except Exception as e:
            print(f"[Main] 连接下载器信号失败: {e}")

        # Tab02 SQL 下载器（SQL Server LocalDB 方案）
        self.tab02_sql_downloader = Tab02MinuteDataDownloaderSQL(self.ui, self)
        try:
            self.tab02_sql_downloader.finished_signal.connect(self.on_tab02_sql_finished)
            self.tab02_sql_downloader.error_signal.connect(self.on_tab02_sql_error)
            self.tab02_sql_downloader.log_signal.connect(self.on_tab02_sql_progress)
        except Exception as e:
            print(f"[Main] 连接 SQL 下载器信号失败: {e}")

        # Tab03 分时图组件
        self.tab03_display = None
        try:
            tab2 = self.ui.tab_2
            if tab2.layout() is None:
                tab2_layout = QVBoxLayout(tab2)
                tab2_layout.setContentsMargins(2, 2, 2, 2)
                tab2.setLayout(tab2_layout)

            self.tab03_display = Tab03MinuteDataDisplay(
                self.ui, self, persist_callback=self._save_persist
            )
            tab2.layout().addWidget(self.tab03_display)
            print("[Main] Tab03 分时图组件已加载至 T302_实时行情历史匹配")
        except Exception as e:
            print(f"[Main] Tab03 分时图组件加载失败: {e}")
            self.tab03_display = None

        # === MOD: 创建历史形态匹配组件 ===
        self.tab03_mapping = None
        if self.tab03_display is not None:
            try:
                self.tab03_mapping = Tab03MappingSimilarity(
                    ui=self.ui,
                    tab03_display=self.tab03_display,
                    parent_window=self,
                )
                print("[Main] Tab03 历史形态匹配组件已加载")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Main] Tab03 历史形态匹配组件加载失败: {e}")
                self.tab03_mapping = None
        else:
            print("[Main] Tab03 未加载，跳过历史形态匹配组件")

        # ChangeDate 按钮
        if hasattr(self.ui, 'pushBttn_ChangeDate'):
            try:
                self.ui.pushBttn_ChangeDate.clicked.connect(
                    self.on_pushBttn_ChangeDate_clicked
                )
                print("[Main] 已连接 pushBttn_ChangeDate")
            except Exception as e:
                print(f"[Main] 连接 pushBttn_ChangeDate 失败: {e}")
        else:
            print("[Main] 未找到 pushBttn_ChangeDate 控件")

        # SQL MDF 路径选择
        if hasattr(self.ui, "pushBttn_InitialPath_SQL"):
            try:
                self.ui.pushBttn_InitialPath_SQL.clicked.connect(
                    self.on_pushBttn_InitialPath_SQL_clicked
                )
                print("[Main] 已连接 pushBttn_InitialPath_SQL")
            except Exception as e:
                print(f"[Main] 连接 pushBttn_InitialPath_SQL 失败: {e}")
        else:
            print("[Main] 警告：未找到 pushBttn_InitialPath_SQL 控件")

        # Tab 颜色切换
        self.ui.tabWidget_mainWindow.currentChanged.connect(self.on_tab_changed)
        self.on_tab_changed(self.ui.tabWidget_mainWindow.currentIndex())

        # 菜单动作
        self.ui.actionDataSub01_01.triggered.connect(self.show_hello_world)
        self.ui.menu02_Sub01_DataFolderSelect.triggered.connect(self.open_folder_dialog)

        # Tab01 按钮
        self.ui.pushBttn_API_InitialPath.pressed.connect(self.Tab01_API_InitialPath_dialog)
        self.ui.pushBttn_API_GeneratList.pressed.connect(self.on_generate_list_clicked)

    # ---------------- 持久化 ----------------
    def _load_persist(self):
        try:
            if not os.path.exists(self._persist_file):
                return
            with open(self._persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key in PERSIST_KEYS:
                if key in data and hasattr(self.ui, key):
                    self._set_text(getattr(self.ui, key), data[key])
            print(f"[Main] 已加载持久化数据: {self._persist_file}")
        except Exception as e:
            print(f"[Main] 加载持久化数据失败: {e}")

    def _save_persist(self, *args, **kwargs):
        try:
            data = {}
            for key in PERSIST_KEYS:
                if hasattr(self.ui, key):
                    data[key] = self._get_text(getattr(self.ui, key))
            with open(self._persist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[Main] 持久化数据已保存: {self._persist_file}")
        except Exception as e:
            print(f"[Main] 保存持久化数据失败: {e}")

    # ---------------- SQL 初始路径按钮 ----------------
    def on_pushBttn_InitialPath_SQL_clicked(self):
        try:
            target = getattr(self.ui, "txt_SQL_path_DB_name", None)
            if target is None:
                target = getattr(self.ui, "txt_SQL_path", None)
            if target is None:
                QMessageBox.warning(
                    self, "提示",
                    "未找到 txt_SQL_path_DB_name 控件，无法写入选择结果。",
                )
                return

            current = self._get_text(target)

            initial = ""
            if current:
                if os.path.isfile(current):
                    initial = current
                elif os.path.isdir(current):
                    initial = os.path.join(current, "*.mdf")
                else:
                    parent = os.path.dirname(current)
                    if parent and os.path.isdir(parent):
                        initial = parent

            if not initial:
                try:
                    from Tab02_数据下载.Tab02_minute_data_downloader_SQL import (
                        DEFAULT_SQL_DB_PATH,
                    )
                    initial = DEFAULT_SQL_DB_PATH
                except Exception:
                    initial = os.path.expanduser("~")

            fname, _ = QFileDialog.getOpenFileName(
                self,
                "选择 SQL Server 数据文件（*.mdf）",
                initial,
                "SQL Server 数据文件 (*.mdf);;所有文件 (*.*)",
            )
            if not fname:
                return

            fname = os.path.normpath(fname)
            self._set_text(target, fname)
            print(f"[Main] 数据库文件完整路径已更新为: {fname}")

            self._save_persist()

            # === MOD: 更换数据库后立即触发重匹配 ===
            if getattr(self, "tab03_mapping", None) is not None:
                try:
                    self.tab03_mapping._trigger_mapping()
                except Exception:
                    pass

            try:
                self.statusBar().showMessage(f"已选择数据库文件：{fname}", 5000)
            except Exception:
                pass
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"选择数据库文件失败：\n{e}")

    # ---------------- dateEdit 控件接口 ----------------
    def _init_date_edit_today(self):
        if not hasattr(self.ui, 'dateEdit'):
            print("[Main] 未找到 dateEdit 控件")
            return
        try:
            today = QDate.currentDate()
            self.ui.dateEdit.setDate(today)
            print(f"[Main] dateEdit 已设置为当天日期: {today.toString('yyyy-MM-dd')}")
        except Exception as e:
            print(f"[Main] 设置 dateEdit 日期失败: {e}")

    def get_date_edit_date(self):
        if not hasattr(self.ui, 'dateEdit'):
            print("[Main] get_date_edit_date: 未找到 dateEdit 控件")
            return None
        try:
            qd = self.ui.dateEdit.date()
            d = date_cls(qd.year(), qd.month(), qd.day())
            print(f"[Main] get_date_edit_date 返回: {d}")
            return d
        except Exception as e:
            print(f"[Main] 读取 dateEdit 失败: {e}")
            return None

    def set_date_edit_date(self, d):
        if not hasattr(self.ui, 'dateEdit') or d is None:
            return
        try:
            self.ui.dateEdit.setDate(QDate(d.year, d.month, d.day))
            print(f"[Main] set_date_edit_date 已设置为: {d.strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"[Main] 设置 dateEdit 失败: {e}")

    # ---------------- pushBttn_ChangeDate 按钮接口 ----------------
    def on_pushBttn_ChangeDate_clicked(self):
        if getattr(self, 'tab03_display', None) is None:
            QMessageBox.warning(self, "提示", "Tab03 分时图组件尚未加载，无法按日期提取数据。")
            return

        d = self.get_date_edit_date()
        date_str = d.strftime('%Y-%m-%d') if d else ''

        try:
            self.tab03_display.change_date_reload()
            if date_str:
                self.statusBar().showMessage(
                    f"Tab03: 已按日期 {date_str} 重新提取 1min 分时数据"
                )
            else:
                self.statusBar().showMessage("Tab03: 已按 dateEdit 日期重新提取 1min 分时数据")
            print(f"[Main] ChangeDate 触发，目标日期: {date_str or '(dateEdit)'}")
        except Exception as e:
            print(f"[Main] ChangeDate 执行失败: {e}")
            QMessageBox.warning(self, "错误", f"按日期重新提取失败：{e}")

    def closeEvent(self, event):
        try:
            if getattr(self, "tab03_display", None) is not None:
                self.tab03_display.shutdown()
        except Exception as e:
            print(f"[Main] 关闭 Tab03 组件失败: {e}")

        # === MOD: 关闭 mapping 组件 ===
        try:
            if getattr(self, "tab03_mapping", None) is not None:
                self.tab03_mapping.shutdown()
        except Exception as e:
            print(f"[Main] 关闭 Tab03 匹配组件失败: {e}")

        try:
            if getattr(self, "tab02_sql_downloader", None) is not None:
                self.tab02_sql_downloader.save_settings()
        except Exception as e:
            print(f"[Main] 保存 SQL 下载器设置失败: {e}")

        self._save_persist()
        super().closeEvent(event)

    # ---------------- 通用控件读写（加固：清洗不可见字符） ----------------
    @staticmethod
    def _clean(value):
        """清除 C0/C1、NBSP、零宽、BOM、全角空格等不可见字符，并 strip。"""
        if value is None:
            return ""
        s = str(value)
        if not s:
            return ""
        return _INVISIBLE_RE.sub("", s).strip()

    @staticmethod
    def _get_text(widget):
        if widget is None:
            return ""
        # QPlainTextEdit / QTextEdit
        if hasattr(widget, "toPlainText"):
            try:
                return MainWindow._clean(widget.toPlainText())
            except Exception:
                pass
        # QLineEdit / QLabel / QSpinBox 等
        if hasattr(widget, "text"):
            try:
                return MainWindow._clean(widget.text())
            except Exception:
                pass
        # QComboBox
        if hasattr(widget, "currentText"):
            try:
                return MainWindow._clean(widget.currentText())
            except Exception:
                pass
        return ""

    @staticmethod
    def _set_text(widget, text):
        if widget is None:
            return
        val = MainWindow._clean(text)
        if hasattr(widget, "setPlainText"):
            widget.setPlainText(val)
        elif hasattr(widget, "setText"):
            widget.setText(val)
        elif hasattr(widget, "setCurrentText"):
            try:
                widget.setCurrentText(val)
            except Exception:
                pass

    # ---------------- Tab02 状态回调（原 CSV/Excel 备用方案） ----------------
    def on_tab02_progress(self, msg):
        self.statusBar().showMessage(msg)
        print("[Tab02]", msg)

    def on_tab02_finished(self, *args):
        if hasattr(self.ui, "pushBttn_Generat_minute_List"):
            self.ui.pushBttn_Generat_minute_List.setEnabled(True)
        self.statusBar().showMessage("Tab02 分钟数据下载完成")
        self._save_persist()

    def on_tab02_error(self, msg):
        if hasattr(self.ui, "pushBttn_Generat_minute_List"):
            self.ui.pushBttn_Generat_minute_List.setEnabled(True)
        self.statusBar().showMessage("Tab02 分钟数据下载失败")
        print(f"[Tab02] 错误: {msg}")

    # ---------------- Tab02 SQL 状态回调（SQL Server 方案） ----------------
    def on_tab02_sql_progress(self, msg):
        self.statusBar().showMessage(msg)
        print("[Tab02-SQL]", msg)

    def on_tab02_sql_finished(self, *args):
        if hasattr(self.ui, "pushBttn_Generat_minute_List_SQL"):
            self.ui.pushBttn_Generat_minute_List_SQL.setEnabled(True)
        self.statusBar().showMessage("Tab02 SQL 分钟数据写入完成")
        self._save_persist()
        # === MOD: 数据写入后清缓存并触发重匹配 ===
        if getattr(self, "tab03_mapping", None) is not None:
            try:
                self.tab03_mapping._history_cache.clear()
                self.tab03_mapping._trigger_mapping()
            except Exception:
                pass

    def on_tab02_sql_error(self, msg):
        if hasattr(self.ui, "pushBttn_Generat_minute_List_SQL"):
            self.ui.pushBttn_Generat_minute_List_SQL.setEnabled(True)
        self.statusBar().showMessage("Tab02 SQL 分钟数据写入失败")
        print(f"[Tab02-SQL] 错误: {msg}")

    # ---------------- Tab01 原有逻辑 ----------------
    def handle_save_log(self):
        Tab01_Specify_API_FileNamePath.save_log(
            self.ui.txt_Specify_Initial_Path,
            self.ui.txt_Specify_API_log_Name,
            self.ui.pushBttn_API_GeneratList
        )

    def on_generate_list_clicked(self):
        self.handle_save_log()
        self.start_spider()

    def start_spider(self):
        path = self.ui.txt_Specify_Initial_Path.toPlainText().strip()
        if not path:
            QMessageBox.warning(self, "警告", "请先选择输出路径！")
            return

        save_filename = self.ui.txt_Specify_API_list_Name.toPlainText().strip()
        if not save_filename:
            QMessageBox.warning(self, "警告", "请输入API接口文件名！")
            return

        log_filename = self.ui.txt_Specify_API_log_Name.toPlainText().strip()
        if not log_filename:
            QMessageBox.warning(self, "警告", "请输入日志文件名！")
            return

        output_file = os.path.join(path, save_filename)
        log_file    = os.path.join(path, log_filename)
        os.makedirs(path, exist_ok=True)

        spider = TushareDocSpider(
            start_url='https://tushare.pro/document/2',
            output_file=output_file,
            log_file=log_file,
            delay=1
        )

        self.thread = QThread()
        self.worker = SpiderWorker(spider)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.on_spider_finished)
        self.worker.error.connect(self.on_spider_error)

        self.ui.pushBttn_API_GeneratList.setEnabled(False)
        self.thread.start()

    def on_spider_finished(self):
        self.ui.pushBttn_API_GeneratList.setEnabled(True)
        QMessageBox.information(self, "完成", "爬虫任务已完成！")

    def on_spider_error(self, msg):
        self.ui.pushBttn_API_GeneratList.setEnabled(True)
        QMessageBox.critical(self, "错误", f"爬虫运行出错：{msg}")

    # ---------------- 其他原有方法 ----------------
    def on_tab_changed(self, index):
        tab_bar = self.ui.tabWidget_mainWindow.tabBar()
        for i in range(self.ui.tabWidget_mainWindow.count()):
            tab_bar.setTabTextColor(i, Qt.red if i == index else Qt.green)

    def show_hello_world(self):
        QMessageBox.information(self, "信息", "hello world")

    def open_folder_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if folder_path:
            self.ui.label_1.setText(folder_path)

    def Tab01_API_InitialPath_dialog(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "选择文件夹，作为输出文件的保存位置", ""
        )
        if folder_path:
            self.ui.txt_Specify_Initial_Path.setPlainText(folder_path)
            self._save_persist()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())