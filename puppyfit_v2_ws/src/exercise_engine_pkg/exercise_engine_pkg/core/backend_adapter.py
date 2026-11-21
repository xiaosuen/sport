#!/usr/bin/env python3
'''
:brief 终端后端 HTTP 适配层
:desc 封装登录、设备注册、计数上报，并支持 401 自动重登后重试一次。

:author slt
:date 2026/03/25
:version 1.0.4
:history
    1.0.4 - 2026/04/23
        :brief 移除 __main__ 冒烟/CLI，避免与包内 import 混淆；需联调时自行写脚本或 pytest 调用 BackendAdapter
    1.0.3 - 2026/04/20
        :brief 新增 post_json_to_api_path：从 backend.api_paths 按键取路径（如 sts_token、video_notify），
              与 http_base_url 拼成完整 URL 后 POST JSON，复用既有 Bearer 与 401 自动重登；解决终端侧
              「新接口路径只配在 JSON、无专用封装函数」时的重复代码问题，供录像上传 COS 等节点调用。
    1.0.1 - 2026/03/25
        :brief 封装登录、设备注册、计数上报与 401 自动重登重试
    1.0.0 - 2026/03/24
        :brief 初始版本，提供终端对接后端的核心 HTTP 能力
'''

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple
from urllib import error, request
from urllib.parse import urlencode

from exercise_engine_pkg.core.config_loader import load_backend_config


class BackendAdapterError(RuntimeError):
    """后端适配层异常。"""


