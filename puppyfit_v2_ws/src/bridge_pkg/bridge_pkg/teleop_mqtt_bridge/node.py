'''
:brief 云遥控 MQTT → ROS2（puppy_control_msgs / geometry_msgs）
:desc 订阅 puppy/control/{device_id}/teleop，解析与后端 /api/device/{id}/teleop 一致的 JSON，
      经 seq 去重（含空闲 TTL 后重置）、超时停速后发布至 /puppy_control/velocity_move、
      /puppy_control/pose、/cmd_vel_nav。建议在独立终端或与手柄分时互锁使用。

:author slt
:date 2026/04/26
:version 1.0.0
'''

from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import paho.mqtt.client as mqtt
import rclpy
from geometry_msgs.msg import Twist
from puppy_control_msgs.msg import Pose, Velocity
from rclpy.node import Node

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def _read_json_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except OSError:
        return {}


def _parse_optional_int(text: str) -> Optional[int]:
    raw = (text or '').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_optional_bool(text: str) -> Optional[bool]:
    raw = (text or '').strip().lower()
    if not raw:
        return None
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    if raw in ('0', 'false', 'no', 'off'):
        return False
    return None


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _i(x: Any) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


class TeleopMqttBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__('teleop_mqtt_bridge')

        self.declare_parameter('backend_config_path', DEFAULT_BACKEND_CONFIG_PATH)
        self.declare_parameter('device_id', '')
        self.declare_parameter('broker_host', '')
        self.declare_parameter('broker_port', '')
        self.declare_parameter('use_tls', '')
        self.declare_parameter('mqtt_username', '')
        self.declare_parameter('mqtt_password', '')
        self.declare_parameter('mqtt_client_id', '')
        self.declare_parameter('mqtt_qos', 1)
        self.declare_parameter('teleop_topic_template', 'puppy/control/{device_id}/teleop')

        self.declare_parameter('velocity_move_topic', '/puppy_control/velocity_move')
        self.declare_parameter('pose_topic', '/puppy_control/pose')
        self.declare_parameter('cmd_vel_nav_topic', '/cmd_vel_nav')

        self.declare_parameter('command_hold_sec', 0.3)
        self.declare_parameter('seq_idle_reset_sec', 2.0)
        self.declare_parameter('drain_queue_rate_hz', 50.0)

        self._load_runtime_config()

        vtopic = self._vel_topic
        ptopic = self._pose_topic
        ttopic = self._twist_topic
        self._pub_vel = self.create_publisher(Velocity, vtopic, 10)
        self._pub_pose = self.create_publisher(Pose, ptopic, 10)
        self._pub_twist = self.create_publisher(Twist, ttopic, 10)

        self._lock = threading.Lock()
        self._queue: Deque[Dict[str, Any]] = deque()
        self._last_seq: int = -1
        self._last_cmd_mono: float = 0.0
        self._last_mode: str = 'velocity_move'
        self._hold_active: bool = False

        rate = float(
            self.get_parameter('drain_queue_rate_hz').get_parameter_value().double_value
        )
        rate = max(10.0, min(200.0, rate))
        self.create_timer(1.0 / rate, self._on_tick)
        self._setup_mqtt()

    def _load_runtime_config(self) -> None:
        cfg_path = (
            self.get_parameter('backend_config_path').get_parameter_value().string_value
            or DEFAULT_BACKEND_CONFIG_PATH
        )
        cfg = _read_json_file(cfg_path)
        mqtt_cfg = cfg.get('mqtt', {}) if isinstance(cfg.get('mqtt', {}), dict) else {}
        device_cfg = cfg.get('device', {}) if isinstance(cfg.get('device', {}), dict) else {}

        device_id_override = self.get_parameter('device_id').get_parameter_value().string_value.strip()
        self._device_id = device_id_override or str(device_cfg.get('device_id', 'puppy_001')).strip() or 'puppy_001'

        host_override = self.get_parameter('broker_host').get_parameter_value().string_value.strip()
        self._broker_host = host_override or str(mqtt_cfg.get('broker_host', 'localhost')).strip() or 'localhost'

        port_override = _parse_optional_int(
            self.get_parameter('broker_port').get_parameter_value().string_value
        )
        self._broker_port = int(port_override if port_override is not None else mqtt_cfg.get('broker_port', 1883))

        tls_override = _parse_optional_bool(
            self.get_parameter('use_tls').get_parameter_value().string_value
        )
        self._use_tls = bool(mqtt_cfg.get('use_tls', False) if tls_override is None else tls_override)

        qos_raw = self.get_parameter('mqtt_qos').get_parameter_value().integer_value
        self._mqtt_qos = max(0, min(2, int(qos_raw)))

        user_override = self.get_parameter('mqtt_username').get_parameter_value().string_value.strip()
        pass_override = self.get_parameter('mqtt_password').get_parameter_value().string_value
        user_env_name = str(mqtt_cfg.get('username_env', 'PUPPY_MQTT_USER')).strip()
        pass_env_name = str(mqtt_cfg.get('password_env', 'PUPPY_MQTT_PASS')).strip()
        self._mqtt_user = user_override or os.getenv(user_env_name, '').strip() or os.getenv('PUPPY_MQTT_USER', '').strip()
        self._mqtt_pass = pass_override or os.getenv(pass_env_name, '') or os.getenv('PUPPY_MQTT_PASS', '')

        client_id_override = self.get_parameter('mqtt_client_id').get_parameter_value().string_value.strip()
        self._mqtt_client_id = client_id_override or f'teleop_mqtt_{self._device_id}'

        ttpl = self.get_parameter('teleop_topic_template').get_parameter_value().string_value
        self._mqtt_teleop_topic = ttpl.replace('{device_id}', self._device_id)

        self._vel_topic = self.get_parameter('velocity_move_topic').get_parameter_value().string_value or (
            '/puppy_control/velocity_move'
        )
        self._pose_topic = self.get_parameter('pose_topic').get_parameter_value().string_value or (
            '/puppy_control/pose'
        )
        self._twist_topic = self.get_parameter('cmd_vel_nav_topic').get_parameter_value().string_value or (
            '/cmd_vel_nav'
        )

        self._hold_sec = max(0.0, float(
            self.get_parameter('command_hold_sec').get_parameter_value().double_value
        ))
        self._seq_idle_reset_sec = max(0.0, float(
            self.get_parameter('seq_idle_reset_sec').get_parameter_value().double_value
        ))

    def _setup_mqtt(self) -> None:
        if not self._mqtt_pass or not self._mqtt_user:
            self.get_logger().error(
                '未配置 MQTT 用户名/密码，teleop 桥接无法连接。请设 PUPPY_MQTT_USER/PUPPY_MQTT_PASS 或 launch 传参。'
            )
            return
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._mqtt_client_id,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(
                client_id=self._mqtt_client_id,
                protocol=mqtt.MQTTv311,
            )
        client.username_pw_set(self._mqtt_user, self._mqtt_pass)
        if self._use_tls:
            client.tls_set()

        client.on_connect = self._on_mqtt_connect  # type: ignore[method-assign]
        client.on_disconnect = self._on_mqtt_disconnect  # type: ignore[method-assign]
        client.on_message = self._on_mqtt_message  # type: ignore[method-assign]

        self._mqtt: Optional[mqtt.Client] = client
        self._mqtt_connected = False
        try:
            client.connect_async(self._broker_host, self._broker_port, keepalive=60)
            client.loop_start()
        except OSError as exc:
            self.get_logger().error(f'MQTT 连接失败: {exc}')

    def _on_mqtt_connect(self, client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        rc = 0
        if len(args) >= 2:
            rc = args[1]
        elif len(args) == 1:
            rc = args[0]
        if hasattr(rc, 'value'):
            rc = int(rc.value)
        elif not isinstance(rc, int):
            try:
                rc = int(rc)
            except (TypeError, ValueError):
                rc = -1
        if rc != 0:
            self._mqtt_connected = False
            self.get_logger().warning(f'MQTT 连接失败 rc={rc}')
            return
        self._mqtt_connected = True
        client.subscribe(self._mqtt_teleop_topic, qos=self._mqtt_qos)
        self.get_logger().info(f'MQTT 已连接并订阅 {self._mqtt_teleop_topic}')

    def _on_mqtt_disconnect(self, _client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        self._mqtt_connected = False
        self.get_logger().warning('MQTT 已断开')

    def _on_mqtt_message(self, _c: mqtt.Client, _u: Any, msg: mqtt.MQTTMessage) -> None:
        if msg.topic != self._mqtt_teleop_topic:
            return
        try:
            payload_text = msg.payload.decode('utf-8', errors='ignore')
            body = json.loads(payload_text) if payload_text else {}
            if not isinstance(body, dict):
                return
        except (json.JSONDecodeError, OSError) as exc:
            self.get_logger().warning(f'解析 teleop MQTT 消息失败: {exc}')
            return
        with self._lock:
            self._queue.append(body)

    def _accept_seq(self, seq: int, now: float) -> bool:
        if not isinstance(seq, int):
            return False
        if self._seq_idle_reset_sec > 0.0 and self._last_cmd_mono > 0.0:
            if (now - self._last_cmd_mono) >= self._seq_idle_reset_sec:
                self._last_seq = -1
        if seq > self._last_seq:
            return True
        return False

    def _build_pose(self, d: Dict[str, Any]) -> Optional[Pose]:
        # 兼容当前后端：pose 至少要求 pitch + height，其余字段缺省补默认值
        if 'pitch' not in d or 'height' not in d:
            return None

        m = Pose()
        m.roll = _f(d.get('roll', 0.0))
        m.pitch = _clamp(_f(d.get('pitch')), -0.54, 0.54)
        m.yaw = _f(d.get('yaw', 0.0))
        m.height = _clamp(_f(d.get('height')), -15.0, -5.0)
        m.x_shift = _f(d.get('x_shift', 0.0))
        m.stance_x = _f(d.get('stance_x', 0.0))
        m.stance_y = _f(d.get('stance_y', 0.0))
        m.run_time = _i(d.get('run_time', 0))
        return m

    def _build_velocity(self, d: Optional[Dict[str, Any]]) -> Optional[Velocity]:
        if not d or not isinstance(d, dict):
            return None
        if 'x' not in d or 'y' not in d or 'yaw_rate' not in d:
            return None

        m = Velocity()
        m.x = _clamp(_f(d.get('x')), -35.0, 35.0)
        # 终端桥二次防线：velocity_move 不允许侧移
        m.y = 0.0
        m.yaw_rate = _clamp(_f(d.get('yaw_rate')), -0.89, 0.89)
        return m

    def _build_twist(self, d: Optional[Dict[str, Any]]) -> Optional[Twist]:
        if not d or not isinstance(d, dict):
            return None
        linear = d.get('linear')
        angular = d.get('angular')
        if not isinstance(linear, dict) or not isinstance(angular, dict):
            return None
        if any(key not in linear for key in ('x', 'y', 'z')):
            return None
        if any(key not in angular for key in ('x', 'y', 'z')):
            return None

        t = Twist()
        t.linear.x = _clamp(_f(linear.get('x')), -0.35, 0.35)
        t.linear.y = 0.0
        t.linear.z = 0.0
        t.angular.x = 0.0
        t.angular.y = 0.0
        t.angular.z = _clamp(_f(angular.get('z')), -0.89, 0.89)
        return t

    def _apply_stop(self, mode: str) -> None:
        if mode == 'twist_nav':
            self._pub_twist.publish(Twist())
        else:
            self._pub_vel.publish(Velocity(x=0.0, y=0.0, yaw_rate=0.0))

    def _handle_teleop(self, body: Dict[str, Any]) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        seq = body.get('seq')
        if not isinstance(seq, int):
            self.get_logger().warning('忽略 teleop：seq 非整数')
            return
        if not self._accept_seq(seq, now):
            self.get_logger().debug(f'忽略重复或乱序 seq={seq}（last={self._last_seq}）')
            return

        mode = str(body.get('mode', 'velocity_move')).strip()
        if mode not in ('velocity_move', 'twist_nav'):
            return
        self._last_mode = mode

        stop = body.get('stop')
        if stop is True:
            # stop 帧不得携带 enabled / velocity / pose / twist
            if (
                body.get('enabled') is not None
                or body.get('velocity') is not None
                or body.get('pose') is not None
                or body.get('twist') is not None
            ):
                self.get_logger().warning('忽略 stop 帧：包含非法附加字段')
                return
            self._apply_stop(mode)
            self._last_seq = seq
            self._last_cmd_mono = now
            # 已显式停步，不再依赖超时重复发停
            self._hold_active = False
            return

        if body.get('enabled') is not True:
            return

        if mode == 'velocity_move':
            vel_d = body.get('velocity')
            pose_d = body.get('pose')
            vel = self._build_velocity(vel_d) if isinstance(vel_d, dict) else None
            pose = self._build_pose(pose_d) if isinstance(pose_d, dict) else None
            if body.get('twist') is not None:
                return
            if vel is None and pose is None:
                return
            if vel is not None:
                self._pub_vel.publish(vel)
            if pose is not None:
                self._pub_pose.publish(pose)
        else:
            if body.get('velocity') is not None or body.get('pose') is not None:
                return
            tw = self._build_twist(
                body.get('twist') if isinstance(body.get('twist'), dict) else None
            )
            if tw is None:
                return
            self._pub_twist.publish(tw)

        self._last_seq = seq
        self._last_cmd_mono = now
        self._hold_active = True

    def _publish_hold_stop_if_needed(self) -> None:
        if self._hold_sec <= 0.0 or not self._hold_active:
            return
        now = self.get_clock().now().nanoseconds / 1e9
        if (now - self._last_cmd_mono) < self._hold_sec:
            return
        self._apply_stop(self._last_mode)
        self._hold_active = False

    def _on_tick(self) -> None:
        pending: List[Dict[str, Any]] = []
        with self._lock:
            while self._queue:
                pending.append(self._queue.popleft())
        for item in pending:
            self._handle_teleop(item)
        self._publish_hold_stop_if_needed()


def main() -> None:
    rclpy.init()
    node = TeleopMqttBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
