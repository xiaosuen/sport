#!/usr/bin/env python3
'''
:brief 姿态检测节点
:desc 使用 MediaPipe 检测人体姿态，发布关键点数据（robot_msgs/PoseLandmarks）。

:author slt&zxh
:date 2026/03/03
:version 1.0.2
:history
    1.0.0 - 2026/03/03
        :brief 初始版本
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
    1.0.2 - 2026/06/05
        :brief 新增推理时延计时与日志
        :desc _process_frame 中对 self.pose.process() 做 monotonic 计时，
              发布至 pose_inference_ms（Float32），每 100 帧 INFO 日志输出
              当前推理时延和平滑 FPS，节点销毁时输出汇总。
'''

import signal
import atexit
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Float32
from cv_bridge import CvBridge
import cv2
import mediapipe as mp

from robot_msgs.msg import Landmark, PoseLandmarks
from robot_msgs.msg import VideoStats

# 模块级：记录已打开的摄像头，以便进程被 SIGTERM 杀死时也能释放（launch 失败时不会走 destroy_node）
_video_captures = []


def _release_all_captures():
    """释放所有已登记的 VideoCapture，避免 /dev/video0 被占用导致下次 launch 失败。"""
    global _video_captures
    for cap in _video_captures:
        try:
            cap.release()
        except Exception:
            pass
    _video_captures.clear()


def _signal_cleanup(signum, frame):
    """SIGTERM/SIGINT 时先释放摄像头再退出，便于 launch 失败后再次启动。"""
    _release_all_captures()
    raise KeyboardInterrupt()


