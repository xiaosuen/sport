'''
:brief MQTT 遥测桥接节点（ROS2 → MQTT）
:desc 按固定周期采集 ROS2 话题与系统指标，经 MQTT 发布至 puppy/data/{device_id}；另按周期向
      puppy/event/{device_id} 发送心跳 JSON（与 puppyfit MQTT_TOPICS["event"] 及 _handle_event 一致）。
      电压：Float32（伏）或 UInt16（毫伏，battery_mv_topic）；percentage 由 battery_v_min/max 线性映射。
      IMU 可订阅真实话题；电压超时未更新时按参数回退模拟值。
      认证优先使用环境变量 PUPPY_MQTT_USER / PUPPY_MQTT_PASS，避免密码硬编码入库。
      HTTP 心跳默认开启（declare_parameter 默认 true）：依赖 exercise_engine_pkg.BackendAdapter，需
      backend_config.json 与 PUPPY_DEVICE_USER / PUPPY_DEVICE_PASS（load_backend_config 同时要求 PUPPY_MQTT_* 已设置）。
      http_register_on_start 默认 false。

:author slt
:date 2026/04/01
:version 1.3.3
:history
    1.3.3 - 2026/04/02
        :brief 源码置于 bridge_pkg.telemetry.node（可执行名仍为 telemetry_bridge）
    1.3.2 - 2026/04/02
        :brief 默认 enable_http_heartbeat=true、http_register_on_start=false（与 launch 一致）
    1.3.1 - 2026/04/02
        :brief 无电池话题逾 25s 打一次 WARN，提示 simulated_voltage_v 导致固定电量百分比
    1.3.0 - 2026/04/01
        :brief 可选 HTTP 周期上报 /api/device/status（复用 BackendAdapter）；launch 参数 enable_http_heartbeat 等
    1.2.0 - 2026/04/01
        :brief battery_mv_topic（UInt16 mV）与 battery_v_min/max 线性 percentage；launch 默认 PuppyPi
    1.0.0 - 2026/03/25
        :brief 初始版本：telemetry_bridge 可执行入口与 mqtt_telemetry.launch.py
    1.1.0 - 2026/03/25
        :brief 每 30s 心跳发 puppy/event/{device_id}（后端未订阅 puppy/{device_id}/heartbeat）
    1.1.1 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
'''

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from std_msgs.msg import Bool, Float32, String, UInt16

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def _quat_to_rpy(x: float, y: float, z: float, w: float) -> Tuple[float, float, float]:
    """四元数转 roll/pitch/yaw（弧度）。"""
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return roll, pitch, yaw


def _read_cpu_temp_c() -> Optional[float]:
    path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        raw = int(open(path, "r", encoding="utf-8").read().strip())
        return raw / 1000.0
    except (OSError, ValueError):
        return None


def _read_uptime_sec() -> Optional[float]:
    try:
        line = open("/proc/uptime", "r", encoding="utf-8").read().split()
        return float(line[0])
    except (OSError, ValueError, IndexError):
        return None


