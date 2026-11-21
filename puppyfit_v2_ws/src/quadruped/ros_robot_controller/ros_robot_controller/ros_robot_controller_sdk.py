#!/usr/bin/env python3
# encoding: utf-8
"""
:brief STM32 机器人控制板串口通讯 Python SDK
:desc 解析固定帧格式（0xAA 0x55 + 功能码 + 长度 + 数据 + CRC8），后台线程收包并按功能码分发到各队列；提供 LED、蜂鸣器、电机、PWM/总线舵机、OLED、RGB 等下发接口与 IMU、按键、手柄、SBUS、电池等读取接口
:author Aiden（沿用原包注释）
:date 2023/08/28
:version 1.0.0
:history
    - 1.0.0 2023/08/28
        :brief 初始 SDK（Board 与协议解析）
"""

import enum
import time
import queue
import struct
import serial
import threading

class PacketControllerState(enum.IntEnum):
    """
    :brief 串口帧解析状态机枚举
    :desc 单字节流按序匹配帧头 0xAA 0x55，再读功能码、长度、载荷与 CRC8；与协议 0xAA 0x55 + Function + Length + Data + Checksum 对应
    """

    PACKET_CONTROLLER_STATE_STARTBYTE1 = 0
    PACKET_CONTROLLER_STATE_STARTBYTE2 = 1
    PACKET_CONTROLLER_STATE_LENGTH = 2
    PACKET_CONTROLLER_STATE_FUNCTION = 3
    PACKET_CONTROLLER_STATE_ID = 4
    PACKET_CONTROLLER_STATE_DATA = 5
    PACKET_CONTROLLER_STATE_CHECKSUM = 6


class PacketFunction(enum.IntEnum):
    """
    :brief 串口协议功能码
    :desc 与固件侧 PACKET_FUNC_* 一致，用于区分 SYS/LED/电机/舵机等数据通道
    """

    PACKET_FUNC_SYS = 0  # 系统/电池等
    PACKET_FUNC_LED = 1  # LED
    PACKET_FUNC_BUZZER = 2  # 蜂鸣器
    PACKET_FUNC_MOTOR = 3  # 电机
    PACKET_FUNC_PWM_SERVO = 4  # PWM 舵机（板载口 1–4 由里到外）
    PACKET_FUNC_BUS_SERVO = 5  # 总线舵机
    PACKET_FUNC_KEY = 6  # 按键
    PACKET_FUNC_IMU = 7  # IMU
    PACKET_FUNC_GAMEPAD = 8  # 无线手柄
    PACKET_FUNC_SBUS = 9  # SBUS 遥控接收
    PACKET_FUNC_OLED = 10  # OLED 显示
    PACKET_FUNC_RGB = 11  # RGB 灯
    PACKET_FUNC_NONE = 12  # 非法/结束边界


class PacketReportKeyEvents(enum.IntEnum):
    """
    :brief 板载按键事件类型（位标志）
    :desc 与固件上报的按键事件字节对应；节点侧将部分事件映射为按下/松开语义
    """

    KEY_EVENT_PRESSED = 0x01
    KEY_EVENT_LONGPRESS = 0x02
    KEY_EVENT_LONGPRESS_REPEAT = 0x04
    KEY_EVENT_RELEASE_FROM_LP = 0x08
    KEY_EVENT_RELEASE_FROM_SP = 0x10
    KEY_EVENT_CLICK = 0x20
    KEY_EVENT_DOUBLE_CLICK= 0x40
    KEY_EVENT_TRIPLE_CLICK = 0x80


