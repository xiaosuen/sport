#!/usr/bin/env python3
'''
:brief 运动画面叠字节点
:desc 订阅视频帧、计数状态、FPS 状态，将文本叠加后发布新图像话题。

:author copilot
:date 2026/04/27
:version 1.0.0
'''

from __future__ import annotations

import threading

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image

from robot_msgs.msg import SitUpCount, VideoStats


class VideoOverlayNode(Node):
    '''
    :brief 叠字节点
    :desc 将 /situp_count 与 /pose_video_stats 的最近值叠加到图像上。
    '''

    def __init__(self) -> None:
        super().__init__('video_overlay_node')

        self.declare_parameter('input_image_topic', '/pose_image')
        self.declare_parameter('output_image_topic', '/pose_image_overlay')
        self.declare_parameter('count_topic', '/situp_count')
        self.declare_parameter('stats_topic', '/pose_video_stats')
        self.declare_parameter('show_fps', True)
        self.declare_parameter('show_state', True)
        self.declare_parameter('show_count', True)
        self.declare_parameter('font_scale', 0.8)
        self.declare_parameter('line_height', 34)
        self.declare_parameter('origin_x', 20)
        self.declare_parameter('origin_y', 36)
        self.declare_parameter('thickness', 2)

        self._input_image_topic = str(self.get_parameter('input_image_topic').value).strip() or '/pose_image'
        self._output_image_topic = str(self.get_parameter('output_image_topic').value).strip() or '/pose_image_overlay'
        self._count_topic = str(self.get_parameter('count_topic').value).strip() or '/situp_count'
        self._stats_topic = str(self.get_parameter('stats_topic').value).strip() or '/pose_video_stats'

        self._show_fps = bool(self.get_parameter('show_fps').value)
        self._show_state = bool(self.get_parameter('show_state').value)
        self._show_count = bool(self.get_parameter('show_count').value)
        self._font_scale = float(self.get_parameter('font_scale').value)
        self._line_height = int(self.get_parameter('line_height').value)
        self._origin_x = int(self.get_parameter('origin_x').value)
        self._origin_y = int(self.get_parameter('origin_y').value)
        self._thickness = int(self.get_parameter('thickness').value)

        self._bridge = CvBridge()
        self._state_lock = threading.Lock()
        self._latest_count = 0
        self._latest_state = 'UNKNOWN'
        self._latest_fps = 0.0

        self._image_pub = self.create_publisher(Image, self._output_image_topic, 10)

        self.create_subscription(SitUpCount, self._count_topic, self._on_count, 10)
        self.create_subscription(VideoStats, self._stats_topic, self._on_stats, 10)
        self.create_subscription(Image, self._input_image_topic, self._on_image, 10)

        self.get_logger().info(
            '视频叠字节点已启动：input=%s output=%s count=%s stats=%s'
            % (
                self._input_image_topic,
                self._output_image_topic,
                self._count_topic,
                self._stats_topic,
            )
        )

    def _on_count(self, msg: SitUpCount) -> None:
        with self._state_lock:
            self._latest_count = int(msg.count)
            self._latest_state = str(msg.state)

    def _on_stats(self, msg: VideoStats) -> None:
        with self._state_lock:
            self._latest_fps = float(msg.fps)

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception:
            return

        with self._state_lock:
            count = self._latest_count
            state = self._latest_state
            fps = self._latest_fps

        lines: list[str] = []
        if self._show_fps:
            lines.append(f'FPS: {fps:.1f}')
        if self._show_state:
            lines.append(f'STATE: {state}')
        if self._show_count:
            lines.append(f'COUNT: {count}')

        y = self._origin_y
        for line in lines:
            cv2.putText(
                frame,
                line,
                (self._origin_x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                self._font_scale,
                (0, 0, 0),
                self._thickness + 2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                line,
                (self._origin_x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                self._font_scale,
                (255, 255, 255),
                self._thickness,
                cv2.LINE_AA,
            )
            y += self._line_height

        out_msg = self._bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        out_msg.header = msg.header
        self._image_pub.publish(out_msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VideoOverlayNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
