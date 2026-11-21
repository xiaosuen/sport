'''
:brief 训练会话桥接节点（MQTT 控制 + HTTP 会话接口）
:desc 订阅 puppy/control/{device_id} 控制命令，处理 training_session_pending/start_training/stop_training；
      通过 situp_control 驱动本地计数链，通过 situp_count 上报 puppy/data/{device_id}；
      调用后端 /api/device/training-sessions/{session_id}/confirm|complete|error 形成闭环。

:author slt
:date 2026/04/13
:version 1.2.0
:history
    1.2.0 - 2026/04/27
        :brief start_training/stop_training 联动录像 start/stop 话题
        :desc 新增 record_enabled / record_start_topic / record_stop_topic；云端开始训练时发布
              SessionRecordStart，训练完成、停止或异常中止时发布 SessionRecordStop，保持与录像/上传链路的话题级弱耦合。
    1.1.0 - 2026/04/27
        :brief start_training 联动自动找位并等待 ready
        :desc 新增 auto_position 控制/状态订阅与超时参数；start_training 时先发
              auto_position/control=start，收到 ready 后再发 situp_control=start；
              支持找位 failed/timeout 的 error 上报与会话中止。
    1.0.0 - 2026/04/13
        :brief 初始版本
        :desc 订阅 puppy/control/{device_id} 控制命令，处理 training_session_pending/start_training/stop_training；
              通过 situp_control 驱动本地计数链，通过 situp_count 上报 puppy/data/{device_id}；
              调用后端 /api/device/training-sessions/{session_id}/confirm|complete|error 形成闭环。
'''

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from robot_msgs.msg import SitUpCount
from session_record_msgs.msg import SessionRecordStart, SessionRecordStop
from std_msgs.msg import String

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def _now_iso_z() -> str:
    '''返回 UTC 时间字符串（ISO8601，Z 结尾）。'''
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _read_json_file(path: str) -> Dict[str, Any]:
    '''读取 JSON 文件并返回字典，失败时返回空字典。'''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_optional_int(text: str) -> Optional[int]:
    '''把字符串解析为整数；空值或非法值返回 None。'''
    raw = (text or '').strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_optional_bool(text: str) -> Optional[bool]:
    '''把字符串解析为布尔值；空值或非法值返回 None。'''
    raw = (text or '').strip().lower()
    if not raw:
        return None
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    if raw in ('0', 'false', 'no', 'off'):
        return False
    return None


