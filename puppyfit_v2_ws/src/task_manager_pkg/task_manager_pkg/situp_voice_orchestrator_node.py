#!/usr/bin/env python3
'''
:brief 语音唤醒仰卧起坐编排节点（找位 + 计数链）
:desc 订阅 asr/text（须与 voice_asr 的 output_topic 一致）；命中关键词后播确认语、向 auto_position/control 发 start；
      订阅 auto_position/status：failed/timeout 等播「没有找到合适的位置」并回 idle；ready 后发 situp_control=start，
      与 counting_tts、situp/ws_start、timer/start 链路与 exercise_assistant 一致。
      旧链路仍用 exercise_assistant + situp_voice.launch.py，二者二选一。

:author slt
:date 2026/04/10
:version 1.0.1
:history
    1.0.1 - 2026/04/23
        :brief 确认语先发 TTS 后再延时可配置秒数启动 auto_position，避免与找位步态/CPU 同时抢占导致听不清
    1.0.0 - 2026/04/10
        :brief 初始版本
'''

from __future__ import annotations

import uuid
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.timer import Timer
from robot_msgs.msg import SitUpCount
from session_record_msgs.msg import SessionRecordStart
from std_msgs.msg import Empty, String


class OrchestratorState:
    '''
    :brief 编排状态
    '''

    IDLE = "idle"
    WAITING_POSITION = "waiting_position"
    WAITING_POSE = "waiting_pose"
    COUNTING = "counting"


