#!/usr/bin/env python3
'''
:brief 实时监控 WebSocket 上报节点
:desc 订阅图像与计数，按后端契约推送 JSON；enable_monitor_ws=false 时不建连、不启线程。
     配置仅依赖 backend_config 中 ws_camera_base_url 与 device_id，与 exercise_engine_pkg 解耦。

:author slt
:date 2026/04/02
:version 1.0.1
:history
    1.0.1 - 2026/04/02
        :brief 置于 bridge_pkg.monitor.node（可执行名仍为 monitor_ws_bridge）
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from __future__ import annotations

import base64
import threading
from typing import List, Optional

import rclpy
from rclpy.node import Node
from robot_msgs.msg import SitUpCount
from sensor_msgs.msg import Image

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH
from bridge_pkg.monitor.config_min import MonitorConfigError, load_ws_camera_and_device_id
from bridge_pkg.monitor.ws_reporter import MonitorWsReporter

try:
    from cv_bridge import CvBridge
except ImportError:
    CvBridge = None  # type: ignore

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore


def _ros_param_bool(value: object) -> bool:
    '''
    :brief 将 launch/参数中的布尔兼容字符串解析为 bool
    :param value: ROS 参数原始值
    :return 布尔结果
    '''
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


class MonitorWsNode(Node):
    '''
    :brief 监控 WebSocket ROS2 桥接节点
    :desc 可选启用；启用时连接后端 /ws/camera/{device_id} 并周期上报 frame/heartbeat。
    '''

    def __init__(self) -> None:
        super().__init__("monitor_ws_bridge")
        self._reporter: Optional[MonitorWsReporter] = None

        self.declare_parameter("enable_monitor_ws", False)
        self.declare_parameter("backend_config_path", DEFAULT_BACKEND_CONFIG_PATH)
        self.declare_parameter("ws_camera_base_url", "")
        self.declare_parameter("device_id", "")
        self.declare_parameter("image_topic", "/pose_image")
        self.declare_parameter("count_topic", "/situp_count")
        self.declare_parameter("push_interval_sec", 0.25)
        self.declare_parameter("push_jpeg", True)
        self.declare_parameter("jpeg_quality", 80)
        self.declare_parameter("heartbeat_interval_sec", 30.0)
        self.declare_parameter("reconnect_backoff_initial_sec", 1.0)
        self.declare_parameter("reconnect_backoff_max_sec", 60.0)

        enable = _ros_param_bool(self.get_parameter("enable_monitor_ws").value)
        if not enable:
            self.get_logger().info("enable_monitor_ws=false，监控 WebSocket 未启动（零连接）")
            return

        cfg_path = str(self.get_parameter("backend_config_path").value).strip()
        url_override = str(self.get_parameter("ws_camera_base_url").value).strip()
        did_override = str(self.get_parameter("device_id").value).strip()

        try:
            if url_override and did_override:
                ws_base, device_id = url_override, did_override
            elif url_override or did_override:
                self.get_logger().error("ws_camera_base_url 与 device_id 须同时覆盖或同时留空，从配置文件读取")
                self._reporter = None
                return
            else:
                ws_base, device_id = load_ws_camera_and_device_id(
                    cfg_path if cfg_path else ""
                )
        except MonitorConfigError as exc:
            self.get_logger().error(f"监控配置失败: {exc}")
            self._reporter = None
            return

        ws_url = f"{ws_base.rstrip('/')}/{device_id}"
        image_topic = str(self.get_parameter("image_topic").value).strip() or "/pose_image"
        count_topic = str(self.get_parameter("count_topic").value).strip() or "/situp_count"
        push_interval = float(self.get_parameter("push_interval_sec").value)
        push_jpeg = _ros_param_bool(self.get_parameter("push_jpeg").value)
        jpeg_q = int(self.get_parameter("jpeg_quality").value)
        hb_sec = float(self.get_parameter("heartbeat_interval_sec").value)
        bo_init = float(self.get_parameter("reconnect_backoff_initial_sec").value)
        bo_max = float(self.get_parameter("reconnect_backoff_max_sec").value)

        self._device_id = device_id
        self._count_lock = threading.Lock()
        self._count = 0
        self._jpeg_lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._push_jpeg = push_jpeg and bool(cv2) and bool(CvBridge)
        self._jpeg_quality = max(1, min(100, jpeg_q))
        self._bridge: Optional[object] = CvBridge() if CvBridge else None

        if push_jpeg and not self._push_jpeg:
            self.get_logger().warning(
                "未安装 cv_bridge 或 OpenCV，监控将只上报 count、不附带 frame（JPEG）"
            )

        self.create_subscription(SitUpCount, count_topic, self._on_count, 10)
        if self._push_jpeg:
            self.create_subscription(Image, image_topic, self._on_image, 5)

        def _frame_payload() -> dict:
            with self._count_lock:
                c = int(self._count)
            out: dict = {
                "type": "frame",
                "device_id": self._device_id,
                "count": c,
            }
            if self._push_jpeg:
                with self._jpeg_lock:
                    jpeg = self._latest_jpeg
                out["frame"] = (
                    base64.standard_b64encode(jpeg).decode("ascii") if jpeg else None
                )
            else:
                out["frame"] = None
            return out

        self._reporter = MonitorWsReporter(
            ws_url=ws_url,
            device_id=device_id,
            push_interval_sec=push_interval,
            get_frame_payload=_frame_payload,
            logger=self.get_logger(),
            heartbeat_interval_sec=hb_sec,
            reconnect_backoff_initial_sec=bo_init,
            reconnect_backoff_max_sec=bo_max,
        )
        self._reporter.start()
        self.get_logger().info(
            f"监控 WebSocket 已启动: {ws_url} 图像={image_topic} 计数={count_topic} push_jpeg={self._push_jpeg}"
        )

    def _on_count(self, msg) -> None:
        with self._count_lock:
            self._count = int(msg.count)

    def _on_image(self, msg: Image) -> None:
        if not self._bridge or not cv2:
            return
        try:
            img = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            ok, buf = cv2.imencode(
                ".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
            )
            if ok:
                with self._jpeg_lock:
                    self._latest_jpeg = buf.tobytes()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().debug(f"图像转 JPEG 失败: {exc}")

    def destroy_node(self) -> bool:
        if self._reporter is not None:
            self._reporter.stop()
            self._reporter = None
        return super().destroy_node()


def main(args: Optional[List[str]] = None) -> None:
    '''
    :brief 可执行入口：创建节点并 spin
    :param args: 可选，传入 rclpy.init 的命令行参数
    '''
    rclpy.init(args=args)
    node = MonitorWsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
