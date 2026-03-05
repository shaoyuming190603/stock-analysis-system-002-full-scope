# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
# 与同前缀ui_manager.py联合使用
from PySide6.QtCore import QSettings

class Tab01SettingsManager:
    def __init__(self):
        self.settings=QSettings('MCSD','Tab01app')  # 'Tab01app - 管理Tab01数据页面
        
    def save_group_choice(self, group_name, choice):
        self.settings.setValue('f{group_name}_choice',choice)
        
    def load_group_choice(self,group_name,default):
        return self.settings.value(f'{group_name}_choice',default)


