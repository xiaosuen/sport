#!/usr/bin/env python3
'''
:brief 仰卧起坐计数 Web 展示节点
:desc 订阅计数话题并通过 HTTP 页面展示（无需额外依赖）。

:author slt&zxh
:date 2026/03/11
:version 1.0.2
:history
    1.0.0 - 2026/03/11
        :brief 初始版本，提供计数 Web 可视化
    1.0.1 - 2026/03/25
        :brief 补充版本控制注释，便于追踪代码演进
    1.0.2 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
'''

from __future__ import annotations

import base64
import json
import time
import threading
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import cv2
import rclpy
from rclpy.node import Node
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from std_msgs.msg import String

from robot_msgs.msg import SitUpCount, VideoStats

from exercise_engine_pkg.core.state_ws_client import StateWsReporter
from exercise_engine_pkg.core.config_loader import BackendConfigError, load_backend_config

_DEFAULT_BACKEND_CONFIG_PATH = "/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json"


def _html_template(safe_video_html: str, stats_topic: str) -> str:
    """页面 HTML 模板，{safe_video_html} 为视频区片段。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>仰卧起坐计数</title>
  <style>
    :root {{ --bg: #0b0f14; --card: #111827; --text: #e5e7eb; --muted: #9ca3af; --accent: #22c55e; --warn: #f59e0b; --border: rgba(255,255,255,.10); }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", "PingFang SC", sans-serif; background: radial-gradient(1200px 700px at 20% 10%, rgba(34,197,94,.20), transparent 55%), radial-gradient(900px 600px at 80% 30%, rgba(245,158,11,.12), transparent 60%), var(--bg); color: var(--text); }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
    header {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 16px; }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: .5px; }}
    .sub {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 14px; }}
    @media (min-width: 900px) {{ .grid {{ grid-template-columns: 380px 1fr; }} }}
    .card {{ background: rgba(17,24,39,.78); border: 1px solid var(--border); box-shadow: 0 18px 60px rgba(0,0,0,.35); border-radius: 16px; padding: 16px; backdrop-filter: blur(10px); }}
    .kpi {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }}
    .kpi .item {{ border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: rgba(0,0,0,.12); }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ font-size: 34px; font-weight: 700; margin-top: 6px; line-height: 1.1; }}
    .pill {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 999px; padding: 6px 10px; font-size: 12px; color: var(--muted); background: rgba(0,0,0,.18); }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; background: var(--warn); box-shadow: 0 0 0 3px rgba(245,158,11,.15); }}
    .dot.ok {{ background: var(--accent); box-shadow: 0 0 0 3px rgba(34,197,94,.18); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .hint {{ color: var(--muted); font-size: 12px; margin: 10px 0 0; }}
    .video-wrap {{ position: relative; width: 100%; padding-top: 56.25%; border-radius: 12px; overflow: hidden; border: 1px solid var(--border); background: rgba(0,0,0,.22); }}
    .video {{ position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }}
    .video-img {{ object-fit: contain; background: rgba(0,0,0,.22); }}
  </style>
</head>
<body>
  <div class="wrap">
    <header><h1>仰卧起坐计数</h1><div class="sub">自动刷新：250ms</div></header>
    <div class="grid">
      <section class="card">
        <div class="pill"><span id="dot" class="dot"></span><span id="conn">连接中...</span></div>
        <div class="kpi">
          <div class="item"><div class="label">次数</div><div id="count" class="value mono">0</div></div>
          <div class="item"><div class="label">动作状态</div><div id="state" class="value mono" style="font-size:28px">-</div></div>
                    <div class="item"><div class="label">视频帧率(FPS)</div><div id="fps" class="value mono" style="font-size:28px">0.0</div></div>
          <div class="item"><div class="label">方向</div><div id="direction" class="value mono" style="font-size:28px">-</div></div>
          <div class="item"><div class="label">已初始化</div><div id="init" class="value mono" style="font-size:28px">false</div></div>
        </div>
                <p class="hint">数据来自 ROS2 话题：<span class="mono">/situp_count</span>、<span class="mono">/situp_status</span>、<span class="mono">{stats_topic}</span></p>
        <p class="hint">最新状态：<span id="status" class="mono">-</span></p>
        <p class="hint">时间戳：<span id="stamp" class="mono">-</span></p>
      </section>
      {safe_video_html}
    </div>
  </div>
  <script>
    const el = (id) => document.getElementById(id);
    const setText = (id, v) => (el(id).textContent = v);
    const dot = el("dot");
    let ok = false;
    async function tick() {{
      try {{
        const res = await fetch("/api/state", {{ cache: "no-store" }});
        if (!res.ok) throw new Error("http " + res.status);
        const s = await res.json();
        setText("count", String(s.count ?? 0));
        setText("state", s.state || "-");
        setText("fps", Number(s.fps || 0).toFixed(1));
        setText("direction", s.direction || "-");
        setText("init", String(!!s.initialized));
        setText("status", s.status_text || "-");
        if (typeof s.stamp_sec === "number" && typeof s.stamp_nanosec === "number") setText("stamp", s.stamp_sec + "." + String(s.stamp_nanosec).padStart(9,"0"));
        else setText("stamp", "-");
        if (!ok) {{ ok = true; dot.classList.add("ok"); setText("conn", "已连接"); }}
      }} catch (e) {{ ok = false; dot.classList.remove("ok"); setText("conn", "连接失败，重试中..."); }}
    }}
    tick();
    setInterval(tick, 250);
  </script>
</body>
</html>
"""


