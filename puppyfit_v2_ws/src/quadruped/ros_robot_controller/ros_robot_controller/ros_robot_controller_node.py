#!/usr/bin/env python3
# encoding: utf-8
'''
:brief STM32 机器人控制板 ROS2 桥接节点
:desc 通过串口 SDK 与板卡通讯：订阅 LED/蜂鸣器/电机/舵机/OLED/RGB 等控制指令并下发；轮询发布 IMU、手柄、SBUS、按键、电池等上报数据；提供总线舵机与 PWM 舵机状态查询服务。

:author Aiden
:date 2023/08/28
:version 1.0.1
:history
    1.0.0 - 2023/08/28
        :brief 初始版本（节点 + 话题/服务与 SDK 对接）
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
'''

import math
import time
import rclpy
import signal
import threading
from rclpy.node import Node
from std_srvs.srv import Trigger
from sensor_msgs.msg import Imu, Joy
from std_msgs.msg import UInt16, Bool
from ros_robot_controller.ros_robot_controller_sdk import Board
from ros_robot_controller_msgs.srv import GetBusServoState, GetPWMServoState
from ros_robot_controller_msgs.msg import ButtonState, BuzzerState, LedState, MotorsState, BusServoState, SetBusServoState, ServosPosition, SetPWMServoState, PWMServoState, Sbus, OLEDState, RGBsState


