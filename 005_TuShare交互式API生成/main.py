#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TuShare API 函数生成器 - 主入口
版本: 1.0.0
"""
import logging
from controller import WorkflowController

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    controller = WorkflowController()
    controller.start()