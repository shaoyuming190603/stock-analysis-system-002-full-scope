# This Python file uses the following encoding: utf-8

# if __name__ == "__main__":
#     pass
import os

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)
