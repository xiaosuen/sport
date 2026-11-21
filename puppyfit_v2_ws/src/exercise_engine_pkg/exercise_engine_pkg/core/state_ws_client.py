#!/usr/bin/env python3
"""
:brief 状态 WebSocket 上报客户端
:desc 在独立线程中连接服务器，周期推送 state 与可选视频帧（base64）
:author slt
:date 2026/03/12
:version 1.0.1
:history
    - 1.0.0 2026/03/12
        :desc 初始版本，支持周期上报与断线重连
    - 1.0.1 2026/03/25
        :desc 补充版本控制注释，便于追踪代码演进
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, Optional

try:
    import websocket
except ImportError:
    websocket = None  # type: ignore


def run_ws_client_thread(
    ws_url: str,
    push_interval_sec: float,
    get_payload: Callable[[], dict],
    stop_event: threading.Event,
    logger,
    reconnect_delay_sec: float = 5.0,
) -> None:
    """
    在调用线程中循环：连接 WebSocket，按 push_interval_sec 周期发送 get_payload() 的 JSON；
    若服务端下发了 frame_ack 则解析并打印。断线后等待 reconnect_delay_sec 重连。
    """
    if websocket is None:
        logger.warning("未安装 websocket-client，WebSocket 上报已禁用。请执行: pip install websocket-client")
        return
    while not stop_event.is_set():
        try:
            ws = websocket.WebSocket()
            ws.settimeout(5)
            ws.connect(ws_url)
            logger.info(f"WebSocket 已连接: {ws_url}")
            last_send = 0.0
            while not stop_event.is_set():
                now = time.monotonic()
                if now - last_send >= push_interval_sec:
                    try:
                        payload = get_payload()
                        text = json.dumps(payload, ensure_ascii=False)
                        ws.send(text)
                        last_send = now
                    except Exception as e:
                        logger.warning(f"WebSocket 发送失败: {e}")
                        break
                # 非阻塞收取服务端下发的 frame_ack 等
                try:
                    ws.settimeout(0.1)
                    raw = ws.recv()
                    if raw:
                        msg = json.loads(raw)
                        if msg.get("type") == "frame_ack":
                            logger.info(f"服务端确认: {msg.get('message', raw)}")
                        else:
                            logger.debug(f"服务端: {raw}")
                except Exception:
                    ws.settimeout(5)
                time.sleep(0.05)
            try:
                ws.close()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"WebSocket 连接/重连失败: {e}")
        if not stop_event.is_set():
            stop_event.wait(timeout=reconnect_delay_sec)


class StateWsReporter:
    """
    封装 WebSocket 上报：持有线程与 stop_event，提供 start/stop。
    get_payload 由节点提供，返回可 JSON 序列化的 dict（含 state 与可选的 frame base64）。
    """

    def __init__(
        self,
        ws_url: str,
        push_interval_sec: float,
        get_payload: Callable[[], dict],
        logger,
    ) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws_url = ws_url
        self._push_interval_sec = push_interval_sec
        self._get_payload = get_payload
        self._logger = logger

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=run_ws_client_thread,
            args=(
                self._ws_url,
                self._push_interval_sec,
                self._get_payload,
                self._stop_event,
                self._logger,
            ),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
