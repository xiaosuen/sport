#!/usr/bin/python3
# coding=utf8
# Author: hiwonder
"""
逆运动学（IK）快速验证脚本（非 ROS2 节点）。

功能：
- 创建 `HiwonderPuppy` 对象（不实际下发舵机脉宽：setServoPulse=None）
- 构造四足足端相对坐标 `foot_locations`（单位 cm -> 转为 m）
- 调用 `fourLegsRelativeCoordControl()` 计算关节角度并打印（度）

用途：
- 验证 IK 计算链路是否正常
- 调试足端坐标系/单位换算
"""

import os, sys, time
import numpy as np

sys.path.append('/home/ubuntu/software/puppypi_control/')
from servo_controller import setServoPulse
from puppy_kinematics import HiwonderPuppy, PWMServoParams
puppy = HiwonderPuppy(setServoPulse=None, servoParams=PWMServoParams(), dof='8')

foot_locations = np.array([ [-1,  -1,  -1,   -1], # X
                            [ 0,    0,   0,    0], # Y
                            [-10,   -10,  -10,   -10]  # Z
                            ])


foot_locations = foot_locations / 100

joint_angles = puppy.fourLegsRelativeCoordControl(foot_locations)


print("Servo angles (in degrees):")
print(joint_angles * 57.3)


while True:
    time.sleep(0.001)