@dataclass
class SitUpWebState:
    count: int = 0
    state: str = ""
    fps: float = 0.0
    direction: str = ""
    initialized: bool = False
    status_text: str = ""
    stamp_sec: int = 0
    stamp_nanosec: int = 0


def _ros_param_bool(value) -> bool:
    """
    Launch 里用 LaunchConfiguration 传入的布尔常为字符串 \"true\"/\"false\"；
    Python 的 bool(\"false\") 为 True（非空串），会导致误开后端配置。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _build_index_html(
    serve_video_stream: bool,
    video_topic: str,
    stats_topic: str,
    video_stream_url: str,
    video_viewer_url: str,
    video_stream_port: int,
    video_stream_topic: str,
    video_stream_host: str,
) -> str:
    """生成首页 HTML。视频区支持：0) 本节点内置 /stream 1) 完整 video_stream_url 2) 同主机 port+topic 3) video_viewer_url。"""
    safe_video_html = ""
    if serve_video_stream:
        safe_video_html = f"""
        <section class="card">
          <h2>视频</h2>
          <div class="video-wrap">
            <img class="video video-img" src="/stream" alt="摄像头" />
          </div>
          <p class="hint">视频由本节点提供，话题 <span class="mono">{video_topic or "/pose_image"}</span>（pose_detector 直接打开摄像头）。</p>
        </section>
        """
        return _html_template(safe_video_html, stats_topic)

    use_same_host = video_stream_port > 0 and video_stream_topic.strip() and not video_stream_url.strip()

    if video_stream_url.strip():
        video_body = f'<img class="video video-img" src="{video_stream_url}" alt="mjpeg stream" />'
        safe_video_html = f"""
        <section class="card">
          <h2>视频</h2>
          <div class="video-wrap">
            {video_body}
          </div>
          <p class="hint">如果看不到视频，请确认 web_video_server 正在运行且地址可访问。</p>
        </section>
        """
    elif use_same_host:
        port_js = str(video_stream_port)
        topic_js = video_stream_topic.strip().replace("\\", "\\\\").replace("'", "\\'")
        # 若配置了 video_stream_host，用其作为 host，否则用当前页面的 hostname（解决 localhost 转发时视频请求错机器）
        host_js = video_stream_host.strip() if video_stream_host.strip() else ""
        if host_js:
            host_expr = json.dumps(host_js)
        else:
            host_expr = "window.location.hostname"
        video_body = """
        <img id="video-stream" class="video video-img" alt="mjpeg stream" />
        <script>
          (function(){
            var port = """ + json.dumps(port_js) + """;
            var topic = """ + json.dumps(topic_js) + """;
            var host = """ + host_expr + """;
            var el = document.getElementById("video-stream");
            if (el) el.src = "http://" + host + ":" + port + "/stream?topic=" + encodeURIComponent(topic);
          })();
        </script>
        """
        hint_host = host_js if host_js else "当前页同主机"
        safe_video_html = f"""
        <section class="card">
          <h2>视频</h2>
          <div class="video-wrap">
            {video_body}
          </div>
          <p class="hint">视频流：{hint_host} port {port_js}，topic <span class="mono">{topic_js}</span>。请确认 web_video_server 已启动。</p>
        </section>
        """
    elif video_viewer_url.strip():
        video_body = (
            f'<iframe class="video" src="{video_viewer_url}" loading="lazy" '
            f'referrerpolicy="no-referrer"></iframe>'
        )
        safe_video_html = f"""
        <section class="card">
          <h2>视频</h2>
          <div class="video-wrap">
            {video_body}
          </div>
          <p class="hint">如果看不到视频，请确认 web_video_server 正在运行且地址可访问。</p>
        </section>
        """

    return _html_template(safe_video_html, stats_topic)


class SitUpDashboardNode(Node):
    '''
    :brief Web 展示节点类
    :desc 起 HTTP 服务并订阅计数话题。
    '''

    def __init__(self) -> None:
        super().__init__("situp_web_dashboard")

        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8090)
        self.declare_parameter("serve_video_stream", True)
        self.declare_parameter("video_topic", "/pose_image")
        self.declare_parameter("video_stream_url", "")
        self.declare_parameter("video_viewer_url", "")
        self.declare_parameter("video_stream_port", 8081)
        self.declare_parameter("video_stream_topic", "/image_raw")
        self.declare_parameter("video_stream_host", "")
        self.declare_parameter("stats_topic", "/pose_video_stats")
        self.declare_parameter("ws_server_base_url", "ws://122.51.12.83:8000/ws/camera")
        self.declare_parameter("ws_device_id", "puppy_001")
        self.declare_parameter("ws_push_interval_sec", 0.25)
        self.declare_parameter("ws_push_video", True)
        # 后端配置加载开关与路径（建议统一走工作空间配置）
        self.declare_parameter("use_backend_config", True)
        self.declare_parameter("backend_config_path", _DEFAULT_BACKEND_CONFIG_PATH)
        # 为 true 时：等收到 situp_control start（或 situp_count 显示非 STOPPED）才开始上报
        self.declare_parameter("ws_wait_for_control_start", False)
        # 为空则禁用；配置后：仅当收到该话题任意消息才启动上报（用于「播报开始计数后再上传」）
        self.declare_parameter("ws_start_trigger_topic", "")

        host = str(self.get_parameter("host").value)
        port = int(self.get_parameter("port").value)
        serve_video_stream = _ros_param_bool(self.get_parameter("serve_video_stream").value)
        video_topic = str(self.get_parameter("video_topic").value).strip() or "/pose_image"
        video_stream_url = str(self.get_parameter("video_stream_url").value)
        video_viewer_url = str(self.get_parameter("video_viewer_url").value)
        video_stream_port = int(self.get_parameter("video_stream_port").value)
        video_stream_topic = str(self.get_parameter("video_stream_topic").value)
        video_stream_host = str(self.get_parameter("video_stream_host").value)
        stats_topic = str(self.get_parameter("stats_topic").value).strip() or "/pose_video_stats"
        ws_server_base_url = str(self.get_parameter("ws_server_base_url").value).strip()
        ws_device_id = str(self.get_parameter("ws_device_id").value).strip() or "puppy_001"
        ws_push_interval_sec = float(self.get_parameter("ws_push_interval_sec").value)
        ws_push_video = _ros_param_bool(self.get_parameter("ws_push_video").value)
        use_backend_config = _ros_param_bool(self.get_parameter("use_backend_config").value)
        backend_config_path = (
            str(self.get_parameter("backend_config_path").value).strip() or _DEFAULT_BACKEND_CONFIG_PATH
        )
        ws_wait_for_control_start = _ros_param_bool(self.get_parameter("ws_wait_for_control_start").value)
        ws_start_trigger_topic = str(self.get_parameter("ws_start_trigger_topic").value).strip()

        if use_backend_config:
            try:
                backend_cfg = load_backend_config(backend_config_path)
                ws_server_base_url = str(backend_cfg["backend"]["ws_camera_base_url"]).strip()
                ws_device_id = str(backend_cfg["device"]["device_id"]).strip() or ws_device_id
                self.get_logger().info(
                    "配置加载成功：%s（device_id=%s, ws_base=%s）"
                    % (backend_config_path, ws_device_id, ws_server_base_url)
                )
            except BackendConfigError as exc:
                raise RuntimeError(f"后端配置加载失败: {exc}") from exc
        else:
            # 本地模式：不读后端配置，也不使用参数里默认的 ws 地址（避免无意义重连）
            ws_server_base_url = ""

        ws_server_url = (ws_server_base_url.rstrip("/") + "/" + ws_device_id) if ws_server_base_url else ""

        self._state_lock = threading.Lock()
        self._state = SitUpWebState()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_jpeg_lock = threading.Lock()
        self._video_bridge = CvBridge() if serve_video_stream else None
        self._placeholder_jpeg = b""
        if serve_video_stream:
            try:
                import numpy as np
                _, ph = cv2.imencode(".jpg", np.zeros((1, 1, 3), dtype=np.uint8))
                self._placeholder_jpeg = ph.tobytes()
            except Exception:
                pass

        self.create_subscription(SitUpCount, "situp_count", self._on_count, 10)
        self.create_subscription(String, "situp_status", self._on_status, 10)
        self.create_subscription(String, "situp_control", self._on_control, 10)
        self.create_subscription(VideoStats, stats_topic, self._on_stats, 10)
        if ws_start_trigger_topic:
            self.create_subscription(String, ws_start_trigger_topic, self._on_ws_start_trigger, 10)
        if serve_video_stream:
            self.create_subscription(Image, video_topic, self._on_image, 5)

        html = _build_index_html(
            serve_video_stream,
            video_topic,
            stats_topic,
            video_stream_url,
            video_viewer_url,
            video_stream_port,
            video_stream_topic,
            video_stream_host,
        )
        handler = self._make_handler(html)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()

        self._ws_reporter: Optional[StateWsReporter] = None
        self._ws_wait_for_control_start = ws_wait_for_control_start
        self._ws_start_trigger_topic = ws_start_trigger_topic
        self._ws_running = False
        if ws_server_url:
            def _get_ws_payload() -> dict:
                with self._state_lock:
                    count = int(self._state.count)
                    fps = float(self._state.fps)
                out: dict = {
                    "type": "frame",
                    "device_id": ws_device_id,
                    "count": count,
                    "fps": fps,
                }
                if ws_push_video:
                    with self._latest_jpeg_lock:
                        jpeg = self._latest_jpeg
                    out["frame"] = base64.standard_b64encode(jpeg).decode("ascii") if jpeg else None
                else:
                    out["frame"] = None
                return out

            self._ws_reporter = StateWsReporter(
                ws_url=ws_server_url,
                push_interval_sec=ws_push_interval_sec,
                get_payload=_get_ws_payload,
                logger=self.get_logger(),
            )
            if self._ws_start_trigger_topic:
                self.get_logger().info(
                    f"WebSocket 上报已就绪（等待 {self._ws_start_trigger_topic} 才启动）：{ws_server_url}, "
                    f"间隔 {ws_push_interval_sec}s, 推送视频帧={ws_push_video}"
                )
            elif self._ws_wait_for_control_start:
                self.get_logger().info(
                    f"WebSocket 上报已就绪（等待 situp_control start / situp_count 非 STOPPED 才启动）：{ws_server_url}, "
                    f"间隔 {ws_push_interval_sec}s, 推送视频帧={ws_push_video}"
                )
            else:
                self._ws_reporter.start()
                self._ws_running = True
                self.get_logger().info(f"WebSocket 上报已启动: {ws_server_url}, 间隔 {ws_push_interval_sec}s, 推送视频帧={ws_push_video}")

        self.get_logger().info(f"Web 展示已启动：http://{host}:{port}/")
        if serve_video_stream:
            self.get_logger().info(f"内置视频流：订阅话题 {video_topic}，浏览器访问同地址 /stream 即可")
        elif video_stream_url.strip():
            self.get_logger().info(f"已配置 MJPEG 视频流：{video_stream_url}")
        elif video_stream_port > 0 and video_stream_topic.strip():
            self.get_logger().info(
                f"视频流使用「同主机」模式：port={video_stream_port}, topic={video_stream_topic}"
            )
            if video_stream_host.strip():
                self.get_logger().info(f"视频流固定 host：{video_stream_host.strip()}")
        if video_viewer_url.strip() and not video_stream_url.strip() and not (video_stream_port > 0 and video_stream_topic.strip()):
            self.get_logger().info(f"已配置视频 Viewer：{video_viewer_url}")

    def _on_count(self, msg: SitUpCount) -> None:
        with self._state_lock:
            self._state.count = int(msg.count)
            self._state.state = str(msg.state)
            self._state.direction = str(msg.direction)
            self._state.initialized = bool(msg.initialized)
            if hasattr(msg, "header") and hasattr(msg.header, "stamp"):
                self._state.stamp_sec = int(msg.header.stamp.sec)
                self._state.stamp_nanosec = int(msg.header.stamp.nanosec)
            state_now = str(msg.state)

        # 若配置了「播报开始计数后再上传」触发话题，则不在这里自动启动
        if self._ws_start_trigger_topic:
            return

        # 若配置为等待 start：当计数节点已进入非 STOPPED（例如非语音模式不会发 start）则自动启动上报
        if (
            self._ws_wait_for_control_start
            and (not self._ws_running)
            and self._ws_reporter is not None
            and state_now
            and state_now.strip().upper() != "STOPPED"
        ):
            self._ws_reporter.start()
            self._ws_running = True
            self.get_logger().info("WebSocket 上报已启动（由 situp_count 状态触发）")

    def _on_status(self, msg: String) -> None:
        with self._state_lock:
            self._state.status_text = str(msg.data)

    def _on_stats(self, msg: VideoStats) -> None:
        with self._state_lock:
            self._state.fps = float(msg.fps)

    def _on_control(self, msg: String) -> None:
        # 若配置了「播报开始计数后再上传」触发话题，则忽略 control start（但仍响应 stop 以停止上传）
        cmd = (msg.data or "").strip().lower()
        if self._ws_start_trigger_topic:
            if cmd == "stop":
                if self._ws_reporter is not None and self._ws_running:
                    self._ws_reporter.stop()
                    self._ws_running = False
                    self.get_logger().info("WebSocket 上报已停止（收到 situp_control stop）")
            return
        if cmd == "start":
            if self._ws_reporter is not None and not self._ws_running:
                self._ws_reporter.start()
                self._ws_running = True
                self.get_logger().info("WebSocket 上报已启动（收到 situp_control start）")
        elif cmd == "stop":
            if self._ws_reporter is not None and self._ws_running:
                self._ws_reporter.stop()
                self._ws_running = False
                self.get_logger().info("WebSocket 上报已停止（收到 situp_control stop）")

    def _on_ws_start_trigger(self, msg: String) -> None:
        if self._ws_reporter is None or self._ws_running:
            return
        self._ws_reporter.start()
        self._ws_running = True
        extra = (msg.data or "").strip()
        if extra:
            self.get_logger().info(f"WebSocket 上报已启动（触发：{self._ws_start_trigger_topic}，{extra}）")
        else:
            self.get_logger().info(f"WebSocket 上报已启动（触发：{self._ws_start_trigger_topic}）")

    def _on_image(self, msg: Image) -> None:
        if self._video_bridge is None:
            return
        try:
            frame = self._video_bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception:
            return
        _, jpeg = cv2.imencode(".jpg", frame)
        with self._latest_jpeg_lock:
            self._latest_jpeg = jpeg.tobytes()
        return

    def _make_handler(self, html: str):
        node_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:
                return

            def _send_json(self, obj) -> None:
                payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_html(self, body: str) -> None:
                payload = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _stream_mjpeg(self) -> None:
                boundary = b"frame"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary.decode()}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    while True:
                        with node_ref._latest_jpeg_lock:
                            jpeg = node_ref._latest_jpeg or node_ref._placeholder_jpeg
                        if not jpeg:
                            time.sleep(0.1)
                            continue
                        part = b"--" + boundary + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
                        try:
                            self.wfile.write(part)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                        time.sleep(1.0 / 30.0)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def do_GET(self) -> None:
                if self.path in ("/", "/index.html"):
                    return self._send_html(html)

                if self.path.startswith("/api/state"):
                    with node_ref._state_lock:
                        data = asdict(node_ref._state)
                    return self._send_json(data)

                if self.path == "/stream" and getattr(node_ref, "_video_bridge", None) is not None:
                    return self._stream_mjpeg()

                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()

        return Handler

    def destroy_node(self) -> bool:
        try:
            if hasattr(self, "_ws_reporter") and self._ws_reporter is not None:
                self._ws_reporter.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_httpd") and self._httpd is not None:
                self._httpd.shutdown()
                self._httpd.server_close()
        except Exception:
            pass
        return super().destroy_node()


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node = SitUpDashboardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