# CRC8 查表，用于帧尾校验（与固件一致）
crc8_table = [
    0, 94, 188, 226, 97, 63, 221, 131, 194, 156, 126, 32, 163, 253, 31, 65,
    157, 195, 33, 127, 252, 162, 64, 30, 95, 1, 227, 189, 62, 96, 130, 220,
    35, 125, 159, 193, 66, 28, 254, 160, 225, 191, 93, 3, 128, 222, 60, 98,
    190, 224, 2, 92, 223, 129, 99, 61, 124, 34, 192, 158, 29, 67, 161, 255,
    70, 24, 250, 164, 39, 121, 155, 197, 132, 218, 56, 102, 229, 187, 89, 7,
    219, 133, 103, 57, 186, 228, 6, 88, 25, 71, 165, 251, 120, 38, 196, 154,
    101, 59, 217, 135, 4, 90, 184, 230, 167, 249, 27, 69, 198, 152, 122, 36,
    248, 166, 68, 26, 153, 199, 37, 123, 58, 100, 134, 216, 91, 5, 231, 185,
    140, 210, 48, 110, 237, 179, 81, 15, 78, 16, 242, 172, 47, 113, 147, 205,
    17, 79, 173, 243, 112, 46, 204, 146, 211, 141, 111, 49, 178, 236, 14, 80,
    175, 241, 19, 77, 206, 144, 114, 44, 109, 51, 209, 143, 12, 82, 176, 238,
    50, 108, 142, 208, 83, 13, 239, 177, 240, 174, 76, 18, 145, 207, 45, 115,
    202, 148, 118, 40, 171, 245, 23, 73, 8, 86, 180, 234, 105, 55, 213, 139,
    87, 9, 235, 181, 54, 104, 138, 212, 149, 203, 41, 119, 244, 170, 72, 22,
    233, 183, 85, 11, 136, 214, 52, 106, 43, 117, 151, 201, 74, 20, 246, 168,
    116, 42, 200, 150, 21, 75, 169, 247, 182, 232, 10, 84, 215, 137, 107, 53
]


def checksum_crc8(data):
    """
    :brief 计算 CRC8 校验字节
    :param data: 待校验字节序列（通常为 function+length+payload）
    :return: 0~255 的校验值
    """
    check = 0
    for b in data:
        check = crc8_table[check ^ b]
    return check & 0x00FF


class SBusStatus:
    """
    :brief SBUS 原始解析中间结构
    :desc 保存 16 路通道及扩展位、丢星与 fail_safe 标志，供 get_sbus 归一化到 [-1,1]
    """

    def __init__(self):
        self.channels = [0] * 16
        self.channel_17 = False
        self.channel_18 = False
        self.signal_loss = True
        self.fail_safe = False


