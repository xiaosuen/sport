#!/usr/bin/env python3
'''
:brief TTS 语音播报节点
:desc 订阅 std_msgs/String（默认 /voice/speak），将文本送入 Piper / espeak 播报队列顺序播放。
     话题名可通过 ROS 参数 speak_topic 修改。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从旧 tts 逻辑迁入 voice_pkg
'''

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from voice_pkg.tts.tts_speak import configure_tts_from_node, speak


class VoiceTtsNode(Node):
    '''
    :brief TTS ROS2 节点
    :desc 仅负责订阅与调用 tts_speak.speak；实际播放在后台线程执行。
    '''

    def __init__(self):
        super().__init__("voice_tts")

        self.declare_parameter("speak_topic", "/voice/speak")
        speak_topic = self.get_parameter("speak_topic").get_parameter_value().string_value
        if not speak_topic:
            speak_topic = "/voice/speak"

        tts_kind = configure_tts_from_node(self)
        self.create_subscription(String, speak_topic, self._on_speak, 10)
        self.get_logger().info(f"TTS 节点已启动，后端={tts_kind}，订阅: {speak_topic}")

    def _on_speak(self, msg: String) -> None:
        '''
        :brief 收到字符串后入队播报
        :param msg: std_msgs/String，data 为空或纯空白则忽略
        '''
        text = (msg.data or "").strip()
        if not text:
            return
        self.get_logger().info(f"播报: {text}")
        speak(text)


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选，传递给 rclpy.init
    '''
    rclpy.init(args=args)
    node = VoiceTtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
