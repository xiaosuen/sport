#!/usr/bin/env python3
'''
:brief 仰卧起坐成绩口播节点
:desc 订阅 counting_tts 在 phrase_end（计时结束）播报**完成后**发出的 Empty（默认话题 situp/voice/phrase_end_done），
      再延迟 result_delay_sec（默认 0.1s）后向 tts/speak 队列提交成绩文案；同时订阅 situp_count 以缓存最新 count。
      与 plan_2：先 counting_tts「计时结束」，再间隔 100ms，再播成绩。

:author slt
:date 2026/04/10
:version 1.0.0
'''

from __future__ import annotations

import rclpy
from rclpy.node import Node
from robot_msgs.msg import SitUpCount
from std_msgs.msg import Empty

from voice_pkg.tts.tts_speak import configure_tts_from_node, speak


class SitupResultTtsNode(Node):
    '''
    :brief phrase_end 完成后再延迟播报成绩的节点
    '''

    def __init__(self) -> None:
        super().__init__("situp_result_tts")

        self.declare_parameter("count_topic", "situp_count")
        self.declare_parameter("phrase_end_done_topic", "situp/voice/phrase_end_done")
        self.declare_parameter("result_delay_sec", 0.1)
        self.declare_parameter("phrase_result_template", "你的仰卧起坐成绩是 {count} 个")
        self.declare_parameter("exercise_name", "仰卧起坐")

        self._count_topic = (
            self.get_parameter("count_topic").get_parameter_value().string_value or "situp_count"
        )
        _done_topic = (
            self.get_parameter("phrase_end_done_topic").get_parameter_value().string_value or ""
        ).strip()
        self._phrase_end_done_topic = _done_topic or "situp/voice/phrase_end_done"
        try:
            self._result_delay_sec = float(self.get_parameter("result_delay_sec").value)
        except (TypeError, ValueError):
            self._result_delay_sec = 0.1
        if self._result_delay_sec < 0.0:
            self._result_delay_sec = 0.0

        self._template = (
            self.get_parameter("phrase_result_template").get_parameter_value().string_value
            or "你的仰卧起坐成绩是 {count} 个"
        )
        self._exercise_name = (
            self.get_parameter("exercise_name").get_parameter_value().string_value or "仰卧起坐"
        )

        self._last_count = 0
        self._result_timer = None

        configure_tts_from_node(self)

        self.create_subscription(SitUpCount, self._count_topic, self._on_count, 10)
        self.create_subscription(Empty, self._phrase_end_done_topic, self._on_phrase_end_done, 10)

        self.get_logger().info(
            f"成绩 TTS：订阅 {self._count_topic}、{self._phrase_end_done_topic}，"
            f"延迟 {self._result_delay_sec}s 后播模板「{self._template}」"
        )

    def _on_count(self, msg: SitUpCount) -> None:
        self._last_count = int(msg.count)

    def _cancel_result_timer(self) -> None:
        if self._result_timer is not None:
            self._result_timer.cancel()
            self._result_timer = None

    def _on_phrase_end_done(self, _msg: Empty) -> None:
        self._cancel_result_timer()
        if self._result_delay_sec <= 0.0:
            self._speak_result()
            return
        self._result_timer = self.create_timer(self._result_delay_sec, self._on_delay_elapsed)

    def _on_delay_elapsed(self) -> None:
        self._cancel_result_timer()
        self._speak_result()

    def _speak_result(self) -> None:
        try:
            text = self._template.format(count=self._last_count)
        except (KeyError, ValueError) as e:
            self.get_logger().error(f"phrase_result_template 格式化失败: {e}")
            text = f"你的仰卧起坐成绩是 {self._last_count} 个"
        self.get_logger().info(f"成绩播报（{self._exercise_name}）: {text}")
        speak(text, lang="zh")


def main(args=None):
    rclpy.init(args=args)
    node = SitupResultTtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
