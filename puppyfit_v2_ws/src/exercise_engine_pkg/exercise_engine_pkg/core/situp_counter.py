"""
:brief 仰卧起坐计数器模块
:desc 实现了仰卧起坐计数的核心算法，将C++版本移植到Python
:author slt&zxh
:date 2026/03/03
:version 1.0.0
"""

from enum import Enum


class SitState(Enum):
    """
    :brief 坐姿方向枚举
    :desc 定义用户相对于相机的方向
    """
    UNKNOWN = 0  # 未知方向
    LEFT = 1     # 左侧
    RIGHT = 2    # 右侧


class State(Enum):
    """
    :brief 动作状态枚举
    :desc 定义仰卧起坐的动作状态
    """
    DOWN = 0  # 躺下状态
    UP = 1    # 坐起状态


class SitUpCounter:
    """
    :brief 仰卧起坐计数器类
    :desc 用于检测和计数用户的仰卧起坐动作
    """

    def __init__(self):
        """
        :brief 构造函数
        :desc 初始化仰卧起坐计数器的状态和参数
        """
        self.counter = 0           # 仰卧起坐计数
        self.current_state = State.DOWN  # 当前状态：躺下
        self.sit_state = SitState.UNKNOWN  # 坐姿方向：未知

        # 配置参数
        self.swap_UP = 0.0         # 坐起判定阈值
        self.swap_DOWN = 0.0       # 躺下判定阈值
        self.MOTION_FRAMES = 3     # 连续运动帧数判定动作
        self.INIT_LENGTH = 4       # 初始化所需的帧数
        self.UP_angle = 0.42       # 坐起角度阈值 (cos 65°)
        self.DOWN_angle = 0.87    # 躺下角度阈值 (cos 30°)
        self.init_angle = 0.005   # 初始化时的多次判断的差值阈值

        # 状态计数缓冲
        self.up_count = 0          # 坐起动作计数
        self.down_count = 0        # 躺下动作计数
        self.init_count = 0        # 初始化计数
        self.init_state = False    # 初始化状态

    def get_init_state(self):
        """
        :brief 获取初始化状态
        :desc 返回计数器是否已经初始化完成
        :return: 初始化状态 (bool)
        """
        return self.init_state

    def process_init(self, left_shoulder, right_shoulder, left_hip, right_hip):
        """
        :brief 初始化计数器
        :desc 根据肩部和髋部的关键点计算初始位置和阈值
        :param left_shoulder: 左肩关键点 {'x': float, 'y': float, 'visibility': float}
        :param right_shoulder: 右肩关键点
        :param left_hip: 左髋关键点
        :param right_hip: 右髋关键点
        """
        # 计算中点坐标
        shoulder_count = 0
        shoulder_x = 0.0
        hip_count = 0
        hip_x = 0.0

        if left_shoulder['visibility'] > 0.5:
            shoulder_x += left_shoulder['x']
            shoulder_count += 1
        if right_shoulder['visibility'] > 0.5:
            shoulder_x += right_shoulder['x']
            shoulder_count += 1
        if left_hip['visibility'] > 0.5:
            hip_x += left_hip['x']
            hip_count += 1
        if right_hip['visibility'] > 0.5:
            hip_x += right_hip['x']
            hip_count += 1

        if shoulder_count == 0 or hip_count == 0:
            return

        # 计算中点坐标平均值
        shoulder_x /= shoulder_count
        hip_x /= hip_count

        # 确定坐姿方向
        if shoulder_x - hip_x > 0:
            self.sit_state = SitState.RIGHT
        else:
            self.sit_state = SitState.LEFT

        # 计算阈值
        if self.sit_state == SitState.RIGHT:
            length = shoulder_x - hip_x
            swap_up = (length * self.UP_angle) + hip_x
            swap_down = (length * self.DOWN_angle) + hip_x
        else:
            length = hip_x - shoulder_x
            swap_up = hip_x - (length * self.UP_angle)
            swap_down = hip_x - (length * self.DOWN_angle)

        if self.init_count == 0:
            self.swap_UP = swap_up
            self.swap_DOWN = swap_down
            self.init_count += 1
            return
        else:
            # if (abs(self.swap_UP - swap_up * self.init_count) < self.init_angle and
            #         abs(self.swap_DOWN - swap_down * self.init_count) < self.init_angle):
            # 计算历史平均值
            avg_swap_up = self.swap_UP / self.init_count
            avg_swap_down = self.swap_DOWN / self.init_count
            # 用当前帧的值和历史平均值进行比较
            if (abs(avg_swap_up - swap_up) < self.init_angle and
                    abs(avg_swap_down - swap_down) < self.init_angle):
                self.swap_UP += swap_up
                self.swap_DOWN += swap_down
                self.init_count += 1
                if self.init_count >= self.INIT_LENGTH:
                    self.swap_UP /= self.init_count
                    self.swap_DOWN /= self.init_count
                    self.counter = 0
                    self.current_state = State.DOWN
                    self.up_count = 0
                    self.down_count = 0
                    self.init_count = 0
                    self.init_state = True
                    return
                return
            else:
                self.swap_UP = 0.0
                self.swap_DOWN = 0.0
                self.init_count = 0
                return

    def process_frame(self, left_shoulder, right_shoulder):
        """
        :brief 处理每一帧的姿态数据
        :desc 根据肩部关键点的位置变化进行仰卧起坐计数
        :param left_shoulder: 左肩关键点
        :param right_shoulder: 右肩关键点
        """
        # 计算中点坐标
        shoulder_count = 0
        shoulder_x = 0.0

        if left_shoulder['visibility'] > 0.5:
            shoulder_x += left_shoulder['x']
            shoulder_count += 1
        if right_shoulder['visibility'] > 0.5:
            shoulder_x += right_shoulder['x']
            shoulder_count += 1

        if shoulder_count == 0:
            return

        shoulder_x /= shoulder_count

        # 状态机逻辑
        if self.sit_state == SitState.RIGHT:
            self._process_right_state(shoulder_x)
        elif self.sit_state == SitState.LEFT:
            self._process_left_state(shoulder_x)

    def _process_right_state(self, shoulder_x):
        """
        :brief 处理右侧坐姿的状态机
        :desc 用户面向右侧时的状态转换逻辑
        :param shoulder_x: 肩部X坐标
        """
        if self.current_state == State.DOWN:
            if shoulder_x <= self.swap_UP:
                self.up_count += 1
                if self.up_count >= self.MOTION_FRAMES:
                    self.current_state = State.UP
                    self.up_count = 0
                    self.counter += 1
            else:
                self.up_count = 0
        elif self.current_state == State.UP:
            if shoulder_x >= self.swap_DOWN:
                self.down_count += 1
                if self.down_count >= self.MOTION_FRAMES:
                    self.current_state = State.DOWN
                    self.down_count = 0
            else:
                self.down_count = 0

    def _process_left_state(self, shoulder_x):
        """
        :brief 处理左侧坐姿的状态机
        :desc 用户面向左侧时的状态转换逻辑
        :param shoulder_x: 肩部X坐标
        """
        if self.current_state == State.DOWN:
            if shoulder_x >= self.swap_UP:
                self.up_count += 1
                if self.up_count >= self.MOTION_FRAMES:
                    self.current_state = State.UP
                    self.up_count = 0
                    self.counter += 1
            else:
                self.up_count = 0
        elif self.current_state == State.UP:
            if shoulder_x <= self.swap_DOWN:
                self.down_count += 1
                if self.down_count >= self.MOTION_FRAMES:
                    self.current_state = State.DOWN
                    self.down_count = 0
            else:
                self.down_count = 0

    def get_count(self):
        """
        :brief 获取当前计数
        :desc 返回当前的仰卧起坐次数
        :return: 仰卧起坐计数 (int)
        """
        return self.counter

    def reset_count(self):
        """
        :brief 重置计数器
        :desc 将计数器和状态重置为初始状态
        """
        self.swap_UP = 0.0
        self.swap_DOWN = 0.0
        self.counter = 0
        self.current_state = State.DOWN
        self.up_count = 0
        self.down_count = 0
        self.init_count = 0
        self.sit_state = SitState.UNKNOWN
        self.init_state = False

    def get_direction(self):
        """
        :brief 获取坐姿方向
        :desc 返回用户相对于相机的方向
        :return: 方向字符串 ("LEFT"/"RIGHT"/"UNKNOWN")
        """
        if self.sit_state == SitState.LEFT:
            return "LEFT"
        elif self.sit_state == SitState.RIGHT:
            return "RIGHT"
        return "UNKNOWN"

    def get_state_string(self):
        """
        :brief 获取状态字符串
        :desc 返回当前动作状态的字符串表示
        :return: 状态字符串 ("DOWN"/"UP")
        """
        return "UP" if self.current_state == State.UP else "DOWN"