class PoseDetectorNode(Node):
    '''
    :brief 姿态检测节点类
    :desc 订阅摄像头图像，使用 MediaPipe 检测姿态，发布关键点。
    '''

    # 姿态关键点索引定义（共33个）
    POSE_LANDMARK_NOSE = 0
    POSE_LANDMARK_LEFT_SHOULDER = 11
    POSE_LANDMARK_RIGHT_SHOULDER = 12
    POSE_LANDMARK_LEFT_ELBOW = 13
    POSE_LANDMARK_RIGHT_ELBOW = 14
    POSE_LANDMARK_LEFT_WRIST = 15
    POSE_LANDMARK_RIGHT_WRIST = 16
    POSE_LANDMARK_LEFT_HIP = 23
    POSE_LANDMARK_RIGHT_HIP = 24
    POSE_LANDMARK_LEFT_KNEE = 25
    POSE_LANDMARK_RIGHT_KNEE = 26
    POSE_LANDMARK_LEFT_ANKLE = 27
    POSE_LANDMARK_RIGHT_ANKLE = 28

    def __init__(self):
        """
        :brief 构造函数
        :desc 初始化节点、发布者和MediaPipe姿态检测器
        """
        super().__init__('pose_detector_node')

        # 声明参数
        self.declare_parameter('camera_id', 0)
        self.declare_parameter('use_image_topic', '')
        self.declare_parameter('publish_rate', 30.0)
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('min_tracking_confidence', 0.5)
        self.declare_parameter('fps_smoothing', 0.2)
        self.declare_parameter('stats_topic', '/pose_video_stats')
        self.declare_parameter('source_image_topic', '/pose_image')

        # 获取参数
        self.camera_id = self.get_parameter('camera_id').value
        self.use_image_topic = str(self.get_parameter('use_image_topic').value).strip()
        self.publish_rate = self.get_parameter('publish_rate').value
        self.min_detection_confidence = self.get_parameter('min_detection_confidence').value
        self.min_tracking_confidence = self.get_parameter('min_tracking_confidence').value
        self.fps_smoothing = float(self.get_parameter('fps_smoothing').value)
        if self.fps_smoothing < 0.0:
            self.fps_smoothing = 0.0
        if self.fps_smoothing > 1.0:
            self.fps_smoothing = 1.0
        self.stats_topic = str(self.get_parameter('stats_topic').value).strip() or '/pose_video_stats'
        self.source_image_topic = str(self.get_parameter('source_image_topic').value).strip() or '/pose_image'

        # 创建发布者
        self.pose_pub = self.create_publisher(PoseLandmarks, 'pose_landmarks', 10)
        self.image_pub = self.create_publisher(Image, 'pose_image', 10)
        self.stats_pub = self.create_publisher(VideoStats, self.stats_topic, 10)
        self.inference_pub = self.create_publisher(Float32, 'pose_inference_ms', 10)
        self._smoothed_inference_ms = 0.0
        self._frame_count = 0

        # CV桥接器
        self.bridge = CvBridge()

        # 初始化MediaPipe
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils
        self.pose = self.mp_pose.Pose(
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence
        )

        self.cap = None
        self._last_frame_time = None
        self._smoothed_fps = 0.0
        if self.use_image_topic:
            # 模式：订阅图像话题（如 /image_raw），不打开摄像头。与 v4l2_camera 配合使用。
            self.image_sub = self.create_subscription(
                Image,
                self.use_image_topic,
                self.image_callback,
                10
            )
            self.get_logger().info(
                f'姿态检测节点已启动，订阅图像话题: {self.use_image_topic}（不打开摄像头）'
            )
        else:
            # 模式：直接打开摄像头；失败时先 release 再抛错，避免占用设备
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                self.get_logger().error(f'无法打开摄像头 {self.camera_id}')
                self.cap.release()
                self.cap = None
                raise RuntimeError(f'无法打开摄像头 {self.camera_id}')
            _video_captures.append(self.cap)
            self.get_logger().info(f'姿态检测节点已启动，使用摄像头 {self.camera_id}')
            timer_period = 1.0 / self.publish_rate
            self.timer = self.create_timer(timer_period, self.timer_callback)

    def timer_callback(self):
        """
        :brief 定时器回调函数（仅在使用摄像头时）
        :desc 读取摄像头帧，检测姿态，发布关键点数据
        """
        if self.cap is None:
            return
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn('无法读取摄像头帧')
            return
        self._process_frame(frame)

    def image_callback(self, msg):
        """
        :brief 图像话题回调（当 use_image_topic 时）
        :desc 将 ROS 图像转为 OpenCV 帧后检测姿态并发布
        """
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().warn(f'图像转换失败: {e}')
            return
        self._process_frame(frame, msg.header)

    def _process_frame(self, frame, header=None):
        """
        :brief 对一帧做姿态检测并发布
        :param frame: BGR 图像
        :param header: 可选，用于发布时沿用时间戳
        """
        # 转换为RGB
        self._update_fps()
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 检测姿态（计时推理时延）
        t0 = time.monotonic()
        results = self.pose.process(frame_rgb)
        t1 = time.monotonic()
        inference_ms = (t1 - t0) * 1000.0

        # 发布推理时延（平滑后）
        if self._smoothed_inference_ms <= 0.0:
            self._smoothed_inference_ms = inference_ms
        else:
            self._smoothed_inference_ms = (
                (1.0 - self.fps_smoothing) * self._smoothed_inference_ms
                + self.fps_smoothing * inference_ms
            )
        self.inference_pub.publish(Float32(data=float(inference_ms)))

        # 每 100 帧打印一次推理时延和 FPS
        self._frame_count += 1
        if self._frame_count % 100 == 0:
            self.get_logger().info(
                f'[Frame {self._frame_count}] '
                f'inference={inference_ms:.1f}ms (smooth={self._smoothed_inference_ms:.1f}ms), '
                f'fps={self._smoothed_fps:.1f}'
            )

        # 绘制姿态
        if results.pose_landmarks:
            self.mp_drawing.draw_landmarks(
                frame,
                results.pose_landmarks,
                self.mp_pose.POSE_CONNECTIONS
            )

            # 发布关键点数据
            landmarks_msg = self._create_landmarks_msg(results.pose_landmarks)
            if header is not None:
                landmarks_msg.header = header
            self.pose_pub.publish(landmarks_msg)

        # 发布图像
        image_msg = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        if header is not None:
            image_msg.header = header
        else:
            image_msg.header.stamp = self.get_clock().now().to_msg()
            image_msg.header.frame_id = 'camera'
        self.image_pub.publish(image_msg)
        self._publish_video_stats(image_msg.header)

    def _update_fps(self):
        """根据相邻帧间隔计算平滑 FPS。"""
        now = time.monotonic()
        if self._last_frame_time is None:
            self._last_frame_time = now
            return

        dt = now - self._last_frame_time
        self._last_frame_time = now
        if dt <= 0.0:
            return

        instant_fps = 1.0 / dt
        if self._smoothed_fps <= 0.0:
            self._smoothed_fps = instant_fps
            return

        alpha = self.fps_smoothing
        self._smoothed_fps = (1.0 - alpha) * self._smoothed_fps + alpha * instant_fps

    def _publish_video_stats(self, header):
        msg = VideoStats()
        msg.header = header
        msg.fps = float(self._smoothed_fps)
        msg.source_topic = self.source_image_topic
        self.stats_pub.publish(msg)

    def _create_landmarks_msg(self, mp_landmarks):
        """
        :brief 创建关键点消息
        :desc 将MediaPipe关键点转换为ROS消息
        :param mp_landmarks: MediaPipe关键点数据
        :return: PoseLandmarks消息
        """
        msg = PoseLandmarks()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera'

        for lm in mp_landmarks.landmark:
            landmark = Landmark()
            landmark.x = lm.x
            landmark.y = lm.y
            landmark.z = lm.z
            landmark.visibility = lm.visibility
            msg.landmarks.append(landmark)

        return msg

    def destroy_node(self):
        """
        :brief 销毁节点
        :desc 释放资源
        """
        if self.cap is not None:
            try:
                if self.cap in _video_captures:
                    _video_captures.remove(self.cap)
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.get_logger().info(
            f'节点销毁，共处理 {self._frame_count} 帧，'
            f'最终平滑推理时延={self._smoothed_inference_ms:.1f}ms，'
            f'平滑 FPS={self._smoothed_fps:.1f}'
        )
        self.pose.close()
        super().destroy_node()


def main(args=None):
    """
    :brief 主函数
    :desc 节点入口；注册 SIGTERM/SIGINT 与 atexit，确保 launch 杀死进程时也释放摄像头。
    """
    # launch 中其它节点失败时会发 SIGTERM，若不释放摄像头会导致 /dev/video0 is busy
    signal.signal(signal.SIGTERM, _signal_cleanup)
    signal.signal(signal.SIGINT, _signal_cleanup)
    atexit.register(_release_all_captures)

    rclpy.init(args=args)
    node = PoseDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
