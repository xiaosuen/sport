#!/usr/bin/env python3
'''
:brief 运动助手编排节点
:desc 订阅 asr/text，识别关键词后播报确认语并恢复计数；订阅 situp_count，在「开始计数」播报完成后发布 timer/start。

:author ubuntu
:date 2026/03/29
:version 1.1.0
:history
    1.1.0 - 2026/03/31
        :brief 可选 session_record_start_topic：在 situp_control=start 前发布 SessionRecordStart
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块与类注释
'''

import uuid

import rclpy
from rclpy.node import Node
from robot_msgs.msg import SitUpCount
from session_record_msgs.msg import SessionRecordStart
from std_msgs.msg import Empty, String


class State:
    '''
    :brief 运动助手状态常量
    :desc IDLE / WAITING_POSE / COUNTING。
    '''

    IDLE = "idle"
    WAITING_POSE = "waiting_pose"
    COUNTING = "counting"


class ExerciseAssistantNode(Node):
    '''
    :brief 运动助手 ROS2 节点
    :desc 协调 ASR、计数话题与定时启动，驱动仰卧起坐语音流程。
    '''

    TRIGGER_KEYWORDS = ("开始", "计数", "仰卧起坐")

    def __init__(self):
        super().__init__("exercise_assistant_node")

        self.declare_parameter("asr_topic", "asr/text")
        self.declare_parameter("count_topic", "situp_count")
        self.declare_parameter("tts_speak_topic", "tts/speak")
        self.declare_parameter("timer_start_topic", "timer/start")
        self.declare_parameter("control_topic", "situp_control")
        self.declare_parameter("phrase_ack", "收到，正在检测人体关节点")
        self.declare_parameter("start_spoken_notify_topic", "situp/ws_start")
        self.declare_parameter("session_record_start_topic", "")

        self._asr_topic = self.get_parameter("asr_topic").get_parameter_value().string_value or "asr/text"
        self._count_topic = self.get_parameter("count_topic").get_parameter_value().string_value or "situp_count"
        self._tts_speak_topic = self.get_parameter("tts_speak_topic").get_parameter_value().string_value or "tts/speak"
        self._timer_start_topic = (
            self.get_parameter("timer_start_topic").get_parameter_value().string_value or "timer/start"
        )
        self._control_topic = self.get_parameter("control_topic").get_parameter_value().string_value or "situp_control"
        self._phrase_ack = (
            self.get_parameter("phrase_ack").get_parameter_value().string_value or "收到，正在检测人体关节点"
        )
        self._start_spoken_notify_topic = (
            self.get_parameter("start_spoken_notify_topic").get_parameter_value().string_value or "situp/ws_start"
        )
        _sr_topic = (self.get_parameter("session_record_start_topic").get_parameter_value().string_value or "").strip()
        self._record_start_pub = None
        if _sr_topic:
            self._record_start_pub = self.create_publisher(SessionRecordStart, _sr_topic, 10)

        self._state = State.IDLE
        self._last_initialized = False
        self._last_state = ""
        self._pose_ready = False
        self._start_spoken = False

        self._tts_pub = self.create_publisher(String, self._tts_speak_topic, 10)
        self._timer_start_pub = self.create_publisher(Empty, self._timer_start_topic, 10)
        self._control_pub = self.create_publisher(String, self._control_topic, 10)

        self.create_subscription(String, self._asr_topic, self._on_asr, 10)
        self.create_subscription(SitUpCount, self._count_topic, self._on_count, 10)
        self.create_subscription(String, self._start_spoken_notify_topic, self._on_start_spoken, 10)

        self.get_logger().info(
            f"运动助手已启动：订阅 {self._asr_topic}、{self._count_topic}"
        )

    def _on_asr(self, msg: String) -> None:
        text = (msg.data or "").strip()
        if not text:
            return
        self.get_logger().debug(f"ASR: 「{text}」")
        if any(kw in text for kw in self.TRIGGER_KEYWORDS):
            self.get_logger().info(f"开始指令: 「{text}」")
            if self._record_start_pub is not None:
                rs = SessionRecordStart()
                rs.session_id = str(uuid.uuid4())
                rs.stamp = self.get_clock().now().to_msg()
                rs.tag = ""
                self._record_start_pub.publish(rs)
            ctrl = String()
            ctrl.data = "start"
            self._control_pub.publish(ctrl)
            ack = String()
            ack.data = self._phrase_ack
            self._tts_pub.publish(ack)
            self._state = State.WAITING_POSE
            self._pose_ready = False
            self._start_spoken = False

    def _try_start_timer(self) -> None:
        if self._state != State.WAITING_POSE:
            return
        if not self._start_spoken:
            return
        if self._pose_ready:
            self.get_logger().info("开始计数已播报且人体就绪，启动定时器")
        else:
            self.get_logger().info("开始计数已播报，启动定时器")
        self._timer_start_pub.publish(Empty())
        self._state = State.COUNTING

    def _on_start_spoken(self, msg: String) -> None:
        if self._state != State.WAITING_POSE:
            return
        self._start_spoken = True
        extra = (msg.data or "").strip()
        if extra:
            self.get_logger().info(f"开始计数播报完成: {extra}")
        else:
            self.get_logger().info("开始计数播报完成")
        self._try_start_timer()

    def _on_count(self, msg: SitUpCount) -> None:
        initialized = bool(msg.initialized)
        state = str(msg.state) if msg.state else ""

        if self._state == State.WAITING_POSE and initialized:
            if not self._pose_ready:
                self.get_logger().info("人体已就绪（等待开始计数播报后再启动定时器）")
            self._pose_ready = True
            self._try_start_timer()

        if self._state == State.COUNTING and state == "STOPPED" and self._last_state != "STOPPED":
            self.get_logger().info("计时结束，空闲")
            self._state = State.IDLE

        self._last_initialized = initialized
        self._last_state = state


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = ExerciseAssistantNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
