# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
import os
import json

class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.config = {
            "excel_name": "TuShareAPI_full_list.xlsx",
            "save_dir": "API_path",
            "log_file": "TuShareAPI_crawler.log"
        }
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.config.update(json.load(f))

    def save_config(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def get_excel_name(self):
        return self.config.get("excel_name", "TuShareAPI_full_list.xlsx")

    def set_excel_name(self, name):
        self.config["excel_name"] = name

    def get_save_dir(self):
        return self.config.get("save_dir", "API_path")

    def get_log_path(self):
        return os.path.join(self.get_save_dir(), self.config.get("log_file", "TuShareAPI_crawler.log"))