class Board:
    """
    :brief 控制板串口访问类
    :desc 打开串口、启动 recv_task 收包线程，将各功能上报放入定长队列；发送侧通过 buf_write 组帧写出
    """

    # 手柄按键位掩码 -> 与 ROS Joy axes/buttons 下标映射用
    buttons_map = {
            'GAMEPAD_BUTTON_MASK_L2':        0x0001,
            'GAMEPAD_BUTTON_MASK_R2':        0x0002,
            'GAMEPAD_BUTTON_MASK_SELECT':    0x0004,
            'GAMEPAD_BUTTON_MASK_START':     0x0008,
            'GAMEPAD_BUTTON_MASK_L3':        0x0020,
            'GAMEPAD_BUTTON_MASK_R3':        0x0040,
            'GAMEPAD_BUTTON_MASK_CROSS':     0x0100,
            'GAMEPAD_BUTTON_MASK_CIRCLE':    0x0200,
            'GAMEPAD_BUTTON_MASK_SQUARE':    0x0800,
            'GAMEPAD_BUTTON_MASK_TRIANGLE':  0x1000,
            'GAMEPAD_BUTTON_MASK_L1':        0x4000,
            'GAMEPAD_BUTTON_MASK_R1':        0x8000
    }

    def __init__(self, device="/dev/rrc", baudrate=1000000, timeout=5):
        """
        :brief 打开串口并启动接收线程
        :param device: 串口设备路径，默认 /dev/rrc
        :param baudrate: 波特率，默认 1Mbps
        :param timeout: 串口读超时（秒）
        """
        self.enable_recv = False
        self.frame = []
        self.recv_count = 0

        self.port = serial.Serial(None, baudrate, timeout=timeout)
        self.port.rts = False
        self.port.dtr = False
        self.port.setPort(device)
        self.port.open()

        self.state = PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE1
        self.servo_read_lock = threading.Lock()
        self.pwm_servo_read_lock = threading.Lock()

        # 各功能最新一帧上报（maxsize=1，新数据覆盖旧数据语义）
        self.sys_queue = queue.Queue(maxsize=1)
        self.bus_servo_queue = queue.Queue(maxsize=1)
        self.pwm_servo_queue = queue.Queue(maxsize=1)
        self.key_queue = queue.Queue(maxsize=1)
        self.imu_queue = queue.Queue(maxsize=1)
        self.gamepad_queue = queue.Queue(maxsize=1)
        self.sbus_queue = queue.Queue(maxsize=1)

        self.parsers = {
            PacketFunction.PACKET_FUNC_SYS: self.packet_report_sys,
            PacketFunction.PACKET_FUNC_KEY: self.packet_report_key,
            PacketFunction.PACKET_FUNC_IMU: self.packet_report_imu,
            PacketFunction.PACKET_FUNC_GAMEPAD: self.packet_report_gamepad,
            PacketFunction.PACKET_FUNC_BUS_SERVO: self.packet_report_serial_servo,
            PacketFunction.PACKET_FUNC_SBUS: self.packet_report_sbus,
            PacketFunction.PACKET_FUNC_PWM_SERVO: self.packet_report_pwm_servo
        }

        time.sleep(0.5)
        threading.Thread(target=self.recv_task, daemon=True).start()

    def packet_report_sys(self, data):
        """
        :brief SYS 功能上报入队（如电池电压）
        :param data: 解析后的载荷
        """
        try:
            self.sys_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_key(self, data):
        """
        :brief 按键事件入队
        :param data: 载荷含按键 id 与事件类型
        """
        try:
            self.key_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_imu(self, data):
        """
        :brief IMU 六轴浮点数据入队
        :param data: 6 个 float 小端二进制
        """
        try:
            self.imu_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_gamepad(self, data):
        """
        :brief 无线手柄原始数据入队
        :param data: 固件打包的手柄报告
        """
        try:
            self.gamepad_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_serial_servo(self, data):
        """
        :brief 总线舵机读回/应答入队
        :param data: 舵机子命令应答载荷
        """
        try:
            self.bus_servo_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_pwm_servo(self, data):
        """
        :brief PWM 舵机读回应答入队
        :param data: PWM 舵机子命令应答载荷
        """
        try:
            self.pwm_servo_queue.put_nowait(data)
        except queue.Full:
            pass

    def packet_report_sbus(self, data):
        """
        :brief SBUS 通道数据入队
        :param data: 16 通道及状态字节打包数据
        """
        try:
            self.sbus_queue.put_nowait(data)
        except queue.Full:
            pass

    def get_battery(self):
        """
        :brief 非阻塞读取最近一次电池电压上报
        :desc 需 enable_recv 为 True；sys_queue 中子类型 0x04 为电压值
        :return: 电压（协议约定单位，通常为 mV），无数据或未开启接收时返回 None
        """
        if self.enable_recv:
            try:
                data = self.sys_queue.get(block=False)
                if data[0] == 0x04:
                    return struct.unpack('<H', data[1:])[0]
                else:
                    None
            except queue.Empty:
                return None
        else:
            print('get_battery enable reception first!')
            return None

    def get_button(self):
        """
        :brief 非阻塞读取板载按键状态
        :desc 返回 (key_id, state)：id 1/2 表示按键；state 0 表示单击语义、1 表示按下保持（与 KEY_EVENT 映射相关）
        :return: 元组或 None
        """
        if self.enable_recv:
            try:
                data = self.key_queue.get(block=False)
                key_id = data[0]
                key_event = PacketReportKeyEvents(data[1])
                if key_event == PacketReportKeyEvents.KEY_EVENT_CLICK:
                    return key_id, 0
                elif key_event == PacketReportKeyEvents.KEY_EVENT_PRESSED:
                    return key_id, 1
            except queue.Empty:
                return None
        else:
            print('get_button enable reception first!')
            return None

    def get_imu(self):
        """
        :brief 非阻塞读取 IMU 六轴
        :desc 返回 (ax, ay, az, gx, gy, gz)：加速度为 g，角速度为 deg/s（由 ROS 节点再换算为 SI）
        :return: 6 元组或 None
        """
        if self.enable_recv:
            try:
                # ax, ay, az, gx, gy, gz
                return struct.unpack('<6f', self.imu_queue.get(block=False))
            except queue.Empty:
                return None
        else:
            print('get_imu enable reception first!')
            return None

    def get_gamepad(self):
        """
        :brief 非阻塞读取无线手柄并映射为 Joy 风格
        :desc 返回 (axes, buttons) 两个列表，下标与 ROS sensor_msgs/Joy 常用布局对齐
        :return: (list, list) 或 None
        """
        if self.enable_recv:
            try:
                # buttons, hat, lx, ly, rx, ry
                gamepad_data = struct.unpack("<HB4b", self.gamepad_queue.get(block=False))
                # 'lx', 'ly', 'rx', 'ry', 'r2', 'l2', 'hat_x', 'hat_y'
                axes = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                # 'cross', 'circle', '', 'square', 'triangle', '', 'l1', 'r1', 'l2', 'r2', 'select', 'start', '', 'l3', 'r3', ''
                buttons = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] 
                for b in self.buttons_map:
                    if self.buttons_map[b] & gamepad_data[0]:
                        if b == 'GAMEPAD_BUTTON_MASK_R2':
                            axes[4] = 1.0
                        elif b == 'GAMEPAD_BUTTON_MASK_L2':
                            axes[5] = 1.0
                        elif b == 'GAMEPAD_BUTTON_MASK_CROSS':
                            buttons[0] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_CIRCLE':
                            buttons[1] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_SQUARE':
                            buttons[3] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_TRIANGLE':
                            buttons[4] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_L1':
                            buttons[6] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_R1':
                            buttons[7] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_SELECT':
                            buttons[10] = 1
                        elif b == 'GAMEPAD_BUTTON_MASK_START':
                            buttons[11] = 1
               
                if gamepad_data[2] > 0:
                    axes[0] = -gamepad_data[2] / 127
                elif gamepad_data[2] < 0:
                    axes[0] = -gamepad_data[2] / 128

                if gamepad_data[3] > 0:
                    axes[1] = gamepad_data[3] / 127
                elif gamepad_data[3] < 0:
                    axes[1] = gamepad_data[3] / 128

                if gamepad_data[4] > 0:
                    axes[2] = -gamepad_data[4] / 127
                elif gamepad_data[4] < 0:
                    axes[2] = -gamepad_data[4] / 128

                if gamepad_data[5] > 0:
                    axes[3] = gamepad_data[5] / 127
                elif gamepad_data[5] < 0:
                    axes[3] = gamepad_data[5] / 128
            
                if gamepad_data[1] == 9:
                    axes[6] = 1.0
                elif gamepad_data[1] == 13:
                    axes[6] = -1.0
                
                if gamepad_data[1] == 11:
                    axes[7] = -1.0
                elif gamepad_data[1] == 15:
                    axes[7] = 1.0
                return axes, buttons
            except queue.Empty:
                return None
        else:
            print('get_gamepad enable reception first!')
            return None

    def get_sbus(self):
        """
        :brief 非阻塞读取 SBUS 并归一化通道
        :desc 丢星时返回中性占位；正常时将脉宽映射到约 [-1, 1]
        :return: 16 个 float 的列表或 None
        """
        if self.enable_recv:
            try:
                sbus_data = self.sbus_queue.get(block=False)
                status = SBusStatus()
                *status.channels, ch17, ch18, sig_loss, fail_safe = struct.unpack("<16hBBBB", sbus_data)
                status.channel_17 = ch17 != 0
                status.channel_18 = ch18 != 0
                status.signal_loss = sig_loss != 0
                status.fail_safe = fail_safe != 0
                data = []
                if status.signal_loss:
                    data = 16 * [0.5]
                    data[4] = 0
                    data[5] = 0
                    data[6] = 0
                    data[7] = 0
                else:
                    for i in status.channels:
                        data.append(2*(i - 192)/(1792 - 192) - 1)
                return data
            except queue.Empty:
                return None
        else:
            print('get_sbus enable reception first!')
            return None

    def buf_write(self, func, data):
        """
        :brief 组帧并写入串口
        :desc 格式：0xAA 0x55 | function | len(data) | data... | crc8(function,len,payload)
        :param func: PacketFunction 功能码
        :param data: 可为 list[int] 或 bytes-like，会 extend 进缓冲区
        """
        buf = [0xAA, 0x55, int(func)]
        buf.append(len(data))
        buf.extend(data)
        buf.append(checksum_crc8(bytes(buf[2:])))
        self.port.write(buf)

    def set_led(self, on_time, off_time, repeat=1, led_id=1):
        """
        :brief 设置 LED 闪烁时序
        :param on_time: 点亮时间（秒），内部乘 1000 下发
        :param off_time: 熄灭时间（秒）
        :param repeat: 重复次数
        :param led_id: 灯号
        """
        on_time = int(on_time*1000)
        off_time = int(off_time*1000)
        self.buf_write(PacketFunction.PACKET_FUNC_LED, struct.pack("<BHHH", led_id, on_time, off_time, repeat))

    def set_buzzer(self, freq, on_time, off_time, repeat=1):
        """
        :brief 设置蜂鸣器频率与通断
        :param freq: 频率 Hz
        :param on_time: 响持续时间（秒）
        :param off_time: 停持续时间（秒）
        :param repeat: 重复次数
        """
        on_time = int(on_time*1000)
        off_time = int(off_time*1000)
        self.buf_write(PacketFunction.PACKET_FUNC_BUZZER, struct.pack("<HHHH", freq, on_time, off_time, repeat))

    def set_motor_speed(self, speeds):
        """
        :brief 设置多路电机转速
        :param speeds: [[电机id, rps], ...]；id 在协议中会减 1 下发
        """
        data = [0x01, len(speeds)]
        for i in speeds:
            data.extend(struct.pack("<Bf", int(i[0] - 1), float(i[1])))
        self.buf_write(PacketFunction.PACKET_FUNC_MOTOR, data)

    def set_oled_text(self, line, text):
        """
        :brief 设置 OLED 指定行文本
        :desc 首字节为行号，次字节为 UTF-8 字节长度（协议与固件约定一致）
        :param line: 行索引
        :param text: 字符串内容
        """
        data = [line, len(text)]
        data.extend(bytes(text, encoding='utf-8'))
        self.buf_write(PacketFunction.PACKET_FUNC_OLED, data)

    def set_rgb(self, pixels):
        """
        :brief 设置 RGB 灯珠颜色
        :param pixels: [[id, r, g, b], ...]；id 在协议中会减 1 下发
        """
        data = [0x01, len(pixels), ]
        for index, r, g, b in pixels:
            data.extend(struct.pack("<BBBB", int(index - 1), int(r), int(g), int(b)))
        self.buf_write(PacketFunction.PACKET_FUNC_RGB, data)

    def pwm_servo_set_position(self, duration, positions):
        """
        :brief PWM 舵机同时到位
        :param duration: 运动总时长（秒），内部乘 1000 为 ms
        :param positions: [[舵机id, 脉宽], ...]
        """
        duration = int(duration * 1000)
        data = [0x01, duration & 0xFF, 0xFF & (duration >> 8), len(positions)]
        for i in positions:
            data.extend(struct.pack("<BH", i[0], i[1]))
        self.buf_write(PacketFunction.PACKET_FUNC_PWM_SERVO, data)

    def pwm_servo_set_offset(self, servo_id, offset):
        """
        :brief 设置 PWM 舵机中位偏移
        :param servo_id: 舵机编号
        :param offset: 偏移量（有符号，协议约定单位）
        """
        data = struct.pack("<BBb", 0x07, servo_id, int(offset))
        self.buf_write(PacketFunction.PACKET_FUNC_PWM_SERVO, data)

    def pwm_servo_read_and_unpack(self, servo_id, cmd, unpack):
        """
        :brief PWM 舵机读命令通用封装
        :desc 加锁发送子命令，阻塞等待 pwm_servo_queue 应答后按 unpack 解包返回 info
        :param servo_id: 舵机 id
        :param cmd: 子命令字节
        :param unpack: struct.unpack 格式串
        :return: 解包后的数据字段或 None
        """
        with self.servo_read_lock:
            self.buf_write(PacketFunction.PACKET_FUNC_PWM_SERVO, [cmd, servo_id])
            data = self.pwm_servo_queue.get(block=True)
            servo_id, cmd, info = struct.unpack(unpack, data)
            return info

    def pwm_servo_read_offset(self, servo_id):
        """
        :brief 读取 PWM 舵机偏移
        :param servo_id: 舵机 id
        :return: 偏移值或 None
        """
        return self.pwm_servo_read_and_unpack(servo_id, 0x09, "<BBb")

    def pwm_servo_read_position(self, servo_id):
        """
        :brief 读取 PWM 舵机当前脉宽/位置
        :param servo_id: 舵机 id
        :return: 位置值或 None
        """
        return self.pwm_servo_read_and_unpack(servo_id, 0x05, "<BBH")

    def bus_servo_enable_torque(self, servo_id, enable):
        """
        :brief 总线舵机力矩开关
        :param servo_id: 舵机 id
        :param enable: True 开启，False 关闭
        """
        if enable:
            data = struct.pack("<BB", 0x0B, servo_id)
        else:
            data = struct.pack("<BB", 0x0C, servo_id)
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_set_id(self, servo_id_now, servo_id_new):
        """
        :brief 修改总线舵机 ID
        :param servo_id_now: 当前 id（如扫描用 254）
        :param servo_id_new: 目标 id
        """
        data = struct.pack("<BBB", 0x10, servo_id_now, servo_id_new)
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_set_offset(self, servo_id, offset):
        """
        :brief 设置总线舵机中位偏移
        """
        data = struct.pack("<BBb", 0x20, servo_id, int(offset))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_save_offset(self, servo_id):
        """
        :brief 将偏移写入舵机存储
        """
        data = struct.pack("<BB", 0x24, servo_id)
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_set_angle_limit(self, servo_id, limit):
        """
        :brief 设置总线舵机角度限制
        :param limit: [低限, 高限]
        """
        data = struct.pack("<BBHH", 0x30, servo_id, int(limit[0]), int(limit[1]))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_set_vin_limit(self, servo_id, limit):
        """
        :brief 设置总线舵机供电电压允许范围
        :param limit: [低限, 高限]（协议单位与固件一致）
        """
        data = struct.pack("<BBHH", 0x34, servo_id, int(limit[0]), int(limit[1]))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_set_temp_limit(self, servo_id, limit):
        """
        :brief 设置总线舵机最高工作温度阈值
        """
        data = struct.pack("<BBb", 0x38, servo_id, int(limit))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)
        time.sleep(0.02)

    def bus_servo_stop(self, servo_id):
        """
        :brief 总线舵机立即停止（可一次多路）
        :param servo_id: id 列表
        """
        data = [0x03, len(servo_id)] 
        data.extend(struct.pack("<"+'B'*len(servo_id), *servo_id))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)

    def bus_servo_set_position(self, duration, positions):
        """
        :brief 总线舵机同步位置指令
        :param duration: 运动时间（秒）转 ms 低高字节下发
        :param positions: [[id, position], ...]
        """
        duration = int(duration * 1000)
        data = [0x01, duration & 0xFF, 0xFF & (duration >> 8), len(positions)]
        for i in positions:
            data.extend(struct.pack("<BH", i[0], i[1]))
        self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, data)

    def bus_servo_read_and_unpack(self, servo_id, cmd, unpack):
        """
        :brief 总线舵机读命令通用封装
        :desc 加锁发子命令，阻塞读 bus_servo_queue；success==0 时返回 info 元组，否则 None
        """
        with self.servo_read_lock:
            self.buf_write(PacketFunction.PACKET_FUNC_BUS_SERVO, [cmd, servo_id])
            data = self.bus_servo_queue.get(block=True)
            servo_id, cmd, success, *info = struct.unpack(unpack, data)
            if success == 0:
                return info

    def bus_servo_read_id(self, servo_id=254):
        """
        :brief 读取总线舵机 ID
        :param servo_id: 默认 254 为广播/扫描约定
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x12, "<BBbB")

    def bus_servo_read_offset(self, servo_id):
        """
        :brief 读取总线舵机偏移
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x22, "<BBbb")

    def bus_servo_read_position(self, servo_id):
        """
        :brief 读取总线舵机当前位置
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x05, "<BBbh")

    def bus_servo_read_vin(self, servo_id):
        """
        :brief 读取总线舵机供电电压
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x07, "<BBbH")

    def bus_servo_read_temp(self, servo_id):
        """
        :brief 读取总线舵机温度
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x09, "<BBbB")

    def bus_servo_read_temp_limit(self, servo_id):
        """
        :brief 读取温度保护阈值
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x3A, "<BBbB")

    def bus_servo_read_angle_limit(self, servo_id):
        """
        :brief 读取角度限制
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x32, "<BBb2H")

    def bus_servo_read_vin_limit(self, servo_id):
        """
        :brief 读取电压限制
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x36, "<BBb2H")

    def bus_servo_read_torque_state(self, servo_id):
        """
        :brief 读取力矩开关状态
        :param servo_id: 舵机 id
        """
        return self.bus_servo_read_and_unpack(servo_id, 0x0D, "<BBbb")

    def enable_reception(self, enable=True):
        """
        :brief 开关接收线程是否解析串口数据
        :desc False 时 recv_task 仅休眠，不读端口；各 get_* 也会提示先开启
        :param enable: 是否接收
        """
        self.enable_recv = enable

    def recv_task(self):
        """
        :brief 串口接收与状态机解析主循环
        :desc 逐字节驱动 PacketControllerState；校验通过后按功能码调用 parsers 入队
        """
        while True:
            if self.enable_recv:
                recv_data = self.port.read()
                if recv_data:
                    for dat in recv_data:
                        # print("%0.2X "%dat)
                        if self.state == PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE1:
                            if dat == 0xAA:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE2
                            continue
                        elif self.state == PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE2:
                            if dat == 0x55:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_FUNCTION
                            else:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE1
                            continue
                        elif self.state == PacketControllerState.PACKET_CONTROLLER_STATE_FUNCTION:
                            if dat < int(PacketFunction.PACKET_FUNC_NONE):
                                self.frame = [dat, 0]
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_LENGTH
                            else:
                                self.frame = []
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE1
                            continue
                        elif self.state == PacketControllerState.PACKET_CONTROLLER_STATE_LENGTH:
                            self.frame[1] = dat
                            self.recv_count = 0
                            if dat == 0:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_CHECKSUM
                            else:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_DATA
                            continue
                        elif self.state == PacketControllerState.PACKET_CONTROLLER_STATE_DATA:
                            self.frame.append(dat)
                            self.recv_count += 1
                            if self.recv_count >= self.frame[1]:
                                self.state = PacketControllerState.PACKET_CONTROLLER_STATE_CHECKSUM
                            continue
                        elif self.state == PacketControllerState.PACKET_CONTROLLER_STATE_CHECKSUM:
                            crc8 = checksum_crc8(bytes(self.frame))
                            if crc8 == dat:
                                func = PacketFunction(self.frame[0])
                                data = bytes(self.frame[2:])
                                if func in self.parsers:
                                    self.parsers[func](data)
                            else:
                                print("校验失败")
                            self.state = PacketControllerState.PACKET_CONTROLLER_STATE_STARTBYTE1
                            continue
            else:
                time.sleep(0.01)
        self.port.close()
        print("END...")