class SitupVoiceOrchestratorNode(Node):
    '''
    :brief 仰卧起坐语音全流程编排
    '''

    TRIGGER_KEYWORDS = ("开始", "计数", "仰卧起坐")

    def __init__(self) -> None:
        super().__init__("situp_voice_orchestrator")

        self.declare_parameter("asr_topic", "asr/text")
        self.declare_parameter("count_topic", "situp_count")
        self.declare_parameter("tts_speak_topic", "tts/speak")
        self.declare_parameter("timer_start_topic", "timer/start")
        self.declare_parameter("control_topic", "situp_control")
        self.declare_parameter("auto_position_control_topic", "auto_position/control")
        self.declare_parameter("auto_position_status_topic", "auto_position/status")
        self.declare_parameter("phrase_ack", "收到，正在调整位置")
        self.declare_parameter("phrase_no_person", "没有找到合适的位置")
        self.declare_parameter("start_spoken_notify_topic", "situp/ws_start")
        self.declare_parameter("session_record_start_topic", "")
        # 发 phrase_ack 到 tts/speak 后，延迟若干秒再发 auto_position start，便于 Piper 先出声再找位（0=旧行为，立刻找位）
        self.declare_parameter("ap_start_delay_sec", 0.6)

        self._asr_topic = (
            self.get_parameter("asr_topic")
            .get_parameter_value().
            string_value or "asr/text"
        )
        self._count_topic = (
            self.get_parameter("count_topic").get_parameter_value().string_value or "situp_count"
        )
        self._tts_speak_topic = (
            self.get_parameter("tts_speak_topic").get_parameter_value().string_value or "tts/speak"
        )
        self._timer_start_topic = (
            self.get_parameter("timer_start_topic").get_parameter_value().string_value or "timer/start"
        )
        self._control_topic = (
            self.get_parameter("control_topic").get_parameter_value().string_value or "situp_control"
        )
        self._ap_control_topic = (
            self.get_parameter("auto_position_control_topic").get_parameter_value().string_value
            or "auto_position/control"
        )
        self._ap_status_topic = (
            self.get_parameter("auto_position_status_topic").get_parameter_value().string_value
            or "auto_position/status"
        )
        self._phrase_ack = (
            self.get_parameter("phrase_ack").get_parameter_value().string_value or "收到，正在调整位置"
        )
        self._phrase_no_person = (
            self.get_parameter("phrase_no_person").get_parameter_value().string_value or "没有找到合适的位置"
        )
        self._start_spoken_notify_topic = (
            self.get_parameter("start_spoken_notify_topic").get_parameter_value().string_value
            or "situp/ws_start"
        )
        _sr_topic = (
            self.get_parameter("session_record_start_topic").get_parameter_value().string_value or ""
        ).strip()
        self._record_start_pub = None
        if _sr_topic:
            self._record_start_pub = self.create_publisher(SessionRecordStart, _sr_topic, 10)

        self._state = OrchestratorState.IDLE
        self._last_initialized = False
        self._last_state = ""
        self._pose_ready = False
        self._start_spoken = False
        self._ap_start_delay_sec = float(
            self.get_parameter("ap_start_delay_sec").get_parameter_value().double_value
        )
        if self._ap_start_delay_sec < 0.0:
            self._ap_start_delay_sec = 0.0
        self._ap_start_timer: Optional[Timer] = None

        self._tts_pub = self.create_publisher(String, self._tts_speak_topic, 10)
        self._timer_start_pub = self.create_publisher(Empty, self._timer_start_topic, 10)
        self._control_pub = self.create_publisher(String, self._control_topic, 10)
        self._ap_control_pub = self.create_publisher(String, self._ap_control_topic, 10)

        self.create_subscription(String, self._asr_topic, self._on_asr, 10)
        self.create_subscription(SitUpCount, self._count_topic, self._on_count, 10)
        self.create_subscription(String, self._start_spoken_notify_topic, self._on_start_spoken, 10)
        self.create_subscription(String, self._ap_status_topic, self._on_auto_position_status, 10)

        self.get_logger().info(
            f"仰卧起坐语音编排：ASR={self._asr_topic}，找位控制={self._ap_control_topic}，"
            f"状态={self._ap_status_topic}"
        )

    @staticmethod
    def _is_auto_position_failed(status: str) -> bool:
        s = (status or "").strip().lower()
        return "failed" in s

    @staticmethod
    def _is_auto_position_ready(status: str) -> bool:
        s = (status or "").strip().lower()
        return s == "ready"

    def _publish_ap_control(self, cmd: str) -> None:
        m = String()
        m.data = cmd
        self._ap_control_pub.publish(m)

    def _on_ap_start_delay_fired(self) -> None:
        if self._ap_start_timer is not None:
            self._ap_start_timer.cancel()
            self._ap_start_timer = None
        if self._state != OrchestratorState.WAITING_POSITION:
            return
        self._publish_ap_control("start")
        self.get_logger().info("已发 auto_position control=start（经 ap_start_delay_sec 延迟，便于先播确认语）")

    def _on_asr(self, msg: String) -> None:
        text = (msg.data or "").strip()
        if not text:
            return
        if self._state != OrchestratorState.IDLE:
            self.get_logger().debug(f"非 IDLE，忽略 ASR：{text!r}")
            return
        if not any(kw in text for kw in self.TRIGGER_KEYWORDS):
            return
        self.get_logger().info(f"开始指令: 「{text}」")
        if self._record_start_pub is not None:
            rs = SessionRecordStart()
            rs.session_id = str(uuid.uuid4())
            rs.stamp = self.get_clock().now().to_msg()
            rs.tag = ""
            self._record_start_pub.publish(rs)
        ack = String()
        ack.data = self._phrase_ack
        self._tts_pub.publish(ack)
        self._state = OrchestratorState.WAITING_POSITION
        self._pose_ready = False
        self._start_spoken = False
        if self._ap_start_timer is not None:
            self._ap_start_timer.cancel()
            self._ap_start_timer = None
        if self._ap_start_delay_sec <= 0.0:
            self._publish_ap_control("start")
        else:
            self._ap_start_timer = self.create_timer(
                self._ap_start_delay_sec, self._on_ap_start_delay_fired
            )

    def _on_auto_position_status(self, msg: String) -> None:
        if self._state != OrchestratorState.WAITING_POSITION:
            return
        raw = msg.data or ""
        if self._is_auto_position_failed(raw):
            self.get_logger().warn(f"找位失败: {raw!r}，播报后回 IDLE")
            no_p = String()
            no_p.data = self._phrase_no_person
            self._tts_pub.publish(no_p)
            self._publish_ap_control("reset")
            self._state = OrchestratorState.IDLE
            return
        if self._is_auto_position_ready(raw):
            self.get_logger().info("找位就绪，启动计数链")
            ctrl = String()
            ctrl.data = "start"
            self._control_pub.publish(ctrl)
            self._state = OrchestratorState.WAITING_POSE
            self._pose_ready = False
            self._start_spoken = False

    def _try_start_timer(self) -> None:
        if self._state != OrchestratorState.WAITING_POSE:
            return
        if not self._start_spoken:
            return
        if self._pose_ready:
            self.get_logger().info("开始计数已播报且人体就绪，启动定时器")
        else:
            self.get_logger().info("开始计数已播报，启动定时器")
        self._timer_start_pub.publish(Empty())
        self._state = OrchestratorState.COUNTING

    def _on_start_spoken(self, msg: String) -> None:
        if self._state != OrchestratorState.WAITING_POSE:
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

        if self._state == OrchestratorState.WAITING_POSE and initialized:
            if not self._pose_ready:
                self.get_logger().info("人体已就绪（等待开始计数播报后再启动定时器）")
            self._pose_ready = True
            self._try_start_timer()

        if self._state == OrchestratorState.COUNTING and state == "STOPPED" and self._last_state != "STOPPED":
            self.get_logger().info("计时结束，编排回 IDLE")
            self._state = OrchestratorState.IDLE

        self._last_initialized = initialized
        self._last_state = state


def main(args=None):
    rclpy.init(args=args)
    node = SitupVoiceOrchestratorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