class RosRobotController(Node):
    '''
    :brief 机器人控制板 ROS 节点类
    :desc 封装 Board SDK，创建订阅/发布/服务，并在后台线程中周期发布传感器与遥控数据。
    '''

    # 标准重力加速度 (m/s^2)，用于将板卡上报的 g 转为 Imu.linear_acceleration
    gravity = 9.80665

    def __init__(self, name):
        '''
        :brief 构造函数
        :desc 初始化 rclpy、串口板卡、参数、话题与服务，并启动轮询发布线程。
        :param name: 节点名称
        '''
        # 该节点内部主动调用 rclpy.init()，通常无需在外部再次 init
        rclpy.init()
        super().__init__(name)
        # 底层串口板卡；默认设备路径与波特率见 Board.__init__
        self.board = Board()
        # 打开 SDK 侧接收；是否实际发布仍由话题 enable_reception 与回调内同名属性控制
        self.board.enable_reception()
        self.running = True

        # 声明参数
        self.declare_parameter('imu_frame', 'imu_link')
        self.declare_parameter('init_finish', False)
        self.IMU_FRAME = self.get_parameter('imu_frame').value

        # 发布：板卡上报数据（相对名 ~/ 会展开为节点私有命名空间）
        self.imu_pub = self.create_publisher(Imu, '~/imu_raw', 1)
        self.joy_pub = self.create_publisher(Joy, '~/joy', 1)
        self.sbus_pub = self.create_publisher(Sbus, '~/sbus', 1)
        self.button_pub = self.create_publisher(ButtonState, '~/button', 1)
        self.battery_pub = self.create_publisher(UInt16, '~/battery', 1)
        # 订阅：上层控制指令
        self.create_subscription(LedState, '~/set_led', self.set_led_state, 5)
        self.create_subscription(BuzzerState, '~/set_buzzer', self.set_buzzer_state, 5)
        self.create_subscription(OLEDState, '~/set_oled', self.set_oled_state, 5)
        self.create_subscription(MotorsState, '~/set_motor', self.set_motor_state, 10)
        self.create_subscription(RGBsState, '~/set_rgb', self.set_rgb_state, 10)
        self.create_subscription(Bool, '~/enable_reception', self.enable_reception, 1)
        self.create_subscription(SetBusServoState, '~/bus_servo/set_state', self.set_bus_servo_state, 10)
        self.create_subscription(ServosPosition, '~/bus_servo/set_position', self.set_bus_servo_position, 10)
        self.create_subscription(SetPWMServoState, '~/pwm_servo/set_state', self.set_pwm_servo_state, 10)
        # 服务：读取舵机状态
        self.create_service(GetBusServoState, '~/bus_servo/get_state', self.get_bus_servo_state)
        self.create_service(GetPWMServoState, '~/pwm_servo/get_state', self.get_pwm_servo_state)

        # 上电安全：PWM 舵机 1 零偏置，电机全部停转
        self.board.pwm_servo_set_offset(1, 0)
        self.board.set_motor_speed([[1, 0], [2, 0], [3, 0], [4, 0]])
        self.clock = self.get_clock()
        # 后台线程：固定周期从 SDK 队列取数并发布
        threading.Thread(target=self.pub_callback, daemon=True).start()
        # Trigger 服务：供外部探测节点是否已就绪
        self.create_service(Trigger, '~/init_finish', self.get_node_state)
        self.get_logger().info('\033[1;32m%s\033[0m' % 'start')

    def get_node_state(self, request, response):
        """
        :brief 节点就绪探测服务回调
        :desc 成功即表示节点已创建完成（不保证板卡业务初始化全部结束）
        :param request: std_srvs/Trigger 请求（无有效字段）
        :param response: std_srvs/Trigger 响应，success 置 True
        :return: 填充后的 response
        """
        response.success = True
        return response

    def pub_callback(self):
        """
        :brief 后台轮询发布循环
        :desc 当 self.enable_reception 为真时周期读取按键/手柄/IMU/SBUS/电池并发布；线程结束时调用 rclpy.shutdown()
        """
        # 注意：首次回调 enable_reception(msg) 后，实例属性 self.enable_reception 会覆盖同名方法，此处读取的为布尔开关
        while self.running:
            if self.enable_reception:
                self.pub_button_data(self.button_pub)
                self.pub_joy_data(self.joy_pub)
                self.pub_imu_data(self.imu_pub)
                self.pub_sbus_data(self.sbus_pub)
                self.pub_battery_data(self.battery_pub)
                time.sleep(0.02)
            else:
                time.sleep(0.02)
        rclpy.shutdown()

    def enable_reception(self, msg):
        """
        :brief 开关底层串口接收与数据发布
        :desc 将 Bool 消息写入实例属性并同步到 Board；首次执行后方法名被属性遮蔽，pub_callback 读取的是布尔值
        :param msg: std_msgs/Bool，data 为 True 时接收并发布上报数据
        """
        self.get_logger().info('\033[1;32m%s\033[0m' % ('enable_reception ' + str(msg.data)))
        self.enable_reception = msg.data
        self.board.enable_reception(msg.data)

    def set_led_state(self, msg):
        """
        :brief LED 控制回调
        :param msg: LedState（亮灭时间、重复次数、灯号）
        """
        self.board.set_led(msg.on_time, msg.off_time, msg.repeat, msg.id)

    def set_buzzer_state(self, msg):
        """
        :brief 蜂鸣器控制回调
        :param msg: BuzzerState（频率与通断时序）
        """
        self.board.set_buzzer(msg.freq, msg.on_time, msg.off_time, msg.repeat)

    def set_motor_state(self, msg):
        """
        :brief 电机转速设置回调
        :desc 将 MotorsState 中的 MotorState 列表转为 SDK 所需的 [[电机id, rps], ...]
        :param msg: MotorsState
        """
        data = []
        for i in msg.data:
            data.extend([[i.id, i.rps]])
        self.board.set_motor_speed(data)

    def set_oled_state(self, msg):
        """
        :brief OLED 文本显示回调
        :param msg: OLEDState（行号 index 与 text）
        """
        self.board.set_oled_text(int(msg.index), msg.text)

    def set_pwm_servo_state(self, msg):
        """
        :brief PWM 舵机状态设置回调
        :desc 根据消息中带标志的数组字段设置位置与中位偏移；有有效 position 列表时调用 pwm_servo_set_position
        :param msg: SetPWMServoState
        """
        data = []
        for i in msg.state:
            # 消息中 id/position/offset 可能为带标志的可选数组，需判空
            if i.id and i.position:
                data.extend([[i.id[0], i.position[0]]])
            if i.id and i.offset:
                self.board.pwm_servo_set_offset(i.id[0], i.offset[0])

        if data != []:
            self.board.pwm_servo_set_position(msg.duration, data)

    def set_rgb_state(self, msg):
        """
        :brief RGB 灯带像素设置回调
        :desc 逐条调用 SDK set_rgb，每条消息可含多像素
        :param msg: RGBsState
        """
        for i in msg.data:
            self.board.set_rgb([[i.id, i.r, i.g, i.b]])

    def get_pwm_servo_state(self, msg):
        """
        :brief 查询 PWM 舵机位置与中位偏移（服务实现）
        :desc 按 cmd 中 get_position/get_offset 标志读取并组装 PWMServoState 列表；当前实现返回 [success, states] 元组，需与客户端约定一致
        :param msg: GetPWMServoState 请求
        :return: [True, states] 列表，states 为 PWMServoState 消息列表
        """
        states = []
        for i in msg.cmd:
            data = PWMServoState()
            if i.get_position:
                state = self.board.pwm_servo_read_position(i.id)
                if state is not None:
                    data.position = state
            if i.get_offset:
                state = self.board.pwm_servo_read_offset(i.id)
                if state is not None:
                    data.offset = state
            states.append(data)
        return [True, states]

    def set_bus_servo_position(self, msg):
        """
        :brief 总线舵机位置指令回调（仅位置）
        :param msg: ServosPosition（duration 与 position 列表）
        """
        data = []
        for i in msg.position:
            data.extend([[i.id, i.position]])
        if data:
            self.board.bus_servo_set_position(msg.duration, data)

    def set_bus_servo_state(self, msg):
        """
        :brief 总线舵机综合设置回调
        :desc 解析 SetBusServoState 中带标志的字段：改 ID、位置、偏移、角度/电压/温度限制、力矩开关、保存偏移、停转等，最后按需下发位置或 stop
        :param msg: SetBusServoState
        """
        data = []
        servo_id = []
        for i in msg.state:
            if i.present_id:
                if i.present_id[0]:
                    if i.target_id:
                        if i.target_id[0]:
                            self.board.bus_servo_set_id(i.present_id[1], i.target_id[1])
                    if i.position:
                        if i.position[0]:
                            data.extend([[i.present_id[1], i.position[1]]])
                    if i.offset:
                        if i.offset[0]:
                            self.board.bus_servo_set_offset(i.present_id[1], i.offset[1])
                    if i.position_limit:
                        if i.position_limit[0]:
                            self.board.bus_servo_set_angle_limit(i.present_id[1], i.position_limit[1:])
                    if i.voltage_limit:
                        if i.voltage_limit[0]:
                            self.board.bus_servo_set_vin_limit(i.present_id[1], i.voltage_limit[1:])
                    if i.max_temperature_limit:
                        if i.max_temperature_limit[0]:
                            self.board.bus_servo_set_temp_limit(i.present_id[1], i.max_temperature_limit[1])
                    if i.enable_torque:
                        if i.enable_torque[0]:
                            self.board.bus_servo_enable_torque(i.present_id[1], i.enable_torque[1])
                    if i.save_offset:
                        if i.save_offset[0]:
                            self.board.bus_servo_save_offset(i.present_id[1])
                    if i.stop:
                        if i.stop[0]:
                            servo_id.append(i.present_id[1])
        if data != []:
            self.board.bus_servo_set_position(msg.duration, data)
        if servo_id != []:    
            self.board.bus_servo_stop(servo_id)

    def get_bus_servo_state(self, request, response):
        """
        :brief 查询总线舵机状态服务回调
        :desc 按 cmd 中各 get_* 标志调用 Board 读接口，填充 BusServoState 列表写入 response
        :param request: GetBusServoState 请求
        :param response: GetBusServoState 响应，填充 state 与 success
        :return: response
        """
        states = []
        for i in request.cmd:
            data = BusServoState()
            if i.get_id:
                state = self.board.bus_servo_read_id(i.id)
                if state is not None:
                    i.id = state[0]
                    data.present_id = state
            if i.get_position:
                state = self.board.bus_servo_read_position(i.id)
                if state is not None:
                    data.position = state
            if i.get_offset:
                state = self.board.bus_servo_read_offset(i.id)
                if state is not None:
                    data.offset = state
            if i.get_voltage:
                state = self.board.bus_servo_read_voltage(i.id)
                if state is not None:
                    data.voltage = state
            if i.get_temperature:
                state = self.board.bus_servo_read_temp(i.id)
                if state is not None:
                    data.temperature = state
            if i.get_position_limit:
                state = self.board.bus_servo_read_angle_limit(i.id)
                if state is not None:
                    data.position_limit = state
            if i.get_voltage_limit:
                state = self.board.bus_servo_read_vin_limit(i.id)
                if state is not None:
                    data.voltage_limit = state
            if i.get_max_temperature_limit:
                state = self.board.bus_servo_read_temp_limit(i.id)
                if state is not None:
                    data.max_temperature_limit = state
            if i.get_torque_state:
                state = self.board.bus_servo_read_torque(i.id)
                if state is not None:
                    data.enable_torque = state
            states.append(data)
        response.state = states
        response.success = True
        return response

    def pub_battery_data(self, pub):
        """
        :brief 发布电池电压
        :desc 从 SDK 取电压（mV 量级，与板卡协议一致），封装为 UInt16
        :param pub: UInt16 发布者
        """
        data = self.board.get_battery()
        if data is not None:
            msg = UInt16()
            msg.data = data
            pub.publish(msg)

    def pub_button_data(self, pub):
        """
        :brief 发布板载按键状态
        :param pub: ButtonState 发布者
        """
        data = self.board.get_button()
        if data is not None:
            msg = ButtonState()
            msg.id = data[0]
            msg.state = data[1]
            pub.publish(msg)

    def pub_joy_data(self, pub):
        """
        :brief 发布无线手柄数据
        :desc 将 SDK 返回的 axes/buttons 填入 sensor_msgs/Joy 并打时间戳
        :param pub: Joy 发布者
        """
        data = self.board.get_gamepad()
        if data is not None:
            msg = Joy()
            msg.axes = data[0]
            msg.buttons = data[1]
            msg.header.stamp = self.clock.now().to_msg()
            pub.publish(msg)

    def pub_sbus_data(self, pub):
        """
        :brief 发布 SBUS 遥控通道数据
        :param pub: Sbus 发布者
        """
        data = self.board.get_sbus()
        if data is not None:
            msg = Sbus()
            msg.channel = data
            msg.header.stamp = self.clock.now().to_msg()
            pub.publish(msg)

    def pub_imu_data(self, pub):
        """
        :brief 发布 IMU 原始数据
        :desc 加速度由 g 转为 m/s^2，角速度由 deg/s 转为 rad/s；姿态四元数置零，协方差为占位值
        :param pub: Imu 发布者
        """
        data = self.board.get_imu()
        if data is not None:
            ax, ay, az, gx, gy, gz = data
            msg = Imu()
            msg.header.frame_id = self.IMU_FRAME
            msg.header.stamp = self.clock.now().to_msg()

            # 控制板仅上报加速度/角速度；姿态四元数置 0（由上层滤波器融合）
            msg.orientation.w = 0.0
            msg.orientation.x = 0.0
            msg.orientation.y = 0.0
            msg.orientation.z = 0.0

            # SDK 返回的加速度单位为 g，乘以标准重力得到 m/s^2
            msg.linear_acceleration.x = ax * self.gravity
            msg.linear_acceleration.y = ay * self.gravity
            msg.linear_acceleration.z = az * self.gravity

            # SDK 返回的角速度单位为 deg/s，这里转成 rad/s
            msg.angular_velocity.x = math.radians(gx)
            msg.angular_velocity.y = math.radians(gy)
            msg.angular_velocity.z = math.radians(gz)

            # 简单写入协方差，供下游节点使用（并非严格标定结果）
            msg.orientation_covariance = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]
            msg.angular_velocity_covariance = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]
            msg.linear_acceleration_covariance = [0.0004, 0.0, 0.0, 0.0, 0.0004, 0.0, 0.0, 0.0, 0.004]
            pub.publish(msg)


def main():
    """
    :brief 节点入口
    :desc 创建节点并 spin；键盘中断时电机停转并关闭节点
    """
    node = RosRobotController('ros_robot_controller')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.board.set_motor_speed([[1, 0], [2, 0], [3, 0], [4, 0]])
        node.destroy_node()
        rclpy.shutdown()
        print('shutdown')
    finally:
        print('shutdown finish')

if __name__ == '__main__':
    main()