def bus_servo_test(board):
    """
    :brief 总线舵机 SDK 自测流程示例
    :param board: Board 实例
    """
    board.bus_servo_set_position(1, [[1, 500], [2, 500]])
    time.sleep(1)
    board.bus_servo_set_position(2, [[1, 0], [2, 0]])
    time.sleep(1)
    board.bus_servo_stop([1, 2])
    time.sleep(1)
    
    servo_id = 1
    board.bus_servo_set_id(254, servo_id)
    servo_id = board.bus_servo_read_id()
    if servo_id is not None:
        servo_id = servo_id[0]
        
        offset_set = -10
        board.bus_servo_set_offset(servo_id, offset_set)
        board.bus_servo_save_offset(servo_id)
        
        vin_l, vin_h = 4500, 14500
        board.bus_servo_set_vin_limit(servo_id, [vin_l, vin_h])

        temp_limit = 85
        board.bus_servo_set_temp_limit(servo_id, temp_limit)

        angle_l, angle_h = 0, 1000
        board.bus_servo_set_angle_limit(servo_id, [angle_l, angle_h])
        
        board.bus_servo_enable_torque(servo_id, 1)

        print('id:', board.bus_servo_read_id(servo_id))
        print('offset:', board.bus_servo_read_offset(servo_id), offset_set)
        print('vin:', board.bus_servo_read_vin(servo_id))
        print('temp:', board.bus_servo_read_temp(servo_id))
        print('position:', board.bus_servo_read_position(servo_id))
        print('angle_limit:', board.bus_servo_read_angle_limit(servo_id), [angle_l, angle_h])
        print('vin_limit:', board.bus_servo_read_vin_limit(servo_id), [vin_l, vin_h])
        print('temp_limit:', board.bus_servo_read_temp_limit(servo_id), temp_limit)
        print('torque_state:', board.bus_servo_read_torque_state(servo_id))


