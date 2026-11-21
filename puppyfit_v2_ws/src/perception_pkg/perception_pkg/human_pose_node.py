#!/usr/bin/env python3
'''
:brief HumanPose 感知节点
:desc 订阅图像或本地摄像头，MediaPipe Pose，发布 /perception/human_pose；
     可选 /perception/debug_image（ROS 话题，非桌面窗口）；可选 show_debug_window 用 OpenCV 弹窗。
     无检测时仍发布 HumanPose（detected=false 等）。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.0 - 2026/03/28
        :brief perception_pkg 人体姿态节点
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 补充 :history 与版本号
'''

import atexit
import signal
import sys

import cv2
import mediapipe as mp
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from robot_msgs.msg import HumanPose
from sensor_msgs.msg import Image

from perception_pkg.human_pose_builder import HumanPoseMappingConfig, build_human_pose

_video_captures: list = []


def _release_all_captures() -> None:
    global _video_captures
    for cap in _video_captures:
        try:
            cap.release()
        except Exception:
            pass
    _video_captures.clear()


def _signal_cleanup(signum, frame):
    _release_all_captures()
    raise KeyboardInterrupt


def _open_video_capture(camera_id: int):
    '''
    :brief 打开摄像头
    :desc Linux 上优先 CAP_V4L2，避免 OpenCV 默认走 GStreamer 时出现多余告警且占用失败难排查。
    '''
    if sys.platform.startswith('linux'):
        cap = cv2.VideoCapture(camera_id, cv2.CAP_V4L2)
        if cap.isOpened():
            return cap
        cap.release()
    cap = cv2.VideoCapture(camera_id)
    if cap.isOpened():
        return cap
    cap.release()
    return None