def _read_wifi_rssi_dbm() -> Optional[int]:
    """解析 /proc/net/wireless 中首个非 lo 接口的 level（dBm）。"""
    try:
        with open("/proc/net/wireless", "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in lines[2:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[0].rstrip(":")
        if iface == "lo":
            continue
        try:
            level = parts[3].rstrip(".")
            return int(float(level))
        except ValueError:
            continue
    return None


def _voltage_to_percent_linear(v: float, vmin: float, vmax: float) -> int:
    '''
    :brief 将电压线性映射到 0–100
    :param v: 当前电压（V）
    :param vmin: 对应 0% 的电压（V）
    :param vmax: 对应 100% 的电压（V）
    '''
    if vmax <= vmin:
        return 0
    p = (v - vmin) / (vmax - vmin) * 100.0
    return int(max(0, min(100, round(p))))


class TelemetryBridgeNode(Node):
    '''
    :brief 订阅 ROS2 话题与本机系统信息，定时向 MQTT 发布遥测 JSON
    :desc 参数化 Broker、主题模板、各数据源话题名；MQTT 连接失败或密码缺失时仅记录日志，不阻塞节点启动。
    '''

    def __init__(self) -> None:
        super().__init__("mqtt_telemetry_bridge")
        self._node_start_sec = self.get_clock().now().nanoseconds / 1e9
        self._battery_missing_warned = False

        self.declare_parameter("device_id", "puppy_001")
        self.declare_parameter("broker_host", "122.51.12.83")
        self.declare_parameter("broker_port", 1883)
        self.declare_parameter("use_tls", False)
        self.declare_parameter("mqtt_username", "")
        self.declare_parameter("mqtt_password", "")
        self.declare_parameter("mqtt_client_id", "")
        self.declare_parameter("mqtt_qos", 1)
        # 与后端 EnhancedMQTTClient 订阅一致：puppy/data/{device_id}
        self.declare_parameter("mqtt_topic_template", "puppy/data/{device_id}")
        self.declare_parameter("publish_interval_sec", 5.0)
        # 与 puppyfit/config.py MQTT_TOPICS["event"] 一致；后端未订阅 puppy/{device_id}/heartbeat
        self.declare_parameter("mqtt_heartbeat_topic_template", "puppy/event/{device_id}")
        self.declare_parameter("heartbeat_interval_sec", 30.0)
        self.declare_parameter("heartbeat_enabled", True)
        self.declare_parameter("heartbeat_status", "online")

        self.declare_parameter("voltage_topic", "/voltage")
        # 非空则订阅 std_msgs/UInt16 毫伏（如 /ros_robot_controller/battery），并除以 1000 为伏特
        self.declare_parameter("battery_mv_topic", "")
        self.declare_parameter("battery_v_min", 10.5)
        self.declare_parameter("battery_v_max", 12.6)
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("gait_topic", "")
        self.declare_parameter("moving_topic", "")
        self.declare_parameter("default_gait", "stand")
        self.declare_parameter("default_moving", False)
        self.declare_parameter("simulated_voltage_v", 12.6)
        self.declare_parameter("voltage_timeout_sec", 10.0)
        self.declare_parameter("enable_http_heartbeat", True)
        self.declare_parameter("http_heartbeat_interval_sec", 30.0)
        self.declare_parameter("backend_config_path", DEFAULT_BACKEND_CONFIG_PATH)
        self.declare_parameter("http_register_on_start", False)

        self._device_id = self.get_parameter("device_id").get_parameter_value().string_value
        self._broker_host = self.get_parameter("broker_host").get_parameter_value().string_value
        self._broker_port = self.get_parameter("broker_port").get_parameter_value().integer_value
        self._use_tls = self.get_parameter("use_tls").get_parameter_value().bool_value
        self._mqtt_qos = self.get_parameter("mqtt_qos").get_parameter_value().integer_value
        tpl = self.get_parameter("mqtt_topic_template").get_parameter_value().string_value
        self._publish_topic = tpl.replace("{device_id}", self._device_id)
        hb_tpl = self.get_parameter("mqtt_heartbeat_topic_template").get_parameter_value().string_value
        self._heartbeat_topic = hb_tpl.replace("{device_id}", self._device_id)
        self._heartbeat_interval = float(
            self.get_parameter("heartbeat_interval_sec").get_parameter_value().double_value
        )
        self._heartbeat_enabled = self.get_parameter("heartbeat_enabled").get_parameter_value().bool_value
        self._heartbeat_status = self.get_parameter("heartbeat_status").get_parameter_value().string_value

        user_param = self.get_parameter("mqtt_username").get_parameter_value().string_value
        pass_param = self.get_parameter("mqtt_password").get_parameter_value().string_value
        self._mqtt_user = os.environ.get("PUPPY_MQTT_USER", user_param).strip() or "puppy_device"
        self._mqtt_pass = os.environ.get("PUPPY_MQTT_PASS", pass_param)

        cid = self.get_parameter("mqtt_client_id").get_parameter_value().string_value.strip()
        self._client_id = cid or f"ros2_telemetry_{self._device_id}"

        self._voltage_topic = (
            self.get_parameter("voltage_topic").get_parameter_value().string_value or ""
        ).strip()
        self._battery_mv_topic = (
            self.get_parameter("battery_mv_topic").get_parameter_value().string_value or ""
        ).strip()
        self._battery_v_min = float(self.get_parameter("battery_v_min").get_parameter_value().double_value)
        self._battery_v_max = float(self.get_parameter("battery_v_max").get_parameter_value().double_value)
        self._imu_topic = self.get_parameter("imu_topic").get_parameter_value().string_value
        self._gait_topic = self.get_parameter("gait_topic").get_parameter_value().string_value.strip()
        self._moving_topic = self.get_parameter("moving_topic").get_parameter_value().string_value.strip()
        self._default_gait = self.get_parameter("default_gait").get_parameter_value().string_value
        self._default_moving = self.get_parameter("default_moving").get_parameter_value().bool_value
        self._sim_v = float(self.get_parameter("simulated_voltage_v").get_parameter_value().double_value)
        self._voltage_timeout = float(self.get_parameter("voltage_timeout_sec").get_parameter_value().double_value)
        self._enable_http_heartbeat = (
            self.get_parameter("enable_http_heartbeat").get_parameter_value().bool_value
        )
        self._http_heartbeat_interval_sec = float(
            self.get_parameter("http_heartbeat_interval_sec").get_parameter_value().double_value
        )
        self._http_register_on_start = (
            self.get_parameter("http_register_on_start").get_parameter_value().bool_value
        )
        self._http_adapter: Optional[Any] = None

        self._last_voltage: Optional[float] = None
        self._last_voltage_stamp_sec: Optional[float] = None
        self._imu_rpy: Optional[Tuple[float, float, float]] = None
        self._gait: str = self._default_gait
        self._moving: bool = self._default_moving
        self._mqtt_lock = threading.Lock()
        self._mqtt: Optional[mqtt.Client] = None
        self._mqtt_connected = False

        if not self._mqtt_pass:
            self.get_logger().error(
                "mqtt_password 为空且未设置环境变量 PUPPY_MQTT_PASS，无法连接 Broker"
            )
        else:
            self._setup_mqtt()

        if self._voltage_topic:
            self.create_subscription(Float32, self._voltage_topic, self._on_voltage, 10)
        if self._battery_mv_topic:
            self.create_subscription(UInt16, self._battery_mv_topic, self._on_battery_mv, 10)
        if self._imu_topic:
            self.create_subscription(Imu, self._imu_topic, self._on_imu, 10)
        if self._gait_topic:
            self.create_subscription(String, self._gait_topic, self._on_gait, 10)
        if self._moving_topic:
            self.create_subscription(Bool, self._moving_topic, self._on_moving, 10)

        interval = float(self.get_parameter("publish_interval_sec").get_parameter_value().double_value)
        self.create_timer(max(0.5, interval), self._on_timer)

        if self._heartbeat_enabled and self._heartbeat_interval > 0.0:
            self.create_timer(max(1.0, self._heartbeat_interval), self._on_heartbeat_timer)

        self._setup_http_heartbeat()

        vsrc = []
        if self._voltage_topic:
            vsrc.append(f"Float32:{self._voltage_topic}")
        if self._battery_mv_topic:
            vsrc.append(f"UInt16mV:{self._battery_mv_topic}")
        vsrc_s = "+".join(vsrc) if vsrc else "(仅模拟电压)"
        self.get_logger().info(
            f"telemetry_bridge: data_topic={self._publish_topic} interval={interval}s "
            f"heartbeat_topic={self._heartbeat_topic} every={self._heartbeat_interval}s "
            f"device={self._device_id} voltage={vsrc_s} percent_map=[{self._battery_v_min},{self._battery_v_max}]V"
        )

    def _setup_http_heartbeat(self) -> None:
        """
        :brief 按 backend_config.json + BackendAdapter 周期 POST /api/device/status
        :desc 登录与 401 重试由 BackendAdapter 处理；配置加载需环境变量 PUPPY_DEVICE_* 与 PUPPY_MQTT_*。
        """
        if not self._enable_http_heartbeat:
            return
        try:
            from exercise_engine_pkg.core.backend_adapter import BackendAdapter, BackendAdapterError
            from exercise_engine_pkg.core.config_loader import BackendConfigError
        except ImportError as exc:
            self.get_logger().error(
                f"enable_http_heartbeat 已开启但无法导入 exercise_engine_pkg: {exc}"
            )
            return

        cfg = self.get_parameter("backend_config_path").get_parameter_value().string_value.strip()
        path_arg = cfg if cfg else DEFAULT_BACKEND_CONFIG_PATH
        try:
            self._http_adapter = BackendAdapter(config_path=path_arg)
        except BackendConfigError as exc:
            self.get_logger().error(f"加载 backend 配置失败，HTTP 心跳已禁用: {exc}")
            self._http_adapter = None
            return

        if self._http_register_on_start:
            try:
                self._http_adapter.register_device()
                self.get_logger().info("HTTP 设备注册成功")
            except BackendAdapterError as exc:
                self.get_logger().warning(
                    f"HTTP 设备注册失败（设备若已在库中可忽略）: {exc}"
                )

        if self._http_heartbeat_interval_sec <= 0.0:
            self.get_logger().info("HTTP 设备状态上报已启用，但未设置正数间隔，跳过周期定时器")
            return

        iv = max(5.0, self._http_heartbeat_interval_sec)
        self.create_timer(iv, self._on_http_heartbeat_timer)
        self.get_logger().info(f"HTTP 设备状态上报已启用，间隔 {iv}s（配置: {path_arg}）")

    def _current_battery_percentage(self) -> int:
        v = self._resolve_voltage()
        return _voltage_to_percent_linear(v, self._battery_v_min, self._battery_v_max)

    def _on_http_heartbeat_timer(self) -> None:
        if self._http_adapter is None:
            return
        try:
            from exercise_engine_pkg.core.backend_adapter import BackendAdapterError

            pct = self._current_battery_percentage()
            self._http_adapter.report_heartbeat(battery=pct, status_text="online")
        except BackendAdapterError as exc:
            self.get_logger().warning(f"HTTP 设备状态上报失败: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f"HTTP 设备状态上报异常: {exc}")

    def _setup_mqtt(self) -> None:
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._client_id,
                protocol=mqtt.MQTTv311,
                transport="tcp",
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(
                client_id=self._client_id,
                protocol=mqtt.MQTTv311,
                transport="tcp",
            )
        client.username_pw_set(self._mqtt_user, self._mqtt_pass)

        def _on_disconnect(_c: mqtt.Client, _u: Any, *args: Any) -> None:
            # paho v1: (rc,) ；v2: (disconnect_flags, reason_code, properties)
            rc = -1
            if len(args) == 1:
                rc = args[0]
            elif len(args) >= 2:
                rc = args[1]
            if hasattr(rc, "value"):
                rc = int(rc.value)
            elif not isinstance(rc, int):
                try:
                    rc = int(rc)
                except (TypeError, ValueError):
                    rc = -1
            self._mqtt_connected = False
            self.get_logger().warn(f"MQTT 断开 rc={rc}")

        if self._use_tls:
            client.tls_set()

        def _on_connect_cb(_client: mqtt.Client, _userdata: Any, *args: Any) -> None:
            # v1: flags, rc ；v2: flags, reason_code, properties —— 成功码均在索引 1
            rc = 0
            if len(args) >= 2:
                rc = args[1]
            elif len(args) == 1:
                rc = args[0]
            if hasattr(rc, "value"):
                rc = int(rc.value)
            elif not isinstance(rc, int):
                try:
                    rc = int(rc)
                except (TypeError, ValueError):
                    rc = -1
            if rc == 0:
                self._mqtt_connected = True
                self.get_logger().info("MQTT 已连接")
            else:
                self._mqtt_connected = False
                self.get_logger().warn(f"MQTT 连接结果 rc={rc}")

        client.on_connect = _on_connect_cb  # type: ignore[method-assign]
        client.on_disconnect = _on_disconnect  # type: ignore[method-assign]

        try:
            client.connect_async(self._broker_host, int(self._broker_port), keepalive=60)
            client.loop_start()
            self._mqtt = client
        except OSError as e:
            self.get_logger().error(f"MQTT 连接失败: {e}")

    def _on_voltage(self, msg: Float32) -> None:
        self._last_voltage = float(msg.data)
        self._last_voltage_stamp_sec = self.get_clock().now().nanoseconds / 1e9

    def _on_battery_mv(self, msg: UInt16) -> None:
        self._last_voltage = float(msg.data) / 1000.0
        self._last_voltage_stamp_sec = self.get_clock().now().nanoseconds / 1e9

    def _on_imu(self, msg: Imu) -> None:
        o = msg.orientation
        self._imu_rpy = _quat_to_rpy(o.x, o.y, o.z, o.w)

    def _on_gait(self, msg: String) -> None:
        text = (msg.data or "").strip()
        if text:
            self._gait = text

    def _on_moving(self, msg: Bool) -> None:
        self._moving = bool(msg.data)

    def _resolve_voltage(self) -> float:
        now = self.get_clock().now().nanoseconds / 1e9
        if self._last_voltage is not None and self._last_voltage_stamp_sec is not None:
            if now - self._last_voltage_stamp_sec <= self._voltage_timeout:
                return self._last_voltage
        return self._sim_v

    def _build_payload(self) -> Dict[str, Any]:
        """
        :brief 组装本周期上报后端的 JSON 字典
        :desc 合并 device_id、timestamp、battery、motion、system；若已收到 IMU 则附加
              imu 的 roll/pitch/yaw（弧度）。system 中各子字段仅在读取成功时写入。
        :return 可被 json.dumps 序列化为 UTF-8 载荷的 dict
        """
        v = self._resolve_voltage()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        imu_block: Optional[Dict[str, float]] = None
        if self._imu_rpy is not None:
            roll, pitch, yaw = self._imu_rpy
            imu_block = {"roll": roll, "pitch": pitch, "yaw": yaw}

        wifi = _read_wifi_rssi_dbm()
        cpu_t = _read_cpu_temp_c()
        up = _read_uptime_sec()

        system: Dict[str, Any] = {}
        if cpu_t is not None:
            system["cpu_temp"] = round(cpu_t, 2)
        if wifi is not None:
            system["wifi_rssi"] = wifi
        if up is not None:
            system["uptime"] = int(up)

        payload: Dict[str, Any] = {
            "device_id": self._device_id,
            "timestamp": ts,
            "battery": {
                "voltage": round(v, 2),
                "percentage": _voltage_to_percent_linear(v, self._battery_v_min, self._battery_v_max),
            },
            "motion": {"gait": self._gait, "moving": self._moving},
            "system": system,
        }
        if imu_block is not None:
            payload["imu"] = imu_block
        return payload

    def _build_heartbeat_payload(self) -> Dict[str, Any]:
        """
        :brief 组装 MQTT 心跳 JSON（与 puppyfit EnhancedMQTTClient._handle_event 约定）
        :desc 主题须为 puppy/event/{device_id}；含 type=heartbeat 便于后端 _handle_event 分类，其余字段与业务约定一致。
        :return 可序列化为 UTF-8 的 dict
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "type": "heartbeat",
            "device_id": self._device_id,
            "status": self._heartbeat_status,
            "timestamp": ts,
        }

    def _publish_json(self, topic: str, payload: Dict[str, Any]) -> None:
        if not self._mqtt or not self._mqtt_pass:
            return
        body = json.dumps(payload, ensure_ascii=False)
        with self._mqtt_lock:
            if self._mqtt_connected and self._mqtt:
                try:
                    self._mqtt.publish(topic, body.encode("utf-8"), qos=int(self._mqtt_qos))
                except Exception as e:  # noqa: BLE001
                    self.get_logger().warn(f"MQTT publish 失败 ({topic}): {e}")
            elif self._mqtt:
                self.get_logger().debug(f"MQTT 未连接，跳过发布: {topic}")

    def _maybe_warn_battery_missing(self) -> None:
        """
        :brief 长时间无电池话题时告警一次
        :desc 默认 simulated_voltage_v=7.35V 在 PuppyPi 6.4–8.3V 映射下约为 50%，易与「未收到真值」混淆。
        """
        if self._battery_missing_warned:
            return
        if not self._battery_mv_topic and not self._voltage_topic:
            return
        if self._last_voltage is not None:
            return
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self._node_start_sec < 25.0:
            return
        topic = self._battery_mv_topic or self._voltage_topic
        sim_pct = _voltage_to_percent_linear(
            self._sim_v, self._battery_v_min, self._battery_v_max
        )
        self.get_logger().warning(
            f"逾 25s 未收到电池话题「{topic}」上的消息，遥测/HTTP 使用 simulated_voltage_v="
            f"{self._sim_v}V（约 {sim_pct}%）。请确认 ros_robot_controller 已运行、串口正常，并可用 "
            f"ros2 topic echo {topic} / ros2 topic hz {topic} 排查。"
        )
        self._battery_missing_warned = True

    def _on_timer(self) -> None:
        self._maybe_warn_battery_missing()
        self._publish_json(self._publish_topic, self._build_payload())

    def _on_heartbeat_timer(self) -> None:
        if not self._heartbeat_enabled:
            return
        self._publish_json(self._heartbeat_topic, self._build_heartbeat_payload())

    def destroy_node(self) -> bool:
        with self._mqtt_lock:
            if self._mqtt:
                try:
                    self._mqtt.loop_stop()
                    self._mqtt.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._mqtt = None
        return super().destroy_node()


def main(args: Optional[List[str]] = None) -> None:
    """
    :brief 可执行入口：创建节点并 spin
    :param args: 可选，传入 rclpy.init 的命令行参数
    """
    rclpy.init(args=args)
    node = TelemetryBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