def pwm_servo_test(board):
    """
    :brief PWM 舵机 SDK 自测流程示例
    :param board: Board 实例
    """
    servo_id = 1
    board.pwm_servo_set_position(0.5, [[servo_id, 1500]])
    board.pwm_servo_set_offset(servo_id, 0)
    print('offset:', board.pwm_servo_read_offset(servo_id))
    print('position:', board.pwm_servo_read_position(servo_id))

if __name__ == "__main__":
    board = Board()
    board.enable_reception()
    print("START...")
    board.set_led(0.1, 0.9, 1)
    board.set_buzzer(1900, 0.05, 0.01, 1)
    board.set_rgb([[1, 0, 0, 255]])
    # board.set_motor_speed([[1, 0.6], [2, 0.6], [3, -0.6], [4, -0.6]])
    # time.sleep(1)
    # board.set_motor_speed([[1, 0], [2, 0], [3, 0], [4, 0]])
    # bus_servo_test(board)
    # pwm_servo_test(board)
    # last_time = time.time()
    while True:
        try:
            # board.set_buzzer(3000, 0.05, 0.01, 1)
            res = board.get_imu()
            if res is not None:
                for item in res:
                    print("  {: .8f} ".format(item), end='')
                print()
            # res = board.get_button()
            # if res is not None:
                # print(res)
            # data = board.get_gamepad()
            # if data is not None:
                # print(data[0])
                # print(data[1])
            # res = board.get_sbus()
            # if res is not None:
                # print(res)
            # res = board.get_battery()
            # if res is not None:
                # print(res)
            time.sleep(0.01)
            # t = time.time()
            # print(1/(t - last_time))
            # last_time = t
        except KeyboardInterrupt:
            break
