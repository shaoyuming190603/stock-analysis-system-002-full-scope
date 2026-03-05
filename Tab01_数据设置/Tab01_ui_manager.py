# This Python file uses the following encoding: utf-8

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QButtonGroup
from PySide6.QtCore import Qt, QDate, Slot
from datetime import datetime

# 确保导入路径正确
sys.path.append("./Tab01_数据设置")
from Tab01_数据设置.Tab01_settings_manager import Tab01SettingsManager


class Tab01UIManager:
    def __init__(self, ui, settings_manager):
        self.ui = ui
        self.settings_manager = settings_manager
        self.setup_group()
        self.update_ui_from_selected() # 初始化时根据加载的选择更新界面

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

        # 或者方法2：使用buttonClicked信号并配合@Slot修饰符
        # self.group1.buttonClicked.connect(self.on_group1_button_clicked)

    @Slot(int) # 如果使用方法2，需要这个修饰符
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
        if checked_id == 1: # TuShare
            label_text1 = "TuShare API接口列表"
            label_text2 = "TuShare API日志文件"
            label_text3 = "TuShare API保存路径"
            plain_text1 = f"TuShare API接口列表_{today_str}"
            plain_text2 = f"TuShare API日志文件_{today_str}"

        elif checked_id == 2: # AST
            label_text1 = "AST API接口列表"
            label_text2 = "AST API日志文件"
            label_text3 = "AST API保存路径"
            plain_text1 = f"AST API接口列表_{today_str}"
            plain_text2 = f"AST API日志文件_{today_str}"
        elif checked_id == 3: # Choice
            label_text1 = "东财CHOICE API接口列表"
            label_text2 = "东财CHOICE API日志文件"
            label_text3 = "东财CHOICE API保存路径"
            plain_text1 = f"东财CHOICE API接口列表_{today_str}"
            plain_text2 = f"东财CHOICE API接口列表_{today_str}"
        else:
            label_text1 = "其他 API接口列表"
            label_text2 = "其他 API日志文件"
            label_text3 = "其他 API保存路径"
            plain_text1 = f"其他 API接口列表_{today_str}"
            plain_text2 = f"其他 API日志文件_{today_str}"

        # 更新界面控件
        self.ui.lab_Specify_API_list_Name.setText(label_text1)
        self.ui.lab_Specify_API_log_Name.setText(label_text2)
        self.ui.lab_Specify_Initial_Path.setText(label_text3)
        self.ui.txt_Specify_API_list_Name.setPlainText(plain_text1)
        self.ui.txt_Specify_API_log_Name.setPlainText(plain_text2)
        # self.ui.txt_Specify_API_list_Name.setPlainText(plain_text3)