class BackendAdapter:
    '''
    :brief 后端 HTTP 适配器
    :desc 提供登录、设备注册、计数上报能力，并处理 token 缓存和 401 自动重登。
    '''

    def __init__(self, config_path: str = "puppyfit_v2_ws/config/backend_config.json"):
        self.config = load_backend_config(config_path)
        self.http_base_url = str(self.config["backend"]["http_base_url"]).rstrip("/")
        self.api_paths = self.config["backend"]["api_paths"]
        self.device = self.config["device"]
        self.auth = self.config["auth"]
        self.network = self.config.get("network", {})
        self.http_timeout_sec = int(self.network.get("http_timeout_sec", 8))
        self.token: Optional[str] = None

    def _build_url(self, path_key: str) -> str:
        path = str(self.api_paths[path_key]).strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.http_base_url}{path}"

    def _build_url_with_query(self, path_key: str, query: Dict[str, Any]) -> str:
        base = self._build_url(path_key)
        filtered = {k: v for k, v in query.items() if v is not None and str(v) != ""}
        if not filtered:
            return base
        return f"{base}?{urlencode(filtered)}"

    def _http_json(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        with_auth: bool = True,
    ) -> Tuple[int, Dict[str, Any]]:
        body = None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if with_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = request.Request(url=url, data=body, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.http_timeout_sec) as resp:
                status = int(resp.getcode())
                raw = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw) if raw else {}
                return status, data
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            data = {}
            if raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"message": raw}
            return int(exc.code), data
        except Exception as exc:
            raise BackendAdapterError(f"HTTP 请求失败: {method} {url} -> {exc}") from exc

    def login(self) -> Dict[str, Any]:
        """
        :brief 登录并缓存 token
        :return: 登录响应 data
        """
        url = self._build_url("login")
        payload = {
            "username": self.auth["username"],
            "password": self.auth["password"],
            "type": self.auth["login_type"],
        }
        status, data = self._http_json("POST", url, payload=payload, with_auth=False)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"登录失败: status={status}, resp={data}")

        token = ((data.get("data") or {}).get("token") or "").strip()
        if not token:
            raise BackendAdapterError(f"登录响应缺少 token: {data}")
        self.token = token
        return data

    def _request_with_reauth(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """
        :brief 带 401 自动重登的一次请求
        :desc 首次请求若返回 401，则自动 login 后重试一次。
        """
        if not self.token:
            self.login()

        status, data = self._http_json(method, url, payload=payload, with_auth=True)
        if status == 401:
            self.login()
            status, data = self._http_json(method, url, payload=payload, with_auth=True)
        return status, data

    def post_json_to_api_path(self, path_key: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        '''
        :brief 向 backend.api_paths[path_key] 所配置的相对路径 POST JSON
        :desc 携带 Bearer 登录态，走 _request_with_reauth（401 时重登后重试一次）。
        :param path_key: api_paths 中的键名（如 sts_token、video_notify）
        :param payload: JSON 请求体
        :return (HTTP 状态码, 解析后的 JSON 字典)
        '''
        path = str(self.api_paths.get(path_key, "")).strip()
        if not path:
            raise BackendAdapterError(f"api_paths 缺少键: {path_key}")
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.http_base_url}{path}"
        return self._request_with_reauth("POST", url, payload=payload)

    def register_device(self, register_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        :brief 设备注册
        :desc 支持终端字段到后端字段的最小兼容映射。
        """
        url = self._build_url("device_register")

        payload = register_payload.copy() if register_payload else {}
        payload.setdefault("device_id", self.device["device_id"])
        payload.setdefault("device_name", self.device.get("device_name"))
        payload.setdefault("firmware_version", self.device.get("firmware_version"))
        payload.setdefault("status", "online")
        payload.setdefault("device_type", "puppy")

        # 文档兼容：model 字段映射到后端 device_type。
        if "model" in payload and payload.get("model") and not payload.get("device_type"):
            payload["device_type"] = payload.get("model")

        # 保留文档字段（如 mac_address/model）以便后续后端升级兼容；
        # 当前后端若不使用这些字段会自动忽略。
        payload = {k: v for k, v in payload.items() if v is not None}

        status, data = self._request_with_reauth("POST", url, payload=payload)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"设备注册失败: status={status}, resp={data}")
        return data

    def report_count(
        self,
        current_count: Optional[int] = None,
        task_id: Optional[str] = None,
        count_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        :brief 计数上报
        :desc 将终端 current_count 映射为后端字段 count。
        """
        url = self._build_url("workout_count")
        payload = count_payload.copy() if count_payload else {}

        # 文档兼容：current_count -> count
        if current_count is not None:
            payload["count"] = int(current_count)
        if "count" not in payload and payload.get("current_count") is not None:
            payload["count"] = int(payload["current_count"])

        if task_id:
            payload["task_id"] = task_id

        if payload.get("count") is None:
            raise BackendAdapterError("计数上报缺少 count（或 current_count）")

        # 当前后端重点字段为 count/task_id；其他文档字段保留透传（后端可忽略）。

        status, data = self._request_with_reauth("POST", url, payload=payload)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"计数上报失败: status={status}, resp={data}")
        return data

    def report_heartbeat(
        self,
        battery: Optional[int] = None,
        status_text: str = "online",
        ip: Optional[str] = None,
        firmware_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        :brief 心跳近似上报
        :desc 使用后端现有 POST /api/device/status 实现心跳近似能力。
        """
        url = self._build_url("device_status")
        payload: Dict[str, Any] = {
            "device_id": self.device["device_id"],
            "status": status_text,
        }
        if battery is not None:
            payload["battery"] = int(battery)
        if ip:
            payload["ip"] = ip
        if firmware_version:
            payload["firmware_version"] = firmware_version
        status, data = self._request_with_reauth("POST", url, payload=payload)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"心跳近似上报失败: status={status}, resp={data}")
        return data

    def get_current_task(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        :brief 获取当前任务（近似）
        :desc 映射到 GET /api/workout/status，支持可选 task_id 查询。
        """
        url = self._build_url_with_query("task_current", {"task_id": task_id})
        status, data = self._request_with_reauth("GET", url, payload=None)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"获取当前任务失败: status={status}, resp={data}")
        return data

    def start_task(
        self,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        target_count: int = 30,
        duration_limit: int = 60,
    ) -> Dict[str, Any]:
        """
        :brief 开始任务（近似）
        :desc 映射到 POST /api/workout/start。
        """
        url = self._build_url("task_start")
        payload = {
            "device_id": self.device["device_id"],
            "user_id": user_id or self.device["device_id"],
            "task_id": task_id,
            "target_count": int(target_count),
            "duration_limit": int(duration_limit),
        }
        status, data = self._request_with_reauth("POST", url, payload=payload)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"开始任务失败: status={status}, resp={data}")
        return data

    def get_task_history(self, limit: int = 20) -> Dict[str, Any]:
        """
        :brief 获取任务历史（近似）
        :desc 映射到 GET /api/workout/records。
        """
        url = self._build_url_with_query("task_history", {"limit": int(limit)})
        status, data = self._request_with_reauth("GET", url, payload=None)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"获取任务历史失败: status={status}, resp={data}")
        return data

    def complete_task(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        :brief 完成任务（近似）
        :desc 映射到 POST /api/workout/stop，用于任务结束近似闭环。
        """
        url = self._build_url("task_complete")
        payload = {"task_id": task_id} if task_id else {}
        status, data = self._request_with_reauth("POST", url, payload=payload)
        if status != 200 or int(data.get("code", status)) != 200:
            raise BackendAdapterError(f"结束任务失败: status={status}, resp={data}")
        return data

