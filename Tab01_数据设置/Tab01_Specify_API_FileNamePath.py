# -*- coding: utf-8 -*-
"""
Tab01_Specify_API_FileNamePath.py
=================================
Tab01_数据设置 —— 生成 API 清单时写日志文件的工具模块。

对外接口（保持向后兼容）：
    save_log(txt_Specify_Initial_Path,
             txt_Specify_API_log_Name,
             pushBttn_API_GeneratList,
             on_error=None) -> bool

主要特性：
  * 目录不存在自动创建；创建失败记录日志并返回 False（不再抛 FileNotFoundError）
  * 路径为空 / 非法文件名字符 / 写入失败 均被捕获并记录
  * 使用 logging 写模块日志（模块目录优先，失败回退到系统临时目录）
  * 全程不向外抛异常，返回值 True/False 表示是否写入成功
"""

import os
import re
import sys
import logging
import tempfile
from datetime import datetime


# ============================================================
# 模块级 logger
# ============================================================
_LOGGER_NAME   = "Tab01_Specify_API_FileNamePath"
_LOG_FILE_NAME = "Tab01_Specify_API_FileNamePath.log"

# Windows 文件名非法字符 + 控制字符
_ILLEGAL_CHARS_RE  = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_BASENAME_LEN  = 180        # 避免 Windows 超长路径（260 字符限制）

_DEFAULT_LOG_BASENAME = "API_log"


def _build_logger():
    """初始化模块 logger：优先模块目录，失败回退到系统临时目录"""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:                    # 避免重复初始化
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False               # 不向 root 传播，避免重复输出

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 文件：模块目录优先，失败回退系统临时目录
    candidates = []
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    candidates.append(tempfile.gettempdir())

    for folder in candidates:
        try:
            if not folder or not os.path.isdir(folder):
                continue
            path = os.path.join(folder, _LOG_FILE_NAME)
            fh = logging.FileHandler(path, mode="a", encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
            logger.info("模块日志文件: %s", path)
            break
        except Exception as exc:
            print(f"[Tab01] 无法在 {folder} 创建日志文件: {exc}")

    return logger


_logger = _build_logger()


# ============================================================
# 小工具
# ============================================================
def _widget_get_text(widget):
    """兼容 QLineEdit / QPlainTextEdit 读取文本"""
    if widget is None:
        return ""
    try:
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText().strip()
        if hasattr(widget, "text"):
            return str(widget.text()).strip()
    except Exception as exc:
        _logger.warning("读取控件文本失败: %s", exc)
    return ""


def _widget_get_object_name(widget, fallback="<None>"):
    try:
        if widget is not None and hasattr(widget, "objectName"):
            return widget.objectName() or fallback
    except Exception:
        pass
    return fallback


def _sanitize_filename(name, fallback=_DEFAULT_LOG_BASENAME):
    """清理 Windows 非法字符、去首尾空格与尾点、限长；空时用 fallback"""
    if not name:
        return fallback
    name = _ILLEGAL_CHARS_RE.sub("_", str(name))
    name = name.strip().rstrip(". ")
    if not name:
        return fallback
    if len(name) > _MAX_BASENAME_LEN:
        name = name[:_MAX_BASENAME_LEN]
    return name


def _ensure_dir(path):
    """确保目录存在；成功返回 True，失败记录 error 返回 False"""
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as exc:
        _logger.error("创建目录失败: %s (%s)", path, exc)
        return False


def _notify_error(on_error, msg):
    """可选错误回调"""
    if on_error is None:
        return
    try:
        on_error(msg)
    except Exception as exc:
        _logger.warning("on_error 回调执行失败: %s", exc)


# ============================================================
# 对外接口
# ============================================================
def save_log(txt_Specify_Initial_Path,
             txt_Specify_API_log_Name,
             pushBttn_API_GeneratList,
             on_error=None):
    """
    写 Tab01 API 清单创建日志。

    参数
    ----
    txt_Specify_Initial_Path : 输出目录控件（QPlainTextEdit / QLineEdit）
    txt_Specify_API_log_Name : 日志文件名控件（不含时间戳与 .log 扩展名）
    pushBttn_API_GeneratList : 触发按钮控件（仅取 objectName 写日志）
    on_error                 : 可选；签名 callable(msg:str)，失败时被调用

    返回
    ----
    bool : True 表示日志写入成功；False 表示失败（已记录日志，不抛异常）
    """
    try:
        # ---------- 读取控件 ----------
        api_initial_path_obj_name = _widget_get_object_name(txt_Specify_Initial_Path)
        api_initial_path          = _widget_get_text(txt_Specify_Initial_Path)

        api_log_obj_name     = _widget_get_object_name(txt_Specify_API_log_Name)
        api_initial_log_text = _widget_get_text(txt_Specify_API_log_Name)

        api_gen_btn_name = _widget_get_object_name(pushBttn_API_GeneratList)

        _logger.info("-" * 60)
        _logger.info("save_log 被调用")
        _logger.info("  路径控件名称: %s", api_initial_path_obj_name)
        _logger.info("  路径内容    : %r", api_initial_path)
        _logger.info("  日志名控件  : %s", api_log_obj_name)
        _logger.info("  日志名内容  : %r", api_initial_log_text)
        _logger.info("  触发按钮    : %s", api_gen_btn_name)

        # ---------- 校验输出路径 ----------
        if not api_initial_path:
            msg = "输出路径为空，无法写入日志文件"
            _logger.error(msg)
            _notify_error(on_error, msg)
            return False

        # 目录不存在 -> 尝试自动创建
        if not os.path.isdir(api_initial_path):
            _logger.warning("输出目录不存在，尝试创建: %s", api_initial_path)
            if not _ensure_dir(api_initial_path):
                msg = f"输出目录创建失败，放弃写日志: {api_initial_path}"
                _logger.error(msg)
                _notify_error(on_error, msg)
                return False

        # ---------- 文件名 ----------
        safe_base = _sanitize_filename(api_initial_log_text,
                                       fallback=_DEFAULT_LOG_BASENAME)
        now       = datetime.now()
        time_str  = now.strftime("%Y%m%d_%H%M%S")
        log_filename = f"{safe_base}_{time_str}.log".replace(" ", "_")
        log_path     = os.path.join(api_initial_path, log_filename)

        # ---------- 写入 ----------
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"API清单创建日期时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"API log文件名的控件名称: {api_log_obj_name}\n")
                f.write(f"API log文件名: {api_initial_log_text}\n")
                f.write(f"文件保存路径控件名称: {api_initial_path_obj_name}\n")
                f.write(f"文件保存路径: {api_initial_path}\n")
                f.write(f"触发生成API清单的按钮控件名称: {api_gen_btn_name}\n")
        except Exception as exc:
            msg = f"写入日志文件失败: {log_path} ({exc})"
            _logger.exception(msg)
            _notify_error(on_error, msg)
            return False

        _logger.info("日志已保存: %s", log_path)
        return True

    except Exception as exc:
        # 兜底：任何未预期异常都不向外抛
        try:
            _logger.exception("save_log 未预期异常: %s", exc)
        except Exception:
            pass
        _notify_error(on_error, f"save_log 未预期异常: {exc}")
        return False


# 便捷别名（可选），便于 `from ... import save_log` 使用
__all__ = ["save_log"]