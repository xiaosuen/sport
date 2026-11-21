#!/usr/bin/env python3
'''
:brief 仰卧起坐计数节点
:desc 订阅姿态关键点，实现仰卧起坐计数逻辑，发布计数结果（robot_msgs/SitUpCount）。

:author slt&zxh
:date 2026/03/03
:version 1.0.3
:history
    1.0.0 - 2026/03/03
        :brief 初始版本
    1.0.1 - 2026/03/15
        :brief 增加语音助手模式：启动即停止，等用户说「开始」后收 start 再计数
    1.0.2 - 2026/03/17
        :brief 从停止态收到 start 时重置计数与人体初始化，修复第二轮语音唤醒计数不清零
    1.0.3 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
'''

import rclpy
from rclpy.node import Node
from std_msgs.msg import Header, String

from robot_msgs.msg import PoseLandmarks, SitUpCount
from exercise_engine_pkg.core.situp_counter import SitUpCounter


class SitUpCounterNode(Node):
    '''
    :brief 仰卧起坐计数节点类
    :desc 订阅姿态关键点，进行仰卧起坐计数，发布结果。
    '''

    # 姿态关键点索引
    POSE_LANDMARK_LEFT_SHOULDER = 11
    POSE_LANDMARK_RIGHT_SHOULDER = 12
    POSE_LANDMARK_LEFT_HIP = 23
    POSE_LANDMARK_RIGHT_HIP = 24

    def __init__(self):
        '''
        :brief 构造函数
        :desc 初始化节点、订阅者与发布者。
        '''
        super().__init__('situp_counter_node')

        # 声明参数
        self.declare_parameter('auto_reset', True)
        self.declare_parameter('reset_timeout', 5.0)
        self.declare_parameter('start_stopped', False)  # 语音助手模式：true 时启动即停止，等 situp_control 发 start 后再计数

        # 获取参数
        self.auto_reset = self.get_parameter('auto_reset').value
        self.reset_timeout = self.get_parameter('reset_timeout').value
        start_stopped = self.get_parameter('start_stopped').value
        if start_stopped in (True, 'true', 'True', '1'):
            start_stopped = True
        else:
            start_stopped = False

        # 创建计数器
        self.counter = SitUpCounter()

        # 创建订阅者
        self.pose_sub = self.create_subscription(
            PoseLandmarks,
            'pose_landmarks',
            self.pose_callback,
            10
        )

        # 创建发布者
        self.count_pub = self.create_publisher(SitUpCount, 'situp_count', 10)
        self.status_pub = self.create_publisher(String, 'situp_status', 10)

        # 订阅控制话题：接收 "stop" 进入停止状态，"start" 恢复计数
        self.control_sub = self.create_subscription(
            String,
            'situp_control',
            self._control_callback,
            10
        )

        # 状态变量
        self.last_count = 0
        self.frame_count = 0
        self.stopped = bool(start_stopped)  # 语音助手模式下启动即停止，等用户说「开始」后收 start 再计数

        if self.stopped:
            self.get_logger().info('仰卧起坐计数节点已启动（语音助手模式：等待 situp_control start 后再计数）')
        else:
            self.get_logger().info('仰卧起坐计数节点已启动')
        self.get_logger().info('等待姿态数据...')

    def _control_callback(self, msg):
        """
        :brief 控制回调：接收 "stop" 进入停止状态，"start" 恢复计数
        :param msg: String 消息
        """
        cmd = (msg.data or "").strip().lower()
        if cmd == 'stop':
            if not self.stopped:
                self.stopped = True
                self.get_logger().info('已进入停止状态，不再计数')
        elif cmd == 'start':
            if self.stopped:
                # 新一轮语音唤醒/定时结束后再次 start：必须清零计数并重置人体初始化，
                # 否则 init_state 仍为 True，会继续沿用上一轮 count（表现为第二轮计数不清零）。
                self.reset_counter()
                self.stopped = False
                hdr = Header()
                hdr.stamp = self.get_clock().now().to_msg()
                hdr.frame_id = 'situp_control'
                self._publish_count(hdr)
                self.get_logger().info('已恢复计数（新一轮：计数已清零，需重新完成人体初始化）')

    def pose_callback(self, msg):
        """
        :brief 姿态数据回调函数
        :desc 接收关键点数据，进行计数处理
        :param msg: PoseLandmarks消息
        """
        if len(msg.landmarks) < 33:
            self.get_logger().warn('关键点数据不完整')
            return

        # 停止状态下仅发布当前计数，不处理新帧
        if self.stopped:
            self._publish_count(msg.header)
            return

        # 提取关键点
        left_shoulder = self._landmark_to_dict(msg.landmarks[self.POSE_LANDMARK_LEFT_SHOULDER])
        right_shoulder = self._landmark_to_dict(msg.landmarks[self.POSE_LANDMARK_RIGHT_SHOULDER])
        left_hip = self._landmark_to_dict(msg.landmarks[self.POSE_LANDMARK_LEFT_HIP])
        right_hip = self._landmark_to_dict(msg.landmarks[self.POSE_LANDMARK_RIGHT_HIP])

        # 检查关键点可见性
        if not self._check_visibility([left_shoulder, right_shoulder, left_hip, right_hip]):
            return

        # 初始化或处理帧
        if not self.counter.get_init_state():
            self.counter.process_init(left_shoulder, right_shoulder, left_hip, right_hip)
            if self.counter.get_init_state():
                self.get_logger().info('初始化完成！开始计数')
                self.get_logger().info(f'坐姿方向: {self.counter.get_direction()}')
        else:
            self.counter.process_frame(left_shoulder, right_shoulder)

            # 检查计数变化
            current_count = self.counter.get_count()
            if current_count != self.last_count:
                self.get_logger().info(f'计数: {current_count}')
                self.last_count = current_count

        # 发布计数结果
        self._publish_count(msg.header)

    def _landmark_to_dict(self, landmark):
        """
        :brief 将关键点消息转换为字典
        :desc 方便后续处理
        :param landmark: Landmark消息
        :return: 关键点字典
        """
        return {
            'x': landmark.x,
            'y': landmark.y,
            'z': landmark.z,
            'visibility': landmark.visibility
        }

    def _check_visibility(self, landmarks):
        """
        :brief 检查关键点可见性
        :desc 确保所有关键点都可见
        :param landmarks: 关键点列表
        :return: 是否全部可见
        """
        for lm in landmarks:
            if lm['visibility'] < 0.5:
                return False
        return True

    def _publish_count(self, header):
        """
        :brief 发布计数结果
        :desc 创建并发布SitUpCount消息
        :param header: 消息头
        """
        msg = SitUpCount()
        msg.header = header
        msg.count = self.counter.get_count()
        msg.state = 'STOPPED' if self.stopped else self.counter.get_state_string()
        msg.direction = self.counter.get_direction()
        msg.initialized = self.counter.get_init_state()

        self.count_pub.publish(msg)

        # 发布状态字符串
        status_msg = String()
        status_msg.data = f'Count: {msg.count}, State: {msg.state}, Dir: {msg.direction}'
        self.status_pub.publish(status_msg)

    def reset_counter(self):
        """
        :brief 重置计数器
        :desc 手动重置计数
        """
        self.counter.reset_count()
        self.last_count = 0
        self.get_logger().info('计数器已重置')


def main(args=None):
    """
    :brief 主函数
    :desc 节点入口
    """
    rclpy.init(args=args)
    node = SitUpCounterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
