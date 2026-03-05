# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
import os
import datetime

class Logger:
    def __init__(self, log_path):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.log_path = log_path

    def log(self, msg):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {msg}\n")
        print(f"[{now}] {msg}")
