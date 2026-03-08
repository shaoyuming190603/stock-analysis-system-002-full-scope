"""
版本管理工具，提供装饰器用于给函数添加版本信息。
版本: 1.0.0
"""
from functools import wraps

def add_version_info(version, author, description):
    """装饰器：为函数添加版本属性。"""
    def decorator(func):
        func.__version__ = version
        func.__author__ = author
        func.__description__ = description
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator