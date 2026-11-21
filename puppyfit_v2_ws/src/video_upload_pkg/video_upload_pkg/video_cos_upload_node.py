#!/usr/bin/env python3
'''
:brief 会话录像 COS 上传节点
:desc 订阅 SessionRecordDone，经 STS 临时密钥直传腾讯云 COS，再 POST notify 登记元数据。
     HTTP 鉴权与 401 重登复用 BackendAdapter；大文件走分片上传。

:author slt
:date 2026/04/20
:version 1.0.0
:history
    1.0.1 - 2026/04/20
        :brief 回调内拷贝 SessionRecordDone 再进线程；COS 上传与 STS/notify 共用 max_retries 退避重试
    1.0.0 - 2026/04/20
        :brief 初始版本：STS → COS → notify，可选上传状态话题与删本地文件
'''

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import rclpy
from rclpy.node import Node
from exercise_engine_pkg.core.backend_adapter import BackendAdapter, BackendAdapterError
from session_record_msgs.msg import SessionRecordDone
from std_msgs.msg import String


def _etag_from_cos(resp: Any) -> str:
    '''
    :brief 从 COS SDK 返回结果中解析 ETag 字符串
    :param resp: put_object / upload_file 返回值
    :return 去掉引号的 ETag，无法解析时为空字符串
    '''
    if resp is None:
        return ""
    if isinstance(resp, dict):
        e = resp.get("ETag") or resp.get("Etag") or ""
        return str(e).strip('"')
    return ""


@dataclass(frozen=True)
class _RecordDoneSnapshot:
    '''
    :brief 订阅回调里从 SessionRecordDone 拷贝出的不可变快照
    :desc 避免 rclpy 消息在回调返回后被复用，后台线程读到脏数据
    '''

    session_id: str
    file_path: str
    duration_sec: float