class TrainingSessionBridgeNode(Node):
    '''
    :brief 训练会话桥接主节点
    :desc 把云端控制命令转换为本地训练控制，并把训练进度/结果回传云端。

          控制链路：MQTT -> pending/start/stop -> ROS situp_control
          数据链路：ROS situp_count -> MQTT data/event -> HTTP complete/error
    '''

    def __init__(self) -> None:
        '''初始化参数、ROS 通道、会话状态以及 MQTT 连接。'''
        super().__init__('training_session_bridge')

        self.declare_parameter('backend_config_path', DEFAULT_BACKEND_CONFIG_PATH)
        self.declare_parameter('http_base_url', '')
        self.declare_parameter('device_id', '')
        self.declare_parameter('broker_host', '')
        self.declare_parameter('broker_port', '')
        self.declare_parameter('use_tls', '')
        self.declare_parameter('mqtt_username', '')
        self.declare_parameter('mqtt_password', '')
        self.declare_parameter('mqtt_client_id', '')
        self.declare_parameter('mqtt_qos', 1)
        self.declare_parameter('control_topic_template', 'puppy/control/{device_id}')
        self.declare_parameter('data_topic_template', 'puppy/data/{device_id}')
        self.declare_parameter('event_topic_template', 'puppy/event/{device_id}')
        self.declare_parameter('control_topic', 'situp_control')
        self.declare_parameter('count_topic', 'situp_count')
        self.declare_parameter('auto_position_control_topic', 'auto_position/control')
        self.declare_parameter('auto_position_status_topic', 'auto_position/status')
        self.declare_parameter('wait_auto_position_ready', True)
        self.declare_parameter('auto_position_ready_timeout_sec', 60.0)
        self.declare_parameter('record_enabled', True)
        self.declare_parameter('record_start_topic', 'session/record_start')
        self.declare_parameter('record_stop_topic', 'session/record_stop')
        self.declare_parameter('count_report_interval_sec', 1.0)
        self.declare_parameter('complete_on_target', True)
        self.declare_parameter('http_timeout_sec', 8.0)
        self.declare_parameter(
            'http_confirm_path',
            '/api/device/training-sessions/{session_id}/confirm',
        )
        self.declare_parameter(
            'http_complete_path',
            '/api/device/training-sessions/{session_id}/complete',
        )
        self.declare_parameter(
            'http_error_path',
            '/api/device/training-sessions/{session_id}/error',
        )

        self._mqtt_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending_commands: List[Dict[str, Any]] = []
        self._mqtt: Optional[mqtt.Client] = None
        self._mqtt_connected = False
        self._record_start_pub = None
        self._record_stop_pub = None

        self._load_runtime_config()

        self._control_pub = self.create_publisher(String, self._control_topic, 10)
        self._ap_control_pub = self.create_publisher(String, self._ap_control_topic, 10)
        if self._record_enabled and self._record_start_topic:
            self._record_start_pub = self.create_publisher(SessionRecordStart, self._record_start_topic, 10)
        if self._record_enabled and self._record_stop_topic:
            self._record_stop_pub = self.create_publisher(SessionRecordStop, self._record_stop_topic, 10)
        self.create_subscription(SitUpCount, self._count_topic, self._on_situp_count, 10)
        self.create_subscription(String, self._ap_status_topic, self._on_auto_position_status, 10)
        self.create_timer(0.1, self._drain_control_commands)

        self._reset_session_context()
        self._setup_mqtt()

        self.get_logger().info(
            f'training_session_bridge: device={self._device_id} '
            f'control_topic={self._mqtt_control_topic} data_topic={self._mqtt_data_topic} '
            f'count_topic={self._count_topic} control_topic_ros={self._control_topic} '
            f'ap_control_topic={self._ap_control_topic} ap_status_topic={self._ap_status_topic} '
            f'record_enabled={self._record_enabled} record_start_topic={self._record_start_topic} '
            f'record_stop_topic={self._record_stop_topic}'
        )

    def _load_runtime_config(self) -> None:
        '''加载运行配置并处理参数/配置文件/环境变量的覆盖优先级。'''
        cfg_path = (
            self.get_parameter('backend_config_path').get_parameter_value().string_value
            or DEFAULT_BACKEND_CONFIG_PATH
        )
        cfg = _read_json_file(cfg_path)
        backend_cfg = cfg.get('backend', {}) if isinstance(cfg.get('backend', {}), dict) else {}
        mqtt_cfg = cfg.get('mqtt', {}) if isinstance(cfg.get('mqtt', {}), dict) else {}
        device_cfg = cfg.get('device', {}) if isinstance(cfg.get('device', {}), dict) else {}
        api_paths = backend_cfg.get('api_paths', {}) if isinstance(backend_cfg.get('api_paths', {}), dict) else {}

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
        self._mqtt_client_id = client_id_override or f'training_session_{self._device_id}'

        ctpl = self.get_parameter('control_topic_template').get_parameter_value().string_value
        dtpl = self.get_parameter('data_topic_template').get_parameter_value().string_value
        etpl = self.get_parameter('event_topic_template').get_parameter_value().string_value
        self._mqtt_control_topic = ctpl.replace('{device_id}', self._device_id)
        self._mqtt_data_topic = dtpl.replace('{device_id}', self._device_id)
        self._mqtt_event_topic = etpl.replace('{device_id}', self._device_id)

        self._count_topic = (
            self.get_parameter('count_topic').get_parameter_value().string_value or 'situp_count'
        )
        self._control_topic = (
            self.get_parameter('control_topic').get_parameter_value().string_value or 'situp_control'
        )
        self._ap_control_topic = (
            self.get_parameter('auto_position_control_topic').get_parameter_value().string_value
            or 'auto_position/control'
        )
        self._ap_status_topic = (
            self.get_parameter('auto_position_status_topic').get_parameter_value().string_value
            or 'auto_position/status'
        )
        self._wait_ap_ready = (
            self.get_parameter('wait_auto_position_ready').get_parameter_value().bool_value
        )
        self._ap_ready_timeout_sec = float(
            self.get_parameter('auto_position_ready_timeout_sec').get_parameter_value().double_value
        )
        self._record_enabled = (
            self.get_parameter('record_enabled').get_parameter_value().bool_value
        )
        self._record_start_topic = (
            self.get_parameter('record_start_topic').get_parameter_value().string_value
            or 'session/record_start'
        )
        self._record_stop_topic = (
            self.get_parameter('record_stop_topic').get_parameter_value().string_value
            or 'session/record_stop'
        )
        self._count_report_interval_sec = float(
            self.get_parameter('count_report_interval_sec').get_parameter_value().double_value
        )
        self._complete_on_target = (
            self.get_parameter('complete_on_target').get_parameter_value().bool_value
        )

        http_base_override = self.get_parameter('http_base_url').get_parameter_value().string_value.strip()
        self._http_base_url = (http_base_override or str(backend_cfg.get('http_base_url', '')).strip()).rstrip('/')
        self._http_timeout = float(
            self.get_parameter('http_timeout_sec').get_parameter_value().double_value
        )

        self._confirm_path = str(
            api_paths.get(
                'training_session_confirm',
                self.get_parameter('http_confirm_path').get_parameter_value().string_value,
            )
        )
        self._complete_path = str(
            api_paths.get(
                'training_session_complete',
                self.get_parameter('http_complete_path').get_parameter_value().string_value,
            )
        )
        self._error_path = str(
            api_paths.get(
                'training_session_error',
                self.get_parameter('http_error_path').get_parameter_value().string_value,
            )
        )

    def _reset_session_context(self) -> None:
        '''重置当前训练会话上下文到初始状态。'''
        self._session_id = ''
        self._task_id = ''
        self._target_count = 0
        self._current_count = 0
        self._is_ready = False
        self._is_active = False
        self._completed = False
        self._situp_started = False
        self._waiting_ap_ready = False
        self._ap_wait_begin_sec = 0.0
        self._last_count_report_sec = 0.0
        self._record_started = False

    def _setup_mqtt(self) -> None:
        '''创建并启动 MQTT 客户端，订阅控制主题。'''
        if not self._mqtt_pass:
            self.get_logger().error('未配置 MQTT 密码，训练会话桥接节点无法连接 broker')
            return
        if not self._mqtt_user:
            self.get_logger().error('未配置 MQTT 用户名，训练会话桥接节点无法连接 broker')
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

        with self._mqtt_lock:
            self._mqtt = client
        try:
            client.connect_async(self._broker_host, self._broker_port, keepalive=60)
            client.loop_start()
        except OSError as exc:
            self.get_logger().error(f'MQTT 连接失败: {exc}')

    def _on_mqtt_connect(self, client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        '''MQTT 连接回调：校验返回码并订阅控制主题。'''
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
        client.subscribe(self._mqtt_control_topic, qos=self._mqtt_qos)
        self.get_logger().info(f'MQTT 已连接并订阅 {self._mqtt_control_topic}')

    def _on_mqtt_disconnect(self, _client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        '''MQTT 断连回调：更新连接状态并记录断开原因。'''
        self._mqtt_connected = False
        rc = -1
        if len(args) == 1:
            rc = args[0]
        elif len(args) >= 2:
            rc = args[1]
        if hasattr(rc, 'value'):
            rc = int(rc.value)
        self.get_logger().warning(f'MQTT 已断开 rc={rc}')

    def _on_mqtt_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        '''MQTT 消息回调：解析控制消息并入待处理队列。'''
        if msg.topic != self._mqtt_control_topic:
            return
        try:
            payload_text = msg.payload.decode('utf-8', errors='ignore')
            body = json.loads(payload_text) if payload_text else {}
            if not isinstance(body, dict):
                return
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'解析 MQTT 控制消息失败: {exc}')
            return
        with self._pending_lock:
            self._pending_commands.append(body)

    def _drain_control_commands(self) -> None:
        '''从队列取出待处理控制命令并逐条执行。'''
        # MQTT 回调线程只负责入队；ROS 定时器线程统一出队执行，避免跨线程直接改状态。
        commands: List[Dict[str, Any]] = []
        with self._pending_lock:
            if self._pending_commands:
                commands = self._pending_commands.copy()
                self._pending_commands.clear()
        for command in commands:
            self._handle_control_command(command)
        self._check_auto_position_timeout()

    def _handle_control_command(self, command: Dict[str, Any]) -> None:
        '''根据 cmd 字段分发 pending/start/stop 控制命令。'''
        # 按 cmd 分发控制命令，未知命令仅记录调试日志，不中断主循环。
        cmd = str(command.get('cmd', '')).strip()
        params = command.get('params', {})
        if not isinstance(params, dict):
            params = {}
        if cmd == 'training_session_pending':
            self._handle_pending(params)
        elif cmd == 'start_training':
            self._handle_start_training(params)
        elif cmd == 'stop_training':
            self._handle_stop_training(params)
        else:
            self.get_logger().debug(f'忽略未知控制命令: {cmd!r}')

    def _extract_target_count(self, params: Dict[str, Any]) -> int:
        '''从 exercises 列表中提取有效目标次数（target）。'''
        exercises = params.get('exercises', [])
        if not isinstance(exercises, list):
            return 0
        for item in exercises:
            if not isinstance(item, dict):
                continue
            target = item.get('target')
            try:
                val = int(target)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                continue
        return 0

    def _handle_pending(self, params: Dict[str, Any]) -> None:
        '''处理 training_session_pending：建立上下文并向后端 confirm。'''
        # pending 阶段用于“建立会话上下文 + 向云端 confirm 就绪”。
        session_id = str(params.get('session_id', '')).strip()
        task_id = str(params.get('task_id', '')).strip()
        if not session_id:
            self.get_logger().warning('training_session_pending 缺少 session_id，忽略')
            return

        self._reset_session_context()
        self._session_id = session_id
        self._task_id = task_id
        self._target_count = self._extract_target_count(params)

        ok = self._post_confirm(session_id)
        self._is_ready = ok
        if ok:
            self.get_logger().info(
                f'训练会话已确认 ready: session_id={session_id}, task_id={task_id}, target={self._target_count}'
            )
        else:
            self.get_logger().warning(f'训练会话确认失败: session_id={session_id}')

    def _handle_start_training(self, params: Dict[str, Any]) -> None:
        '''处理 start_training：激活会话并下发本地 start 控制。'''
        # start 只在会话上下文合法时生效，避免串会话导致错控。
        session_id = str(params.get('session_id', '')).strip()
        task_id = str(params.get('task_id', '')).strip()

        if session_id and self._session_id and session_id != self._session_id:
            self.get_logger().warning(
                f'start_training 的 session_id 与当前上下文不一致: cmd={session_id}, local={self._session_id}'
            )
            return
        if session_id and not self._session_id:
            self._session_id = session_id
        if task_id:
            self._task_id = task_id
        if not self._session_id:
            self.get_logger().warning('start_training 前未建立会话上下文，忽略')
            return

        self._is_active = True
        self._completed = False
        self._situp_started = False
        self._waiting_ap_ready = False
        self._ap_wait_begin_sec = 0.0
        self._current_count = 0
        self._publish_record_start()
        self._publish_auto_position_control('start')

        if self._wait_ap_ready:
            self._waiting_ap_ready = True
            self._ap_wait_begin_sec = time.monotonic()
            self._publish_event('auto_position_start', '自动找位已开始')
            self.get_logger().info(
                f'训练开始请求已接收，等待 auto_position ready: session_id={self._session_id}, '
                f'task_id={self._task_id}'
            )
            return

        self._start_situp_counting('skip_wait_auto_position')

    def _handle_stop_training(self, params: Dict[str, Any]) -> None:
        '''处理 stop_training：停止本地训练并执行收尾上报。'''
        session_id = str(params.get('session_id', '')).strip()
        if session_id and self._session_id and session_id != self._session_id:
            self.get_logger().warning(
                f'stop_training 的 session_id 与当前上下文不一致: cmd={session_id}, local={self._session_id}'
            )
            return
        if not self._is_active:
            self.get_logger().info('收到 stop_training，但本地未处于 active，忽略')
            return
        if self._waiting_ap_ready:
            self._waiting_ap_ready = False
            self._publish_auto_position_control('stop')
        self._publish_ros_control('stop')
        self._finish_training(reason='server_stop')

    def _start_situp_counting(self, reason: str) -> None:
        '''启动本地 situp 计数链。'''
        if not self._is_active or self._completed:
            return
        if self._situp_started:
            return
        self._situp_started = True
        self._publish_ros_control('start')
        self._publish_event('training_started', '训练开始')
        self.get_logger().info(
            f'训练已开始: session_id={self._session_id}, task_id={self._task_id}, reason={reason}'
        )

    def _publish_auto_position_control(self, cmd: str) -> None:
        '''向 auto_position/control 发布 start/stop/reset 指令。'''
        msg = String()
        msg.data = cmd
        self._ap_control_pub.publish(msg)

    def _check_auto_position_timeout(self) -> None:
        '''等待 auto_position ready 超时保护。'''
        if not self._waiting_ap_ready:
            return
        if self._ap_ready_timeout_sec <= 0.0:
            return
        if (time.monotonic() - self._ap_wait_begin_sec) < self._ap_ready_timeout_sec:
            return
        self._waiting_ap_ready = False
        self._publish_auto_position_control('stop')
        self._abort_with_error(
            error_code='AUTO_POSITION_TIMEOUT',
            error_message=f'等待自动找位就绪超时({self._ap_ready_timeout_sec:.1f}s)',
            event_message='自动找位超时，训练中止',
        )

    def _on_auto_position_status(self, msg: String) -> None:
        '''监听 auto_position/status，在 ready 时启动计数，failed 时上报错误。'''
        if not self._waiting_ap_ready:
            return

        raw = str(msg.data or '').strip()
        if not raw:
            return
        status = raw.lower()

        if status == 'ready':
            self._waiting_ap_ready = False
            self._start_situp_counting('auto_position_ready')
            return

        if 'failed' in status:
            self._waiting_ap_ready = False
            self._publish_auto_position_control('reset')
            self._abort_with_error(
                error_code='AUTO_POSITION_FAILED',
                error_message=f'自动找位失败: {raw}',
                event_message='自动找位失败，训练中止',
            )

    def _abort_with_error(self, *, error_code: str, error_message: str, event_message: str) -> None:
        '''训练异常中止：上报 error 并重置会话上下文。'''
        self._publish_record_stop()
        session_id = self._session_id
        ok = self._post_error(session_id, error_code, error_message)
        self._is_active = False
        self._completed = True
        self._situp_started = False
        self._waiting_ap_ready = False
        self._publish_event('training_error', event_message, result={'error_code': error_code})
        if ok:
            self.get_logger().warning(
                f'训练异常已上报: session_id={session_id}, code={error_code}, msg={error_message}'
            )
        else:
            self.get_logger().warning(
                f'训练异常上报失败: session_id={session_id}, code={error_code}, msg={error_message}'
            )
        self._reset_session_context()

    def _publish_ros_control(self, cmd: str) -> None:
        '''向 ROS 控制话题发布 start/stop 指令。'''
        msg = String()
        msg.data = cmd
        self._control_pub.publish(msg)

    def _publish_record_start(self) -> None:
        '''发布会话录像开始消息（幂等）。'''
        if not self._record_enabled or self._record_start_pub is None:
            return
        sid = self._session_id.strip()
        if not sid or self._record_started:
            return
        msg = SessionRecordStart()
        msg.session_id = sid
        self._record_start_pub.publish(msg)
        self._record_started = True
        self.get_logger().info(f'已发布录像开始 session_id={sid}')

    def _publish_record_stop(self) -> None:
        '''发布会话录像结束消息（幂等）。'''
        if not self._record_enabled or self._record_stop_pub is None:
            return
        sid = self._session_id.strip()
        if not sid or not self._record_started:
            return
        msg = SessionRecordStop()
        msg.session_id = sid
        self._record_stop_pub.publish(msg)
        self._record_started = False
        self.get_logger().info(f'已发布录像结束 session_id={sid}')

    def _on_situp_count(self, msg: SitUpCount) -> None:
        '''计数回调：更新次数、节流上报，并在达标或停止时触发收尾。'''
        # 仅在 active 且未结束时处理计数，防止旧消息影响已结束会话。
        if not self._is_active or self._completed:
            return
        if not self._situp_started:
            return

        self._current_count = int(msg.count)

        # 按节流间隔上报计数，减少 MQTT 高频小包。
        now_sec = time.monotonic()
        if (now_sec - self._last_count_report_sec) >= max(0.2, self._count_report_interval_sec):
            self._publish_count_data(self._current_count)
            self._last_count_report_sec = now_sec

        # 达标后自动停训并进入完成上报闭环。
        if self._complete_on_target and self._target_count > 0 and self._current_count >= self._target_count:
            self._publish_ros_control('stop')
            self._finish_training(reason='target_reached')
            return

        # 若计数器节点已停止，同样触发收尾。
        if str(msg.state or '').upper() == 'STOPPED':
            self._finish_training(reason='counter_stopped')

    def _publish_count_data(self, count: int) -> None:
        '''发布训练计数数据到 MQTT data 主题。'''
        payload = {
            'type': 'count',
            'count': int(count),
            'task_id': self._task_id,
            'timestamp': _now_iso_z(),
        }
        self._mqtt_publish_json(self._mqtt_data_topic, payload)

    def _publish_event(
        self,
        event_name: str,
        message: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        '''发布训练事件到 MQTT event 主题。'''
        payload: Dict[str, Any] = {
            'event': event_name,
            'task_id': self._task_id,
            'message': message,
            'timestamp': _now_iso_z(),
        }
        if result is not None:
            payload['result'] = result
        self._mqtt_publish_json(self._mqtt_event_topic, payload)

    def _finish_training(self, *, reason: str) -> None:
        '''结束当前训练会话并上报 complete 结果。'''
        # 幂等保护：只允许一次收尾，避免重复 complete。
        if self._completed:
            return
        self._publish_record_stop()
        self._completed = True
        self._is_active = False
        self._situp_started = False
        self._waiting_ap_ready = False

        ok = self._post_complete(
            session_id=self._session_id,
            final_count=self._current_count,
            ended_at=_now_iso_z(),
        )
        if ok:
            self._publish_event(
                'training_completed',
                f'训练完成({reason})',
                result={'total_count': int(self._current_count)},
            )
            self.get_logger().info(
                f'训练完成上报成功: session_id={self._session_id}, final_count={self._current_count}, reason={reason}'
            )
        else:
            self.get_logger().warning(
                f'训练完成上报失败: session_id={self._session_id}, final_count={self._current_count}, reason={reason}'
            )
        self._reset_session_context()

    def _build_session_url(self, path_template: str, session_id: str) -> str:
        '''根据模板和 session_id 生成完整训练会话接口 URL。'''
        path = str(path_template or '').strip()
        if not path:
            raise RuntimeError('训练会话 HTTP 路径为空')
        if '{session_id}' in path:
            path = path.replace('{session_id}', session_id)
        if not path.startswith('/'):
            path = '/' + path
        if not self._http_base_url:
            raise RuntimeError('http_base_url 未配置')
        return f'{self._http_base_url}{path}'

    def _http_post_json(self, url: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        '''发送 HTTP JSON POST 并返回状态码与响应字典。'''
        # 统一 HTTP POST 出口：返回 (状态码, JSON字典)。非 JSON 响应会退化为 message 字段。
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = request.Request(
            url=url,
            data=body,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
        )
        try:
            with request.urlopen(req, timeout=max(1.0, self._http_timeout)) as resp:
                status = int(resp.getcode())
                raw = resp.read().decode('utf-8', errors='ignore')
                data = json.loads(raw) if raw else {}
                return status, data if isinstance(data, dict) else {}
        except error.HTTPError as exc:
            raw = exc.read().decode('utf-8', errors='ignore')
            data: Dict[str, Any] = {}
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        data = parsed
                except json.JSONDecodeError:
                    data = {'message': raw}
            return int(exc.code), data
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'HTTP 请求异常: url={url}, err={exc}')
            return 0, {'message': str(exc)}

    def _post_confirm(self, session_id: str) -> bool:
        '''调用 confirm 接口上报设备就绪状态。'''
        try:
            url = self._build_session_url(self._confirm_path, session_id)
        except RuntimeError as exc:
            self.get_logger().warning(f'无法上报 confirm: {exc}')
            return False
        status, data = self._http_post_json(
            url,
            {
                'device_id': self._device_id,
                'confirm_status': 'ready',
                'timestamp': _now_iso_z(),
            },
        )
        return status == 200 and int(data.get('code', status)) == 200

    def _post_complete(self, session_id: str, final_count: int, ended_at: str) -> bool:
        '''调用 complete 接口上报训练完成结果。'''
        if not session_id:
            return False
        try:
            url = self._build_session_url(self._complete_path, session_id)
        except RuntimeError as exc:
            self.get_logger().warning(f'无法上报 complete: {exc}')
            return False
        status, data = self._http_post_json(
            url,
            {
                'device_id': self._device_id,
                'final_count': int(final_count),
                'ended_at': ended_at,
            },
        )
        return status == 200 and int(data.get('code', status)) == 200

    def _post_error(self, session_id: str, error_code: str, error_message: str) -> bool:
        '''调用 error 接口上报训练异常信息。'''
        if not session_id:
            return False
        try:
            url = self._build_session_url(self._error_path, session_id)
        except RuntimeError as exc:
            self.get_logger().warning(f'无法上报 error: {exc}')
            return False
        status, data = self._http_post_json(
            url,
            {
                'device_id': self._device_id,
                'error_code': error_code,
                'error_message': error_message,
                'timestamp': _now_iso_z(),
            },
        )
        return status == 200 and int(data.get('code', status)) == 200

    def _mqtt_publish_json(self, topic: str, payload: Dict[str, Any]) -> None:
        '''向指定 MQTT 主题发布 JSON 消息。'''
        # 连接未就绪时静默丢弃，避免阻塞训练主流程。
        with self._mqtt_lock:
            client = self._mqtt
        if not client or not self._mqtt_connected:
            return
        try:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            client.publish(topic, body, qos=self._mqtt_qos)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'MQTT 发布失败: topic={topic}, err={exc}')

    def destroy_node(self) -> bool:
        '''节点销毁时关闭 MQTT 循环并断开连接。'''
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
    '''程序入口：初始化 ROS、运行节点并在退出时清理资源。'''
    rclpy.init(args=args)
    node = TrainingSessionBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
