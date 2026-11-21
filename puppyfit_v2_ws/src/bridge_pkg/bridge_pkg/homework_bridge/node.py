#!/usr/bin/env python3
'''
:brief 今日作业语音桥接节点
:desc 订阅 asr/text，命中“今天/作业”类关键词后调用后端 HTTP 接口，
      并把返回 response_text 发布到 tts/speak。

:author slt
:date 2026/04/29
:version 1.0.0
:history
    1.0.0 - 2026/04/29
        :brief 初始版本
        :desc 新增终端侧“今日作业”查询桥接，复用 BackendAdapter 的鉴权与 401 自动重登。
'''

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from exercise_engine_pkg.core.backend_adapter import BackendAdapter, BackendAdapterError


_NORMALIZE_RE = re.compile(r"[\s，。！？、；：,.!?;:()（）【】\[\]<>《》\"'“”‘’]+")


class HomeworkVoiceBridgeNode(Node):
    '''
    :brief 今日作业语音桥接主节点
    :desc 负责关键词门控、防抖节流、HTTP 请求、异常映射与 TTS 文案发布。
    '''

    def __init__(self) -> None:
        super().__init__('homework_voice_bridge')

        self.declare_parameter('enabled', True)
        self.declare_parameter('backend_config_path', 'puppyfit_v2_ws/config/backend_config.json')
        self.declare_parameter('api_path_key', 'homework_query')
        self.declare_parameter('asr_topic', 'asr/text')
        self.declare_parameter('tts_speak_topic', 'tts/speak')
        self.declare_parameter('device_id', '')
        self.declare_parameter('cooldown_sec', 3.0)
        self.declare_parameter('http_timeout_sec', 8.0)

        self._enabled = self.get_parameter('enabled').get_parameter_value().bool_value
        self._backend_config_path = (
            self.get_parameter('backend_config_path').get_parameter_value().string_value
            or 'puppyfit_v2_ws/config/backend_config.json'
        )
        self._api_path_key = (
            self.get_parameter('api_path_key').get_parameter_value().string_value or 'homework_query'
        )
        self._asr_topic = self.get_parameter('asr_topic').get_parameter_value().string_value or 'asr/text'
        self._tts_speak_topic = (
            self.get_parameter('tts_speak_topic').get_parameter_value().string_value or 'tts/speak'
        )
        self._device_id_override = (
            self.get_parameter('device_id').get_parameter_value().string_value or ''
        ).strip()
        self._cooldown_sec = float(
            self.get_parameter('cooldown_sec').get_parameter_value().double_value
        )
        self._http_timeout_sec = float(
            self.get_parameter('http_timeout_sec').get_parameter_value().double_value
        )

        self._request_lock = threading.Lock()
        self._query_inflight = False
        self._last_trigger_monotonic = 0.0

        self._tts_pub = self.create_publisher(String, self._tts_speak_topic, 10)
        self.create_subscription(String, self._asr_topic, self._on_asr, 10)

        self.get_logger().info(
            f'homework_voice_bridge 已启动: enabled={self._enabled} '
            f'asr_topic={self._asr_topic} tts_speak_topic={self._tts_speak_topic} '
            f'api_path_key={self._api_path_key}'
        )

    def _normalize_text(self, text: str) -> str:
        '''对识别文本做轻量归一化，便于关键词判断。'''
        return _NORMALIZE_RE.sub('', (text or '').strip().lower())

    def _should_trigger(self, normalized_text: str) -> Tuple[bool, bool, bool, bool]:
        '''返回 trigger/direct_hit/time_hit/task_hit 四个布尔量。'''
        direct_patterns = (
            '作业是什么',
            '有什么作业',
            '今天有什么作业',
            '今日任务是什么',
            '今天作业是什么',
            '今天的作业',
        )
        direct_hit = any(pattern in normalized_text for pattern in direct_patterns)
        time_hit = any(keyword in normalized_text for keyword in ('今天', '今日'))
        task_hit = any(keyword in normalized_text for keyword in ('作业', '任务'))
        trigger = direct_hit or (time_hit and task_hit)
        return trigger, direct_hit, time_hit, task_hit

    def _on_asr(self, msg: String) -> None:
        '''处理 ASR 文本：命中后异步发起后端查询。'''
        if not self._enabled:
            return

        text = (msg.data or '').strip()
        if not text:
            return

        normalized = self._normalize_text(text)
        trigger, direct_hit, time_hit, task_hit = self._should_trigger(normalized)
        self.get_logger().info(
            f'作业查询门控: text="{text}" normalized="{normalized}" '
            f'direct_hit={direct_hit} time_hit={time_hit} task_hit={task_hit} trigger={trigger}'
        )
        if not trigger:
            return

        now = time.monotonic()
        with self._request_lock:
            if self._query_inflight:
                self.get_logger().info('作业查询忽略: 当前已有请求在进行中')
                return
            cooldown_elapsed = now - self._last_trigger_monotonic
            if cooldown_elapsed < self._cooldown_sec:
                self.get_logger().info(
                    f'作业查询忽略: 冷却中 ({cooldown_elapsed:.2f}s < {self._cooldown_sec:.2f}s)'
                )
                return
            self._query_inflight = True
            self._last_trigger_monotonic = now

        threading.Thread(
            target=self._query_homework_worker,
            args=(text,),
            daemon=True,
        ).start()

    def _query_homework_worker(self, text: str) -> None:
        '''后台线程：调用后端并播报返回内容。'''
        try:
            speak_text, trace_id = self._fetch_homework(text)
            if trace_id:
                self.get_logger().info(f'作业查询完成: trace_id={trace_id} speak_text="{speak_text}"')
            else:
                self.get_logger().info(f'作业查询完成: speak_text="{speak_text}"')
            self._publish_tts(speak_text)
        except Exception as exc:  # noqa: BLE001
            speak_text = self._map_error_to_speak_text(exc)
            self.get_logger().error(f'作业查询失败: {exc}')
            self._publish_tts(speak_text)
        finally:
            with self._request_lock:
                self._query_inflight = False

    def _fetch_homework(self, text: str) -> Tuple[str, str]:
        '''调用后端接口并提取播报文案与 trace_id。'''
        adapter = BackendAdapter(config_path=self._backend_config_path)
        adapter.http_timeout_sec = int(max(1.0, self._http_timeout_sec))

        payload: Dict[str, Any] = {
            'text': text,
            'device_id': self._device_id_override or adapter.device.get('device_id', 'puppy_001'),
        }
        status, response = adapter.post_json_to_api_path(self._api_path_key, payload)
        code = int(response.get('code', status))
        data = response.get('data') or {}

        if status == 401 or code == 401:
            raise PermissionError('401 unauthorized')
        if status != 200 or code != 200:
            message = response.get('message') or f'HTTP {status}'
            raise RuntimeError(message)

        response_text = str(data.get('response_text') or '').strip()
        trace_id = str(data.get('trace_id') or '').strip()
        if not response_text:
            response_text = '今天暂时没有新作业'
        return response_text, trace_id

    def _map_error_to_speak_text(self, exc: Exception) -> str:
        '''把异常映射为终端播报文案。'''
        if isinstance(exc, PermissionError):
            return '身份校验失败，请重新登录设备'
        if isinstance(exc, BackendAdapterError):
            message = str(exc).lower()
            if 'timed out' in message or 'timeout' in message:
                return '查询作业超时，请稍后再试'
        message = str(exc).lower()
        if 'timed out' in message or 'timeout' in message:
            return '查询作业超时，请稍后再试'
        return '查询作业失败，请稍后再试'

    def _publish_tts(self, text: str) -> None:
        '''向 TTS 话题发布待播报文本。'''
        msg = String()
        msg.data = text
        self._tts_pub.publish(msg)


def main(args=None) -> None:
    '''节点入口：初始化、spin、清理。'''
    rclpy.init(args=args)
    node = HomeworkVoiceBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()