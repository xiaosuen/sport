#!/usr/bin/env python3
'''
:brief 会话级视频录制节点（FFmpeg 管道）
:desc 订阅 SessionRecordStart/Stop 与 sensor_msgs/Image；在会话区间内将 BGR 原始帧写入 stdin，
      由 FFmpeg 编码为 MP4（默认 libx264；树莓派 V4L2 可用时可设 h264_v4l2m2m）。
      图像仅经 cv_bridge 转 numpy，不使用 OpenCV VideoWriter；图像 QoS depth=1，队列满时丢旧帧。

:author slt
:date 2026/04/01
:version 1.5.0
:history
    1.5.0 - 2026/04/27
        :brief 新增会话录像时长硬上限（默认 600 秒）
        :desc 参数 max_record_duration_sec；超时后自动停录并复用 SessionRecordDone 上报链路
    1.4.0 - 2026/04/20
        :brief 成功落盘且退出码为 0 时发布 SessionRecordDone；参数 record_done_topic
    1.3.0 - 2026/04/01
        :brief FFmpeg + 可配置编码器替代 VideoWriter；写入线程与有界队列；launch 支持 session_video_encoder
    1.0.0 - 2026/03/29
        :brief 初始会话录像（OpenCV VideoWriter + mp4v）
'''

from __future__ import annotations

import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image
from session_record_msgs.msg import SessionRecordDone, SessionRecordStart, SessionRecordStop

_writer_log = logging.getLogger("video_record_pkg.session_video_record.writer")


def _safe_filename_part(s: str, max_len: int = 80) -> str:
    '''
    :brief 将 session_id 等字符串整理为安全文件名片段
    :param s: 原始字符串
    :param max_len: 最大长度
    :return 仅含字母数字与 ._- 的截断字符串；空则 unknown
    '''
    s = (s or "").strip()
    if not s:
        return "unknown"
    out = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return out[:max_len] if len(out) > max_len else out


