#!/usr/bin/env python3
'''
:brief PoseLandmarks -> HumanPose 桥接节点
:desc 订阅 exercise_engine 的 pose_landmarks（与 situp_counter 同源），用 perception_pkg 的
      human_pose_builder 生成 robot_msgs/HumanPose，发布到 /perception/human_pose，
      供 auto_position 使用，避免再开一个摄像头跑 human_pose_node。

:author slt
:date 2026/04/07
:version 1.0.0
'''

from __future__ import annotations

from typing import Any, List, Optional

import rclpy
from rclpy.node import Node
from robot_msgs.msg import HumanPose, PoseLandmarks

from perception_pkg.human_pose_builder import HumanPoseMappingConfig, build_human_pose


class _FakeLandmark:
    '''与 MediaPipe landmark 字段对齐，供 build_human_pose 使用。'''

    __slots__ = ('x', 'y', 'z', 'visibility')

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, visibility: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.visibility = float(visibility)


class _FakeMpLandmarks:
    __slots__ = ('landmark',)

    def __init__(self, landmark: List[_FakeLandmark]):
        self.landmark = landmark


def _landmarks_msg_to_fake(msg: PoseLandmarks) -> Optional[_FakeMpLandmarks]:
    n = len(msg.landmarks)
    if n < 25:
        return None
    pts: List[_FakeLandmark] = []
    for i in range(33):
        if i < n:
            lm = msg.landmarks[i]
            pts.append(_FakeLandmark(lm.x, lm.y, lm.z, lm.visibility))
        else:
            pts.append(_FakeLandmark(0.0, 0.0, 0.0, 0.0))
    return _FakeMpLandmarks(pts)


class HumanPoseBridgeNode(Node):
    '''
    :brief 将 PoseLandmarks 转为 HumanPose 并发布
    '''

    def __init__(self) -> None:
        super().__init__('human_pose_bridge_node')
        self.declare_parameter('pose_landmarks_topic', 'pose_landmarks')
        self.declare_parameter('human_pose_topic', '/perception/human_pose')
        self.declare_parameter('keypoint_visibility_min', 0.5)
        self.declare_parameter('ready_visibility_min', 0.6)
        self.declare_parameter('ready_min_bbox_area', 0.05)
        self.declare_parameter('dy_shoulder_max', 0.15)
        self.declare_parameter('source_tag', 'pose_landmarks_bridge')

        in_topic = str(self.get_parameter('pose_landmarks_topic').value or 'pose_landmarks').strip()
        out_topic = str(self.get_parameter('human_pose_topic').value or '/perception/human_pose').strip()

        self._cfg = HumanPoseMappingConfig(
            keypoint_visibility_min=float(self.get_parameter('keypoint_visibility_min').value),
            ready_visibility_min=float(self.get_parameter('ready_visibility_min').value),
            ready_min_bbox_area=float(self.get_parameter('ready_min_bbox_area').value),
            dy_shoulder_max=float(self.get_parameter('dy_shoulder_max').value),
            source=str(self.get_parameter('source_tag').value or 'pose_landmarks_bridge'),
        )

        self._pub = self.create_publisher(HumanPose, out_topic, 10)
        self.create_subscription(PoseLandmarks, in_topic, self._on_pose, 10)
        self.get_logger().info(f'human_pose_bridge: {in_topic} -> {out_topic}')

    def _on_pose(self, msg: PoseLandmarks) -> None:
        fake = _landmarks_msg_to_fake(msg)
        frame_id = msg.header.frame_id or 'camera'
        stamp = msg.header.stamp
        if fake is None:
            hp = HumanPose()
            hp.header.stamp = stamp
            hp.header.frame_id = frame_id
            hp.detected = False
            hp.ready_pose = False
            hp.trunk_angle = 0.0
            hp.bbox_area = 0.0
            hp.bbox_center_x = 0.5
            hp.source = self._cfg.source
            self._pub.publish(hp)
            return

        hp = build_human_pose(fake, stamp, frame_id, self._cfg)
        self._pub.publish(hp)


def main(args: Optional[Any] = None) -> None:
    rclpy.init(args=args)
    node = HumanPoseBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
