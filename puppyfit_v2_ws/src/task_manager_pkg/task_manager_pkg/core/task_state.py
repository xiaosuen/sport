"""
:brief 任务状态枚举
:desc 定义任务状态
:author slt
:date 2026/03/28
:version 1.0.0
"""
from enum import Enum

class TaskState(Enum):
    IDLE = "IDLE" # 空闲状态
    WAITING_USER = "WAITING_USER" # 等待用户状态
    READY = "READY" # 准备状态
    RUNNING = "RUNNING" # 运行状态
    FINISHED = "FINISHED" # 完成状态