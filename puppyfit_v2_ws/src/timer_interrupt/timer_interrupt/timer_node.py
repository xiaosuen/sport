#!/usr/bin/env python3
'''
:brief 定时中断节点（通用）
:desc 启动后经过指定秒数向配置的控制话题发布 "stop"，使对应运动计数模块进入停止状态。
      通过参数 control_topic 与 exercise_name 实现弱耦合，可复用于仰卧起坐、俯卧撑等任意运动。

:author slt
:date 2026/03/15
:version 1.1.0
:history
    1.0.0 - 2026/03/12
        :brief 单次定时器，到时后发布停止指令
    1.0.1 - 2026/03/13
        :brief 每秒打印剩余时间便于观察
    1.1.0 - 2026/03/15
        :brief 参数化 control_topic / exercise_name，支持多运动扩展
'''

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Empty


class TimerInterruptNode(Node):
    '''
    :brief 通用定时中断节点类
    :desc 单次定时器，到时向指定 control_topic 发布 "stop"；通过参数与具体运动解耦。
    '''

    def __init__(self):
        super().__init__('timer_interrupt_node')

        # 定时时长（秒）
        self.declare_parameter('duration_sec', 60)
        val = self.get_parameter('duration_sec').value
        try:
            self.duration_sec = float(val) if val is not None else 60.0
        except (TypeError, ValueError):
            self.duration_sec = 60.0
        if self.duration_sec <= 0:
            self.duration_sec = 60.0

        # 控制话题：订阅该话题的计数节点将收到 "stop" 进入停止状态（弱耦合，可配 situp_control / pushup_control 等）
        self.declare_parameter('control_topic', 'situp_control')
        self.control_topic = self.get_parameter('control_topic').get_parameter_value().string_value
        if not self.control_topic or not self.control_topic.strip():
            self.control_topic = 'situp_control'

        # 运动名称（仅用于日志展示，便于区分仰卧起坐/俯卧撑等）
        self.declare_parameter('exercise_name', '仰卧起坐')
        self.exercise_name = self.get_parameter('exercise_name').get_parameter_value().string_value or '目标模块'

        # 是否在节点启动时立即开始计时；False 时需向 timer/start 发布消息后才开始（用于语音助手流程）
        self.declare_parameter('start_on_launch', False)
        self._start_on_launch = self.get_parameter('start_on_launch').value in (True, 'true', 'True', '1')

        self.control_pub = self.create_publisher(String, self.control_topic, 10)
        self._fired = False
        self.timer = None

        if self._start_on_launch:
            self._start_time = self.get_clock().now()
            self.timer = self.create_timer(1.0, self._on_tick)
            self.get_logger().info(
                f'定时器已启动（立即计时）：{self.duration_sec}s 后向话题 [{self.control_topic}] 发送停止指令（{self.exercise_name}）'
            )
        else:
            self._start_time = None
            self._start_sub = self.create_subscription(
                Empty,
                'timer/start',
                self._on_start_cmd,
                10,
            )
            self.get_logger().info(
                f'定时器已就绪（等待 timer/start）：收到后将 {self.duration_sec}s 向 [{self.control_topic}] 发送停止指令（{self.exercise_name}）'
            )

    def _on_start_cmd(self, _msg: Empty) -> None:
        """收到 timer/start 后开始 60s 倒计时（用于语音助手：检测到人体后再计时）。"""
        if self._fired:
            self.get_logger().info('上次定时已结束，重新开始计时')
        self._start_time = self.get_clock().now()
        self._fired = False
        if self.timer is None:
            self.timer = self.create_timer(1.0, self._on_tick)
        self.get_logger().info(f'定时开始：{self.duration_sec}s 后向 [{self.control_topic}] 发送停止指令')

    def _on_tick(self):
        if self._fired or self._start_time is None:
            return
        now = self.get_clock().now()
        elapsed = (now - self._start_time).nanoseconds / 1e9
        if elapsed >= self.duration_sec:
            self._fired = True
            self.timer.cancel()
            self.timer = None  # 便于下次收到 timer/start 时重新 create_timer，支持多轮计时
            msg = String()
            msg.data = 'stop'
            self.control_pub.publish(msg)
            self.get_logger().info(f'定时到达，已向 [{self.control_topic}] 发送停止指令（{self.exercise_name} 进入停止状态）')
        else:
            remaining = self.duration_sec - elapsed
            self.get_logger().info(f'剩余 {int(remaining)} 秒')


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = TimerInterruptNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
