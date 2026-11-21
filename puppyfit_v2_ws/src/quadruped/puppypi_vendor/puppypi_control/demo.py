#!/usr/bin/env python3
# encoding: utf-8
'''
:brief 扩展板 PWM 舵机简单演示：设置脉宽与偏置并回读
:desc 打开 Board、使能接收，对 1 号舵机设置 offset 与位置后打印回读值。

:author large_models
:date 2024/11
:version 1.0.0
'''

from ros_robot_controller_sdk import Board
import time

board = Board()
board.enable_reception()

board.pwm_servo_set_offset(1,0)
board.pwm_servo_set_position(0.1,[[1,499]])
time.sleep(0.5)

print(board.pwm_servo_read_offset(1))
print(board.pwm_servo_read_position(1))
