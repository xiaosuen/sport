#!/usr/bin/env python3
# encoding: utf-8
'''
:brief PWM 舵机控制：脉宽、阈值、偏差与板子通信
:desc
    封装 Board 的 PWM 舵机指令，支持从 servo_deviation.json 加载/保存偏差，
    脉宽限制在 500–2500 及每舵机可配置的 min/max 阈值内。

:author large_models
:date 2026/03/30
:version 1.1.0
:history
    1.1.0 - 2026/03/30
        :brief 新增 setPulseBatch：单帧 pwm_servo_set_position 多舵机同步运动，供 puppy_control 启动姿态使用
    1.0.0 - 2024/11
        :brief 初始版本：脉宽、阈值、偏差与 Board 通信
'''

import os
import sys
import time
import json
import threading
from ros_robot_controller_sdk import *

if sys.version_info.major == 2:
    print('Please run this program with python3!')
    sys.exit(0)

class PWMServoControl:
    '''
    :brief PWM 舵机控制类：脉宽设置、偏差与阈值管理，通过 Board 发指令
    '''
    def __init__(self, board, time_out=100):
        '''
        :brief 初始化：从 servo_deviation.json 加载偏差并写入板子
        :param board: 幻尔扩展板 Board 实例
        :param time_out: 读舵机应答超时（毫秒）
        '''
        self.board = board # Board 实例
        self.time_out = time_out # 读舵机应答超时（毫秒）
        _root = os.path.dirname(os.path.abspath(__file__))
        self.pwm_servo_deviation_path = os.path.join(_root, 'servo_deviation.json')
        self.pwm_servo_duty_now = {} # 当前脉宽
        self.pwm_servo_threshold = {} # 阈值
        self.pwm_servo_deviation = {} # 偏差
        self.lock = threading.Lock() # 锁
        self.setDevBySelf = False # 是否设置偏差

        for id in range(1,12):
            self.pwm_servo_duty_now[id] = 0 # 当前脉宽
            self.pwm_servo_threshold[id] = {'min':500,'max':2500} # 阈值
            self.pwm_servo_deviation[id] = 0 # 偏差

        try:
            with open(self.pwm_servo_deviation_path, 'r') as f:
                d = json.load(f) # 加载偏差
                for key in d:
                    self.pwm_servo_deviation[int(key)] = d[key] # 加载偏差
                    self.board.pwm_servo_set_offset(int(key),d[key]) # 设置偏差
                    
        except:
            with open(self.pwm_servo_deviation_path, 'w') as f: # 创建偏差文件
                json.dump(self.pwm_servo_deviation, f) # 保存偏差
        
    def setPulse(self, servo_id, pulse, use_time):
        '''
        :brief 设置单个舵机脉宽与运动时间，并做范围与阈值裁剪
        :param servo_id: 舵机 ID
        :param pulse: 目标脉宽（500–2500）
        :param use_time: 运动时间（毫秒，0–30000）
        :return: 越界时返回 False，否则无返回值
        '''
        if pulse < 500 or pulse > 2500:
            print("Angle is out of range")
            return False
        if pulse < self.pwm_servo_threshold[servo_id]['min']:pulse = self.pwm_servo_threshold[servo_id]['min']
        if pulse > self.pwm_servo_threshold[servo_id]['max']:pulse = self.pwm_servo_threshold[servo_id]['max']
        if use_time < 0:use_time = 0
        if use_time > 30000:use_time = 30000
          
        if pulse < 500:pulse=500
        elif pulse > 2500:pulse = 2500
        self.pwm_servo_duty_now[servo_id] = pulse
        self.board.pwm_servo_set_position(use_time/1000, [[servo_id, pulse]])

    def setPulseBatch(self, id_pulse_list, use_time):
        '''
        :brief 多路 PWM 舵机同一时长同步运动（单条 PACKET_FUNC_PWM_SERVO，避免逐舵机分批发导致身体扭动）
        :param id_pulse_list: [[servo_id, pulse], ...]，后者为未裁剪脉宽
        :param use_time: 运动时间（毫秒，0–30000）
        '''
        if not id_pulse_list:
            return
        if use_time < 0:
            use_time = 0
        if use_time > 30000:
            use_time = 30000
        duration_sec = use_time / 1000.0
        positions = []
        for item in id_pulse_list:
            if len(item) < 2:
                continue
            servo_id = int(item[0])
            pulse = item[1]
            if pulse < 500 or pulse > 2500:
                print("Angle is out of range")
                continue
            if pulse < self.pwm_servo_threshold[servo_id]['min']:
                pulse = self.pwm_servo_threshold[servo_id]['min']
            if pulse > self.pwm_servo_threshold[servo_id]['max']:
                pulse = self.pwm_servo_threshold[servo_id]['max']
            if pulse < 500:
                pulse = 500
            elif pulse > 2500:
                pulse = 2500
            pulse = int(round(pulse))
            positions.append([servo_id, pulse])
        if not positions:
            return
        self.board.pwm_servo_set_position(duration_sec, positions)
        for servo_id, pulse in positions:
            self.pwm_servo_duty_now[servo_id] = pulse

    def setThreshold(self, servo_id, min,max):
        '''
        :brief 设置指定舵机的脉宽上下限
        :param servo_id: 舵机 ID
        :param min: 最小脉宽（>=500）
        :param max: 最大脉宽（<=2500）
        :return: 越界返回 False
        '''
        if min < 500 or max > 2500:
            return False
        self.pwm_servo_threshold[servo_id] = {'min':min,'max':max}

    def setDeviation(self, servo_id, d):
        '''
        :brief 设置舵机偏差并下发到板子
        :param servo_id: 舵机 ID
        :param d: 偏差值（-100–100）
        '''
        if d >= -100 and d <= 100:
            with self.lock:
                self.setDevBySelf = True
                self.pwm_servo_deviation[servo_id] = d
                self.board.pwm_servo_set_offset(servo_id,d)
        else:print("Deviation is out of range")
    
    def getDeviation(self, servo_id):
        '''
        :brief 获取指定舵机当前偏差值
        :param servo_id: 舵机 ID
        :return: 偏差值
        '''
        return self.pwm_servo_deviation[servo_id]

    def saveDeviation(self):
        '''将当前所有舵机偏差写入 servo_deviation.json'''
        with self.lock:
            with open(self.pwm_servo_deviation_path, 'w') as f:
                json.dump(self.pwm_servo_deviation, f)
    
    def updatePulse(self, servo_id):
        '''
        :brief 从板子回读舵机当前脉宽，减去偏差后更新 pwm_servo_duty_now
        :param servo_id: 舵机 ID，-1 表示 1–11 全部回读
        '''
        if servo_id == -1:# all ids
            for id in range(1,12):
                try:
                    self.pwm_servo_duty_now[id] = self.board.pwm_servo_read_position(id) - self.pwm_servo_deviation[id]
                except:
                    self.pwm_servo_duty_now[id] = 0
        else:
            try:
                self.pwm_servo_duty_now[servo_id] = self.board.pwm_servo_read_position(servo_id) - self.pwm_servo_deviation[servo_id]
            except:
                self.pwm_servo_duty_now[servo_id] = 0

    def unload(self, servo_id):
        '''
        :brief 舵机掉电：将指定舵机脉宽置 0
        :param servo_id: 舵机 ID
        '''
        self.board.pwm_servo_set_position(0.01, [[servo_id, 0]])


    

