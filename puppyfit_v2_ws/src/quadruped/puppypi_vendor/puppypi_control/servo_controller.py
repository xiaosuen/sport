#!/usr/bin/env python3
# encoding: utf-8
'''
:brief 舵机控制单例入口（PWM 舵机脉宽与偏差）
:desc
    创建 Board 与 PWMServoControl，为四足/机械臂提供 setServoPulse、偏差读写等接口；
    启动时对部分舵机 ID 设置脉宽上下限阈值。

:author large_models
:date 2026/03/30
:version 1.1.0
:history
    1.1.0 - 2026/03/30
        :brief 新增 setServoPulseBatch，转调 PWMServoControl.setPulseBatch
    1.0.0 - 2024/11
        :brief 初始版本：Board/PWMServoControl 单例与 setServoPulse
'''

import threading, os, time
from ros_robot_controller_sdk import Board
from pwm_servo_control import PWMServoControl

board = Board()
#board.enable_reception()
psc = PWMServoControl(board)

psc.setThreshold(2,650,2300)
psc.setThreshold(6,650,2300)

psc.setThreshold(4,700,2350)
psc.setThreshold(8,700,2350)

def getServoDeviation(id):
    '''
    :brief 获取指定舵机的偏差值
    :param id: 舵机 ID
    :return: 偏差值
    '''
    return psc.getDeviation(id)

def setServoPulse(id, pulse, use_time):
    '''
    :brief 设置舵机脉宽与运动时间
    :param id: 舵机 ID
    :param pulse: 脉宽（约 500–2500）
    :param use_time: 运动时间（毫秒）
    '''
    psc.setPulse(id, pulse, use_time)


def setServoPulseBatch(id_pulse_list, use_time):
    '''
    :brief 多舵机同一时长同步到位（毫秒）
    :param id_pulse_list: [[id, pulse], ...]
    '''
    psc.setPulseBatch(id_pulse_list, use_time)


def setServoDeviation(id ,dev):
    '''
    :brief 设置舵机偏差并写入板子
    :param id: 舵机 ID
    :param dev: 偏差值（-100–100）
    '''
    psc.setDeviation(id, dev)

def saveServoDeviation():
    '''将当前偏差保存到 servo_deviation.json'''
    psc.saveDeviation()

def unloadServo(id):
    '''
    :brief 舵机掉电（脉宽置 0）
    :param id: 舵机 ID
    '''
    psc.unload(id)

def updatePulse(id):
    '''
    :brief 从板子回读舵机当前脉宽并更新内部缓存
    :param id: 舵机 ID，-1 表示全部
    '''
    psc.updatePulse(id)

def enable_reception(enable=True):
    '''
    :brief 开启/关闭扩展板数据接收（按键、IMU 等上报）
    :param enable: True 开启，False 关闭
    :desc 关闭时会通过 rostopic 通知 ros_robot_controller，再操作 Board
    '''
    if enable:
        board.enable_reception(not enable)
        time.sleep(1)
        threading.Thread(target=os.system, args=("/bin/zsh -c \'source $HOME/armpi_fpv/src/armpi_fpv_bringup/scripts/source_env.bash && rostopic pub /ros_robot_controller/enable_reception std_msgs/Bool \"data: true\"\'",), daemon=True).start()
        time.sleep(1)
    else:
        threading.Thread(target=os.system, args=("/bin/zsh -c \'source $HOME/armpi_fpv/src/armpi_fpv_bringup/scripts/source_env.bash && rostopic pub /ros_robot_controller/enable_reception std_msgs/Bool \"data: false\"\'",), daemon=True).start()
        time.sleep(3)
        board.enable_reception(not enable)
        time.sleep(1)