class VideoCosUploadNode(Node):
    '''
    :brief 录像落盘后的 COS 上传与 notify
    :desc 在独立线程中执行 STS、上传、notify，避免阻塞订阅回调。
    '''

    def __init__(self) -> None:
        '''
        :brief 声明参数、订阅 SessionRecordDone、可选发布上传状态
        '''
        super().__init__("video_cos_upload")

        self.declare_parameter("backend_config_path", "")
        self.declare_parameter("record_done_topic", "session/record_done")
        self.declare_parameter("upload_status_topic", "")
        self.declare_parameter("default_user_id", "")
        self.declare_parameter("default_task_id", "")
        self.declare_parameter("max_retries", 3)
        self.declare_parameter("retry_delay_sec", 2.0)
        self.declare_parameter("delete_local_after_upload", False)
        self.declare_parameter("cos_multipart_threshold_bytes", 20 * 1024 * 1024)

        self._backend_path = (
            self.get_parameter("backend_config_path").get_parameter_value().string_value or ""
        ).strip()
        self._max_retries = max(1, int(self.get_parameter("max_retries").value))
        self._retry_delay = float(self.get_parameter("retry_delay_sec").value)
        self._delete_local = bool(
            self.get_parameter("delete_local_after_upload").get_parameter_value().bool_value
        )
        self._multipart_threshold = int(self.get_parameter("cos_multipart_threshold_bytes").value)

        self._default_user_id = (
            self.get_parameter("default_user_id").get_parameter_value().string_value or ""
        ).strip()
        self._default_task_id = (
            self.get_parameter("default_task_id").get_parameter_value().string_value or ""
        ).strip()

        if not self._backend_path:
            raise RuntimeError("video_cos_upload: backend_config_path 不能为空")

        self._adapter: Optional[BackendAdapter] = None

        rd_topic = (
            self.get_parameter("record_done_topic").get_parameter_value().string_value or ""
        ).strip()
        if not rd_topic:
            raise RuntimeError("video_cos_upload: record_done_topic 不能为空")

        self.create_subscription(SessionRecordDone, rd_topic, self._on_record_done, 10)

        us_topic = (
            self.get_parameter("upload_status_topic").get_parameter_value().string_value or ""
        ).strip()
        self._status_pub = self.create_publisher(String, us_topic, 10) if us_topic else None

        self.get_logger().info(
            f"video_cos_upload 已启动 config={self._backend_path} subscribe={rd_topic}"
        )

    def _get_adapter(self) -> BackendAdapter:
        '''
        :brief 懒加载 BackendAdapter
        :return 已绑定配置的适配器实例
        '''
        if self._adapter is None:
            self._adapter = BackendAdapter(self._backend_path)
        return self._adapter

    def _on_record_done(self, msg: SessionRecordDone) -> None:
        '''
        :brief 收到落盘完成消息，拷贝字段后启动上传流水线线程
        :param msg: SessionRecordDone
        '''
        snap = _RecordDoneSnapshot(
            session_id=(msg.session_id or "").strip(),
            file_path=(msg.file_path or "").strip(),
            duration_sec=float(msg.duration_sec),
        )
        t = threading.Thread(target=self._upload_pipeline, args=(snap,), daemon=True)
        t.start()

    def _publish_status(self, session_id: str, status: str, detail: str) -> None:
        '''
        :brief 若配置了 upload_status_topic，发布 JSON 状态字符串
        :param session_id: 会话 id
        :param status: uploading / success / error
        :param detail: 人类可读说明
        '''
        if self._status_pub is None:
            return
        s = String()
        s.data = json.dumps(
            {"session_id": session_id, "status": status, "detail": detail},
            ensure_ascii=False,
        )
        self._status_pub.publish(s)

    def _upload_pipeline(self, snap: _RecordDoneSnapshot) -> None:
        '''
        :brief STS → COS 上传 → notify 主流程
        :param snap: 落盘完成消息的线程安全快照
        '''
        session_id = snap.session_id
        file_path = snap.file_path
        if not session_id or not file_path:
            self.get_logger().warning("SessionRecordDone 缺少 session_id 或 file_path，跳过")
            return
        if not os.path.isfile(file_path):
            self._publish_status(session_id, "error", "文件不存在")
            self.get_logger().error(f"上传跳过，文件不存在: {file_path}")
            return

        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            self._publish_status(session_id, "error", str(e))
            self.get_logger().error(f"读取文件大小失败: {e}")
            return

        file_name = os.path.basename(file_path)
        user_id = self._default_user_id
        task_id = self._default_task_id

        self._publish_status(session_id, "uploading", "获取 STS…")
        sts = self._request_sts(session_id, file_name, file_size)
        if sts is None:
            self._publish_status(session_id, "error", "STS 失败")
            return

        self._publish_status(session_id, "uploading", "上传 COS…")
        etag = self._upload_to_cos(
            file_path=file_path,
            credentials=sts["credentials"],
            region=sts["region"],
            bucket=sts["bucket"],
            cos_key=sts["cos_key"],
            file_size=file_size,
        )
        if etag is None:
            self._publish_status(session_id, "error", "COS 上传失败")
            return

        self._publish_status(session_id, "uploading", "notify 后端…")
        ok = self._notify_backend(
            session_id=session_id,
            cos_key=sts["cos_key"],
            file_size=file_size,
            user_id=user_id,
            task_id=task_id,
            etag=etag,
            duration_sec=snap.duration_sec,
        )
        if not ok:
            self._publish_status(session_id, "error", "notify 失败")
            return

        self._publish_status(session_id, "success", "notify 成功")
        if self._delete_local:
            try:
                os.remove(file_path)
                self.get_logger().info(f"已删除本地文件: {file_path}")
            except OSError as e:
                self.get_logger().warning(f"删除本地文件失败: {e}")

    def _request_sts(
        self, session_id: str, file_name: str, file_size: int
    ) -> Optional[Dict[str, Any]]:
        '''
        :brief POST api_paths.sts_token 获取临时密钥与 cos_key
        :param session_id: 训练会话 id
        :param file_name: 本地文件名
        :param file_size: 字节数
        :return credentials/region/bucket/cos_key 字典，失败为 None
        '''
        ad = self._get_adapter()
        device_id = str(ad.device.get("device_id", "")).strip()
        payload = {
            "device_id": device_id,
            "session_id": session_id,
            "file_name": file_name,
            "content_type": "video/mp4",
            "file_size": int(file_size),
        }
        for attempt in range(1, self._max_retries + 1):
            try:
                status, data = ad.post_json_to_api_path("sts_token", payload)
                if status == 200 and int(data.get("code", status)) == 200:
                    inner = data.get("data") or {}
                    if not isinstance(inner, dict):
                        self.get_logger().warning(f"STS data 非 dict: {data}")
                        return None
                    creds = inner.get("credentials")
                    if not isinstance(creds, dict):
                        self.get_logger().warning(f"STS 缺少 credentials: {inner}")
                        return None
                    return {
                        "credentials": creds,
                        "region": str(inner.get("region", "")).strip(),
                        "bucket": str(inner.get("bucket", "")).strip(),
                        "cos_key": str(inner.get("cos_key", "")).strip(),
                    }
                self.get_logger().warning(f"STS HTTP 失败: status={status} body={data}")
            except BackendAdapterError as e:
                self.get_logger().warning(f"STS 异常 (第{attempt}次): {e}")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning(f"STS 异常 (第{attempt}次): {e}")
            if attempt < self._max_retries:
                time.sleep(self._retry_delay * attempt)
        return None

    def _upload_to_cos(
        self,
        file_path: str,
        credentials: Dict[str, Any],
        region: str,
        bucket: str,
        cos_key: str,
        file_size: int,
    ) -> Optional[str]:
        '''
        :brief 使用 STS 临时密钥向 COS 写入对象
        :desc 小于阈值用 put_object，否则 upload_file 分片。
        :param file_path: 本地 MP4 绝对路径
        :param credentials: tmpSecretId / tmpSecretKey / sessionToken
        :param region: COS region
        :param bucket: 存储桶名
        :param cos_key: 对象键（须与 STS、notify 一致）
        :param file_size: 文件字节数
        :return ETag 或占位标记字符串，失败为 None
        '''
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError:
            self.get_logger().error("未安装 cos-python-sdk-v5，无法上传 COS")
            return None

        if not region or not bucket or not cos_key:
            self.get_logger().error("STS 返回缺少 region/bucket/cos_key")
            return None

        sid = str(credentials.get("tmpSecretId", "")).strip()
        sk = str(credentials.get("tmpSecretKey", "")).strip()
        tok = str(credentials.get("sessionToken", "")).strip()
        if not sid or not sk:
            self.get_logger().error("STS credentials 缺少 tmpSecretId/tmpSecretKey")
            return None

        for attempt in range(1, self._max_retries + 1):
            try:
                cfg = CosConfig(
                    Region=region,
                    SecretId=sid,
                    SecretKey=sk,
                    Token=tok,
                    Scheme="https",
                )
                client = CosS3Client(cfg)
                if file_size < self._multipart_threshold:
                    with open(file_path, "rb") as f:
                        resp = client.put_object(
                            Bucket=bucket,
                            Body=f,
                            Key=cos_key,
                            ContentType="video/mp4",
                        )
                    return _etag_from_cos(resp) or "put_object_ok"
                resp = client.upload_file(
                    Bucket=bucket,
                    Key=cos_key,
                    LocalFilePath=file_path,
                    PartSize=10,
                    MAXThread=4,
                    EnableMD5=False,
                )
                return _etag_from_cos(resp) or "multipart_ok"
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning(
                    f"COS 上传失败 (第{attempt}/{self._max_retries}次): {e}"
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay * attempt)
        return None

    def _notify_backend(
        self,
        session_id: str,
        cos_key: str,
        file_size: int,
        user_id: str,
        task_id: str,
        etag: str,
        duration_sec: float,
    ) -> bool:
        '''
        :brief POST api_paths.video_notify 通知后端写库
        :param session_id: 会话 id
        :param cos_key: 已上传对象键
        :param file_size: 字节数
        :param user_id: 业务用户 id（可由参数默认）
        :param task_id: 可选任务 id
        :param etag: COS 返回的 ETag
        :param duration_sec: 时长（秒），小于 0 时不写入 payload
        :return 是否 HTTP 与业务 code 均成功
        '''
        ad = self._get_adapter()
        device_id = str(ad.device.get("device_id", "")).strip()
        payload: Dict[str, Any] = {
            "device_id": device_id,
            "session_id": session_id,
            "cos_key": cos_key,
            "file_size": int(file_size),
            "user_id": user_id,
        }
        if task_id:
            payload["task_id"] = task_id
        if etag:
            payload["etag"] = etag
        if duration_sec >= 0.0:
            payload["duration_sec"] = int(round(duration_sec))

        for attempt in range(1, self._max_retries + 1):
            try:
                status, data = ad.post_json_to_api_path("video_notify", payload)
                if status == 200 and int(data.get("code", status)) == 200:
                    inner = data.get("data") or {}
                    vid = inner.get("video_id", "") if isinstance(inner, dict) else ""
                    self.get_logger().info(f"notify 成功 video_id={vid}")
                    return True
                self.get_logger().warning(f"notify 失败: status={status} body={data}")
            except BackendAdapterError as e:
                self.get_logger().warning(f"notify 异常 (第{attempt}次): {e}")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning(f"notify 异常 (第{attempt}次): {e}")
            if attempt < self._max_retries:
                time.sleep(self._retry_delay * attempt)
        return False


def main(args: Optional[Any] = None) -> None:
    '''
    :brief 节点入口：spin 直至中断
    :param args: 透传 rclpy.init
    '''
    rclpy.init(args=args)
    try:
        node = VideoCosUploadNode()
    except RuntimeError as e:
        print(f"video_cos_upload 启动失败: {e}")
        rclpy.shutdown()
        return
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
