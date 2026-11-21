#!/usr/bin/env python3
# encoding: utf-8
'''
:brief 动作组执行：从 SQLite 动作组文件读帧，驱动舵机或坐标控制
:desc
    支持按脉宽帧或足端坐标帧执行；可循环、指定次数或在线切换动作组；
    通过 runActionGroup/stopActionGroup 与后台线程 online_thread_run_acting 协作。

:author large_models
:date 2024/11
:version 1.0.0
'''

import os
import time
import threading
import sqlite3 as sql
import numpy as np
import sys


from servo_controller import setServoPulse

from PuppyInstantiate import PuppyInstantiate as puppy

_root = os.path.dirname(os.path.abspath(__file__))
action_group_path = os.path.join(_root, 'ActionGroups') + os.sep
runningAction = False
stopRunning = False
online_action_num = None
online_action_times = -1
update_ok = False
action_group_finish = True


def runActionGroup(num, wait = False):
    '''
    :brief 启动指定动作组（异步或阻塞等待结束）
    :param num: 动作组文件名（不含路径）或路径
    :param wait: True 时阻塞直至动作组执行完或超时（约 30s）
    '''
    global runningAction
    threading.Thread(target=runAction, args=(num, )).start()
    if wait == False:return
    
    t = time.time() # 等待动作组做结束(wait for the action group to finish)
    time.sleep(0.02)
    while time.time() - t < 30:#超时强制跳出(force exit due to timeout)
        time.sleep(0.001)
        if runningAction == False:
            break
        

def stopActionGroup():
    '''停止当前动作组并清空在线动作状态'''
    global stopRunning, online_action_num, online_action_times, update_ok
    update_ok = False
    stopRunning = True
    online_action_num = None
    online_action_times = -1
    time.sleep(0.1)

def stop_servo():
    '''预留：停止总线舵机（当前实现为空）'''
    for i in range(16):
        pass
        # stopBusServo(i+1) 

def action_finish():
    '''
    :brief 返回当前是否处于“动作组已执行完”状态
    :return: True 表示已结束，False 表示正在执行
    '''
    global action_group_finish
    return action_group_finish  

def runAction(actNum):
    '''
    :brief 运行动作组（内部使用，无法通过 stop 信号中断单次 runAction）
    :param actNum: 动作组名字或路径，字符串类型
    :desc 从 SQLite 读帧，按脉宽或足端坐标驱动 puppy 舵机，直至读完或 stopRunning 为 True
    '''
    global runningAction
    global stopRunning
    global online_action_times
    if actNum is None:
        return
    actNum = action_group_path + actNum
    stopRunning = False
    if os.path.exists(actNum) is True:
        if runningAction is False:
            runningAction = True
            ag = sql.connect(actNum)
            cu = ag.cursor()
            cu.execute("select * from ActionGroup")

            puppy.servo_force_run()
            time.sleep(0.01)
            while True:
                act = cu.fetchone()
                if stopRunning is True:
                    stopRunning = False                   
                    break
                if act is not None:
                    if type(act[2]) is int:
                        for i in range(0, len(act)-2, 1):
                            setServoPulse(i+1, act[2 + i], act[1])
                                
                    elif type(act[2]) is float:
                        rotated_foot_locations = np.zeros(12)
                        for i in range(0, len(act)-2):
                            value = act[i+2]
                            rotated_foot_locations[i] = float(value)
                        rotated_foot_locations = rotated_foot_locations.reshape(4,3)
                        rotated_foot_locations = rotated_foot_locations.T
                        rotated_foot_locations = rotated_foot_locations/100
                        joint_angles = puppy.fourLegsRelativeCoordControl(rotated_foot_locations)
                        
                        puppy.sendServoAngle(joint_angles, act[1])#, force_execute = True
                        

                    time.sleep(float(act[1])/1000.0)
                else:   # 运行完才退出(exit only after completion of the execution)
                    break

            runningAction = False
            cu.close()
            ag.close()
    else:
        runningAction = False
        print("未能找到动作组文件")

def online_thread_run_acting():
    '''
    :brief 后台线程：根据 online_action_num/online_action_times 与 update_ok 循环执行或空载
    :desc 用于 PuppyPi 等界面“在线”切换动作组与运行次数
    '''
    global online_action_times, online_action_num, update_ok, action_group_finish
    while True:
        if update_ok:
            if online_action_times == 0:
                # 无限次运行(run indefinitely)
                if action_group_finish:
                    action_group_finish = False
                runAction(online_action_num)                
            elif online_action_times > 0:
                # 有次数运行(run for a specified number of times)
                if action_group_finish:
                    action_group_finish = False
                runAction(online_action_num)
                online_action_times -= 1    # 运行完成后，进入空载(enter idle state after execution)
                if online_action_times == 0:
                    online_action_times = -1
            else:
                # 空载(no load)
                if not action_group_finish:
                    action_group_finish = True
                time.sleep(0.001)
        else:
            if not action_group_finish:
                action_group_finish = True
            time.sleep(0.001)
            
def start_action_thread():
    '''启动动作组在线执行后台线程（守护线程）'''
    th1 = threading.Thread(target=online_thread_run_acting)
    th1.setDaemon(True)  # 设置为后台线程，这里默认是True(set as background thread, by default, it is True here)
    th1.start()
    
def change_action_value(actNum, actTimes):
    '''
    :brief 设置在线动作组与运行次数，触发后台线程执行
    :param actNum: 动作组名
    :param actTimes: 运行次数，0 表示无限循环
    '''
    global online_action_times, online_action_num, update_ok, stopRunning, action_group_finish
    
    if action_group_finish:
        online_action_times = actTimes
        online_action_num = actNum
        stopRunning = False
        update_ok = True
