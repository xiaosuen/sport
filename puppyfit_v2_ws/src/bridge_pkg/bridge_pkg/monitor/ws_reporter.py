'''
:brief 监控页 WebSocket 上报（与 exercise_engine_pkg 解耦）
:desc 独立线程连接 ws://.../ws/camera/{device_id}，周期发送 JSON；断线指数退避重连。
     依赖 websocket-client；与 StateWsReporter 思路类似，不复用 exercise_engine_pkg。

:author slt
:date 2026/04/02
:version 1.0.0
:history
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

try:
    import websocket
except ImportError:
    websocket = None  # type: ignore


class MonitorWsReporter:
    '''
    :brief 封装监控 WebSocket：start/stop，线程内 connect + 周期 send + 指数退避重连
    :desc get_payload 返回 type=frame 的 dict；可选周期性额外发送 type=heartbeat
    '''

    def __init__(
        self,
        ws_url: str,
        device_id: str,
        push_interval_sec: float,
        get_frame_payload: Callable[[], dict],
        logger,
        heartbeat_interval_sec: float = 0.0,
        reconnect_backoff_initial_sec: float = 1.0,
        reconnect_backoff_max_sec: float = 60.0,
    ) -> None:
        self._ws_url = ws_url
        self._device_id = device_id
        self._push_interval_sec = max(0.05, float(push_interval_sec))
        self._get_frame_payload = get_frame_payload
        self._logger = logger
        self._heartbeat_interval_sec = max(0.0, float(heartbeat_interval_sec))
        self._backoff_initial = max(0.5, float(reconnect_backoff_initial_sec))
        self._backoff_max = max(self._backoff_initial, float(reconnect_backoff_max_sec))
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # frame_ack 里服务端返回的 count；仅当与上次不同时打 info，避免刷屏
        self._last_frame_ack_count: Optional[int] = None

    def start(self) -> None:
        '''
        :brief 启动后台 WebSocket 线程
        '''
        if websocket is None:
            self._logger.warning("未安装 websocket-client，监控 WebSocket 已禁用: pip install websocket-client")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        '''
        :brief 请求停止线程并 join
        '''
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _build_heartbeat(self) -> Dict[str, object]:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "type": "heartbeat",
            "device_id": self._device_id,
            "timestamp": ts,
        }

    @staticmethod
    def _coerce_ack_count(value: object) -> Optional[int]:
        '''
        :brief 解析 frame_ack 中的 count（JSON 可能为 int/float/str）
        '''
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            s = value.strip()
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                return int(s)
            try:
                return int(float(s))
            except ValueError:
                return None
        return None

    def _run_loop(self) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocket()
                ws.settimeout(5)
                ws.connect(self._ws_url)
                self._logger.info(f"监控 WebSocket 已连接: {self._ws_url}")
                attempt = 0
                self._last_frame_ack_count = None
                last_send = 0.0
                last_hb = 0.0
                while not self._stop_event.is_set():
                    now = time.monotonic()
                    if (
                        self._heartbeat_interval_sec > 0.0
                        and now - last_hb >= self._heartbeat_interval_sec
                    ):
                        try:
                            hb = self._build_heartbeat()
                            ws.send(json.dumps(hb, ensure_ascii=False))
                            last_hb = now
                        except Exception as exc:  # noqa: BLE001
                            self._logger.warning(f"监控 WebSocket 发送 heartbeat 失败: {exc}")
                            break
                    if now - last_send >= self._push_interval_sec:
                        try:
                            payload = self._get_frame_payload()
                            ws.send(json.dumps(payload, ensure_ascii=False))
                            last_send = now
                        except Exception as exc:  # noqa: BLE001
                            self._logger.warning(f"监控 WebSocket 发送 frame 失败: {exc}")
                            break
                    try:
                        ws.settimeout(0.1)
                        raw = ws.recv()
                        if raw:
                            try:
                                msg = json.loads(raw)
                                if msg.get("type") == "frame_ack":
                                    ack_count = self._coerce_ack_count(msg.get("count"))
                                    text = msg.get("message", raw)
                                    if ack_count is not None:
                                        if ack_count != self._last_frame_ack_count:
                                            self._last_frame_ack_count = ack_count
                                            self._logger.info(f"监控服务端: {text}")
                                        else:
                                            self._logger.debug(f"监控服务端(frame_ack count 未变={ack_count}): {text}")
                                    else:
                                        self._logger.debug(f"监控服务端(frame_ack 无有效 count): {text}")
                                else:
                                    self._logger.debug(f"监控服务端: {raw}")
                            except json.JSONDecodeError:
                                self._logger.debug(f"监控服务端(非JSON): {raw}")
                    except Exception:
                        ws.settimeout(5)
                    time.sleep(0.02)
                try:
                    ws.close()
                except Exception:
                    pass
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(f"监控 WebSocket 连接失败: {exc}")
            if self._stop_event.is_set():
                break
            attempt += 1
            delay = min(self._backoff_max, self._backoff_initial * (2 ** (attempt - 1)))
            self._logger.info(f"监控 WebSocket {delay:.1f}s 后重连（第 {attempt} 次退避）")
            self._stop_event.wait(timeout=delay)