class SessionVideoRecordNode(Node):
    '''
    :brief 按 session_id 配对开停，FFmpeg 写入 MP4
    :desc 首帧到达时启动 ffmpeg 子进程与写线程；stop 或析构时关 stdin 并 wait，必要时 kill。
    '''

    def __init__(self) -> None:
        '''
        :brief 声明参数、创建订阅（图像 QoS depth=1）、校验 output_dir 与 ffmpeg 可执行性
        '''
        super().__init__("session_video_record")

        self.declare_parameter("record_start_topic", "session/record_start")
        self.declare_parameter("record_stop_topic", "session/record_stop")
        self.declare_parameter("image_topic", "/pose_image")
        self.declare_parameter("output_dir", "")
        self.declare_parameter("fps", 20.0)
        self.declare_parameter("file_prefix", "situp")
        self.declare_parameter("ffmpeg_path", "ffmpeg")
        self.declare_parameter("video_encoder", "libx264")
        self.declare_parameter("record_done_topic", "session/record_done")
        self.declare_parameter("max_record_duration_sec", 600.0)

        self._start_topic = (
            self.get_parameter("record_start_topic").get_parameter_value().string_value or ""
        ).strip()
        self._stop_topic = (
            self.get_parameter("record_stop_topic").get_parameter_value().string_value or ""
        ).strip()
        self._image_topic = (
            self.get_parameter("image_topic").get_parameter_value().string_value or "/pose_image"
        ).strip() or "/pose_image"
        self._output_dir = (self.get_parameter("output_dir").get_parameter_value().string_value or "").strip()
        try:
            self._fps = float(self.get_parameter("fps").value)
        except (TypeError, ValueError):
            self._fps = 20.0
        if self._fps <= 0:
            self._fps = 20.0
        self._file_prefix = (
            self.get_parameter("file_prefix").get_parameter_value().string_value or "situp"
        ).strip() or "situp"
        self._ffmpeg_path = (
            self.get_parameter("ffmpeg_path").get_parameter_value().string_value or "ffmpeg"
        ).strip() or "ffmpeg"
        self._video_encoder = (
            self.get_parameter("video_encoder").get_parameter_value().string_value or "libx264"
        ).strip() or "libx264"
        try:
            self._max_record_duration_sec = float(self.get_parameter("max_record_duration_sec").value)
        except (TypeError, ValueError):
            self._max_record_duration_sec = 600.0
        if self._max_record_duration_sec < 0.0:
            self._max_record_duration_sec = 0.0
        _rd_topic = (
            self.get_parameter("record_done_topic").get_parameter_value().string_value or ""
        ).strip()
        self._record_done_pub = (
            self.create_publisher(SessionRecordDone, _rd_topic, 10) if _rd_topic else None
        )

        if not self._output_dir:
            self.get_logger().error("output_dir 为空，无法录像")
            raise RuntimeError("session_video_record: output_dir 不能为空")

        os.makedirs(self._output_dir, exist_ok=True)

        self._bridge = CvBridge()
        self._active_id: str | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._writer_thread: threading.Thread | None = None
        self._path: str | None = None
        self._frame_size: tuple[int, int] | None = None
        self._frame_q: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        self._writer_lock = threading.Lock()
        self._auto_stop_timer = None

        self.create_subscription(SessionRecordStart, self._start_topic, self._on_start, 10)
        self.create_subscription(SessionRecordStop, self._stop_topic, self._on_stop, 10)

        _img_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.create_subscription(Image, self._image_topic, self._on_image, _img_qos)

        self.get_logger().info(
            f"会话录像已启动：start=[{self._start_topic}] stop=[{self._stop_topic}] "
            f"image=[{self._image_topic}] dir=[{self._output_dir}] fps={self._fps} "
            f"encoder={self._video_encoder} ffmpeg={self._ffmpeg_path} "
            f"max_duration={self._max_record_duration_sec}s "
            f"record_done=[{_rd_topic or '(关闭)'}]"
        )

        if not shutil.which(self._ffmpeg_path):
            self.get_logger().error(
                f"未在 PATH 中找到 {self._ffmpeg_path}，请安装 ffmpeg 或使用参数 ffmpeg_path"
            )

    def _drain_frame_queue(self) -> None:
        '''
        :brief 清空帧队列中残留项，避免跨会话串帧
        '''
        while True:
            try:
                self._frame_q.get_nowait()
            except queue.Empty:
                break

    def _cancel_auto_stop_timer(self) -> None:
        timer = self._auto_stop_timer
        self._auto_stop_timer = None
        if timer is None:
            return
        try:
            timer.cancel()
        except Exception:
            pass
        try:
            self.destroy_timer(timer)
        except Exception:
            pass

    def _arm_auto_stop_timer(self, sid: str) -> None:
        self._cancel_auto_stop_timer()
        if self._max_record_duration_sec <= 0.0:
            return

        def _on_timeout() -> None:
            self._cancel_auto_stop_timer()
            if self._active_id != sid:
                return
            self.get_logger().warning(
                f"录像达到时长上限 {self._max_record_duration_sec:.1f}s，自动停录 session_id={sid}"
            )
            self._release_writer()
            self._active_id = None

        self._auto_stop_timer = self.create_timer(self._max_record_duration_sec, _on_timeout)

    def _build_ffmpeg_cmd(self, w: int, h: int, path: str) -> list[str]:
        '''
        :brief 组装 ffmpeg 命令行（rawvideo BGR → yuv420p MP4）
        :param w: 帧宽
        :param h: 帧高
        :param path: 输出 mp4 绝对路径
        :return 参数列表
        '''
        cmd: list[str] = [
            self._ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            str(self._fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            self._video_encoder,
        ]
        if self._video_encoder == "libx264":
            cmd.extend(["-preset", "veryfast", "-crf", "23"])
        cmd.extend(["-pix_fmt", "yuv420p", path])
        return cmd

    def _open_ffmpeg(self, w: int, h: int, path: str) -> subprocess.Popen | None:
        '''
        :brief 启动 ffmpeg 子进程并做短时存活检测
        :param w: 帧宽
        :param h: 帧高
        :param path: 输出路径
        :return 成功返回 Popen；立即退出或启动失败返回 None
        '''
        cmd = self._build_ffmpeg_cmd(w, h, path)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            self.get_logger().error(f"无法启动 ffmpeg: {e}")
            return None

        time.sleep(0.08)
        if proc.poll() is not None:
            err_b = b""
            try:
                if proc.stderr:
                    err_b = proc.stderr.read()
            except Exception:
                pass
            err = err_b.decode(errors="replace").strip()
            self.get_logger().error(f"ffmpeg 立即退出 rc={proc.returncode}：{err or '(无 stderr)'}")
            return None
        return proc

    def _writer_loop(self, proc: subprocess.Popen) -> None:
        '''
        :brief 后台线程：从队列取 BGR 字节写入 ffmpeg stdin，遇 None 结束并关闭 stdin
        :param proc: 已启动的 ffmpeg 进程
        '''
        try:
            while True:
                item = self._frame_q.get()
                if item is None:
                    break
                if proc.stdin:
                    proc.stdin.write(item)
        except BrokenPipeError:
            err = ""
            try:
                if proc.stderr:
                    err = proc.stderr.read().decode(errors="replace").strip()
            except Exception:
                pass
            if err:
                _writer_log.error("ffmpeg stdin BrokenPipe，stderr: %s", err[-3000:])
            else:
                _writer_log.error(
                    "ffmpeg stdin BrokenPipe（编码进程已退出）。"
                    "使用 h264_v4l2m2m 时请确认 V4L2 编码设备可用，或改用参数 video_encoder:=libx264"
                )
        except Exception:
            _writer_log.exception("写入 ffmpeg 失败")
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass

    def _ensure_writer_started(self, w: int, h: int) -> bool:
        '''
        :brief 首帧时创建输出文件、启动 ffmpeg 与写线程（幂等）
        :param w: 帧宽
        :param h: 帧高
        :return 成功 True；ffmpeg 失败则清空 active_id 并返回 False
        '''
        with self._writer_lock:
            if self._ffmpeg_proc is not None:
                return True
            safe = _safe_filename_part(self._active_id or "")
            fname = f"{self._file_prefix}_{safe}_{int(time.time())}.mp4"
            path = os.path.join(self._output_dir, fname)
            proc = self._open_ffmpeg(w, h, path)
            if proc is None:
                self._active_id = None
                return False
            self._ffmpeg_proc = proc
            self._path = path
            self._frame_size = (w, h)
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                args=(proc,),
                daemon=True,
            )
            self._writer_thread.start()
            self.get_logger().info(
                f"写入录像(ffmpeg): {path} ({w}x{h}@{self._fps} {self._video_encoder})"
            )
            return True

    def _release_writer(self) -> None:
        '''
        :brief 结束当前文件：发队列哨兵、join 写线程、wait/kill ffmpeg、清空队列
        :desc ffmpeg 成功且文件非空时，若配置了 record_done_topic，则发布 SessionRecordDone。
        '''
        self._cancel_auto_stop_timer()

        t: threading.Thread | None = None
        proc: subprocess.Popen | None = None
        path_done: str | None = None
        with self._writer_lock:
            t = self._writer_thread
            proc = self._ffmpeg_proc
            path_done = self._path
            self._writer_thread = None
            self._ffmpeg_proc = None
            self._path = None
            self._frame_size = None

        if t is not None:
            self._frame_q.put(None)
            t.join(timeout=120.0)
            if t.is_alive():
                self.get_logger().error("录像写入线程未在超时内结束")

        if proc is not None:
            if proc.poll() is None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
            err_tail = ""
            try:
                if proc.stderr:
                    err_b = proc.stderr.read()
                    err_tail = err_b.decode(errors="replace").strip()
            except Exception:
                pass
            try:
                proc.wait(timeout=60.0)
            except subprocess.TimeoutExpired:
                self.get_logger().error("ffmpeg 未在超时内退出，将终止进程")
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
            if proc.returncode not in (0, None):
                self.get_logger().warning(
                    f"ffmpeg 退出码={proc.returncode} stderr: {err_tail[-800:] if err_tail else '(空)'}"
                )

        if path_done:
            self.get_logger().info(f"录像已关闭: {path_done}")

        rc = -1
        if proc is not None and proc.returncode is not None:
            rc = int(proc.returncode)

        if (
            self._record_done_pub is not None
            and path_done
            and proc is not None
            and rc == 0
            and os.path.isfile(path_done)
        ):
            try:
                sz = os.path.getsize(path_done)
            except OSError:
                sz = 0
            if sz > 0:
                sid = (self._active_id or "").strip()
                if sid:
                    done = SessionRecordDone()
                    done.session_id = sid
                    done.stamp = self.get_clock().now().to_msg()
                    done.file_path = path_done
                    done.file_size = int(sz)
                    done.duration_sec = -1.0
                    self._record_done_pub.publish(done)
                    self.get_logger().info(
                        f"已发布 SessionRecordDone session_id={sid} size={sz} path={path_done}"
                    )
                else:
                    self.get_logger().warning("录像成功但 session_id 为空，跳过 SessionRecordDone")

        self._drain_frame_queue()

    def _on_start(self, msg: SessionRecordStart) -> None:
        '''
        :brief 处理 SessionRecordStart，进入录制态；若有未停会话则先关闭
        :param msg: 含 session_id 的开始消息
        '''
        sid = (msg.session_id or "").strip()
        if not sid:
            self.get_logger().warn("SessionRecordStart.session_id 为空，忽略")
            return
        if self._active_id is not None:
            self.get_logger().warn(f"新会话开始，关闭上一段录像 active={self._active_id}")
            self._cancel_auto_stop_timer()
            self._release_writer()
        self._drain_frame_queue()
        self._active_id = sid
        self._arm_auto_stop_timer(sid)
        self.get_logger().info(f"开录 session_id={sid}")

    def _on_stop(self, msg: SessionRecordStop) -> None:
        '''
        :brief 处理 SessionRecordStop，session_id 匹配则停录并释放资源
        :param msg: 含 session_id 的结束消息
        '''
        sid = (msg.session_id or "").strip()
        if not sid or self._active_id is None:
            return
        if sid != self._active_id:
            self.get_logger().debug(f"忽略 stop（id 不匹配） got={sid} active={self._active_id}")
            return
        self._cancel_auto_stop_timer()
        self._release_writer()
        self._active_id = None

    def _on_image(self, msg: Image) -> None:
        '''
        :brief 图像回调：转 BGR、必要时启动 ffmpeg，将帧字节入队（满则丢旧）
        :param msg: sensor_msgs/Image
        '''
        if self._active_id is None:
            return
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as e:
            self.get_logger().error(f"cv_bridge 转换失败: {e}")
            return
        h, w = frame.shape[:2]
        if not frame.flags["C_CONTIGUOUS"]:
            frame = frame.copy()

        if self._ffmpeg_proc is None:
            if not self._ensure_writer_started(w, h):
                return
        elif self._frame_size is not None and (w, h) != self._frame_size:
            return

        data = frame.tobytes()
        try:
            self._frame_q.put_nowait(data)
        except queue.Full:
            try:
                self._frame_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_q.put_nowait(data)
            except queue.Full:
                pass


def main(args=None) -> None:
    '''
    :brief 节点入口：spin，退出时释放录像与 shutdown
    :param args: 透传 rclpy.init
    '''
    rclpy.init(args=args)
    node = SessionVideoRecordNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._release_writer()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