class HumanPoseNode(Node):
    '''
    :brief 感知节点：图像输入 + MediaPipe + HumanPose
    '''

    def __init__(self):
        super().__init__('human_pose_node')

        self.declare_parameter('image_topic', '')
        self.declare_parameter('camera_id', 0)
        self.declare_parameter('camera_frame_id', 'camera_optical_frame')
        self.declare_parameter('publish_rate', 30.0)
        self.declare_parameter('publish_debug_image', False)
        self.declare_parameter('show_debug_window', False)
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('min_tracking_confidence', 0.5)
        self.declare_parameter('keypoint_visibility_min', 0.5)
        self.declare_parameter('ready_visibility_min', 0.6)
        self.declare_parameter('ready_min_bbox_area', 0.05)
        self.declare_parameter('dy_shoulder_max', 0.15)

        self._image_topic = str(self.get_parameter('image_topic').value or '').strip()
        self._camera_id = int(self.get_parameter('camera_id').value)
        self._camera_frame_id = str(
            self.get_parameter('camera_frame_id').value or 'camera_optical_frame'
        )
        self._publish_rate = float(self.get_parameter('publish_rate').value)
        pd = self.get_parameter('publish_debug_image').value
        self._publish_debug = pd in (True, 'true', 'True', '1', 1)
        sw = self.get_parameter('show_debug_window').value
        self._show_debug_window = sw in (True, 'true', 'True', '1', 1)
        self._imshow_warned = False

        self._mapping_cfg = HumanPoseMappingConfig(
            keypoint_visibility_min=float(self.get_parameter('keypoint_visibility_min').value),
            ready_visibility_min=float(self.get_parameter('ready_visibility_min').value),
            ready_min_bbox_area=float(self.get_parameter('ready_min_bbox_area').value),
            dy_shoulder_max=float(self.get_parameter('dy_shoulder_max').value),
        )

        md = float(self.get_parameter('min_detection_confidence').value)
        mt = float(self.get_parameter('min_tracking_confidence').value)

        self._human_pose_pub = self.create_publisher(HumanPose, '/perception/human_pose', 10)
        self._debug_pub = None
        if self._publish_debug:
            self._debug_pub = self.create_publisher(Image, '/perception/debug_image', 10)

        self._bridge = CvBridge()
        self._mp_pose = mp.solutions.pose
        self._mp_drawing = mp.solutions.drawing_utils
        self._pose = self._mp_pose.Pose(
            min_detection_confidence=md,
            min_tracking_confidence=mt,
        )

        self._cap = None
        self._timer = None

        if self._image_topic:
            self.create_subscription(Image, self._image_topic, self._image_callback, 10)
            self.get_logger().info(
                f'订阅图像话题: {self._image_topic}，发布 /perception/human_pose'
            )
        else:
            self._cap = _open_video_capture(self._camera_id)
            if self._cap is None:
                raise RuntimeError(
                    f'无法打开摄像头索引 {self._camera_id}（通常对应 /dev/video{self._camera_id}）。'
                    ' 常见原因：设备已被占用（例如已有一个 human_pose_node/v4l2_camera/浏览器在使用同一设备）、'
                    '或权限不足。排查：在终端执行 `fuser -v /dev/video0` 查看占用 PID。'
                    ' 解决：结束占用进程后重试；或让相机只被一个节点打开，本节点改订阅图像，例如：'
                    ' ros2 launch perception_pkg perception.launch.py image_topic:=/image_raw'
                )
            _video_captures.append(self._cap)
            period = 1.0 / self._publish_rate if self._publish_rate > 0 else 0.033
            self._timer = self.create_timer(period, self._timer_callback)
            self.get_logger().info(
                f'使用摄像头 {self._camera_id}，{self._publish_rate} Hz，发布 /perception/human_pose'
            )

        if self._publish_debug:
            self.get_logger().info('已启用 /perception/debug_image')
        if self._show_debug_window:
            self.get_logger().info(
                '已启用 OpenCV 调试窗口（窗口名 perception_human_pose_debug）；'
                '需本机图形环境或 X11 转发，否则请用 rqt_image_view 订阅 /perception/debug_image'
            )

    def _maybe_imshow(self, bgr) -> None:
        if not self._show_debug_window:
            return
        try:
            cv2.imshow('perception_human_pose_debug', bgr)
            cv2.waitKey(1)
        except cv2.error as e:
            if not self._imshow_warned:
                self.get_logger().warn(
                    f'无法显示调试窗口（常见于无 DISPLAY 或纯 SSH）：{e}；'
                    '可改用: ros2 run rqt_image_view rqt_image_view --ros-args -r image:=/perception/debug_image'
                )
                self._imshow_warned = True

    def _timer_callback(self):
        if self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok:
            self.get_logger().warn('无法读取摄像头帧')
            return
        stamp = self.get_clock().now().to_msg()
        self._process_frame(frame, stamp, self._camera_frame_id)

    def _image_callback(self, msg: Image):
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().warn(f'图像转换失败: {e}')
            return
        self._process_frame(frame, msg.header.stamp, msg.header.frame_id or self._camera_frame_id)

    def _process_frame(self, frame, stamp, frame_id: str):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(frame_rgb)

        mp_lm = results.pose_landmarks
        hp = build_human_pose(mp_lm, stamp, frame_id, self._mapping_cfg)
        self._human_pose_pub.publish(hp)

        need_debug_vis = self._publish_debug or self._show_debug_window
        if need_debug_vis:
            dbg = frame.copy()
            if mp_lm:
                self._mp_drawing.draw_landmarks(
                    dbg,
                    mp_lm,
                    self._mp_pose.POSE_CONNECTIONS,
                )
            if self._publish_debug and self._debug_pub is not None:
                out = self._bridge.cv2_to_imgmsg(dbg, encoding='bgr8')
                out.header.stamp = stamp
                out.header.frame_id = frame_id
                self._debug_pub.publish(out)
            self._maybe_imshow(dbg)

    def destroy_node(self):
        if self._cap is not None:
            try:
                if self._cap in _video_captures:
                    _video_captures.remove(self._cap)
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._pose.close()
        if self._show_debug_window:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    signal.signal(signal.SIGTERM, _signal_cleanup)
    signal.signal(signal.SIGINT, _signal_cleanup)
    atexit.register(_release_all_captures)

    rclpy.init(args=args)
    node = HumanPoseNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except Exception:
                pass


if __name__ == '__main__':
    main()
