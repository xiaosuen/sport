#!/usr/bin/env python3
# encoding: utf-8
'''
:brief 四足 Puppy 单例：HiwonderPuppy 与 setServoPulse 绑定
:desc
    供动作组、ROS2 等模块直接 import PuppyInstantiate 使用同一套舵机与运动学实例。

:author large_models
:date 2024/11
:version 1.0.0
'''

from servo_controller import setServoPulse

from puppy_kinematics import HiwonderPuppy, PWMServoParams

PuppyInstantiate = HiwonderPuppy(setServoPulse = setServoPulse, servoParams = PWMServoParams(), dof='8')

