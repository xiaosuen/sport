#!/usr/bin/env python3
"""
:brief 终端后端配置加载器
:desc 读取 backend JSON 配置，从环境变量注入敏感字段，
      并对关键字段进行严格校验；缺失时抛出明确错误。
:author slt
:date 2026/03/24
:version 1.0.1
:history
    - 1.0.0 2026/03/24
        :desc 初始版本，提供配置加载和环境变量注入校验
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple


class BackendConfigError(RuntimeError):
    """后端配置缺失或不合法时抛出。"""


def _get_by_path(data: Dict[str, Any], dotted_path: str) -> Any:
    cur: Any = data
    for key in dotted_path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            raise BackendConfigError(f"缺少必填配置项: {dotted_path}")
        cur = cur[key]
    return cur


def _set_by_path(data: Dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cur: Dict[str, Any] = data
    for key in parts[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[parts[-1]] = value


def _validate_required_keys(cfg: Dict[str, Any], required_keys: List[str]) -> None:
    for key in required_keys:
        value = _get_by_path(cfg, key)
        if value is None:
            raise BackendConfigError(f"必填配置项不能为空: {key}")
        if isinstance(value, str) and not value.strip():
            raise BackendConfigError(f"必填配置项不能为空字符串: {key}")


def _resolve_env_fields(cfg: Dict[str, Any], env_mapping: List[Tuple[str, str]]) -> None:
    for env_key_path, target_key_path in env_mapping:
        env_name = _get_by_path(cfg, env_key_path)
        if not isinstance(env_name, str) or not env_name.strip():
            raise BackendConfigError(f"环境变量键名无效: {env_key_path}")
        env_value = os.getenv(env_name)
        if env_value is None or not env_value.strip():
            raise BackendConfigError(
                f"缺少环境变量: {env_name}（在 {env_key_path} 中声明）"
            )
        _set_by_path(cfg, target_key_path, env_value)


def find_config_file(preferred_path: str = "puppyfit_ws/config/backend_config.json") -> Path:
    """
    按以下优先级解析配置文件路径：
    1) 环境变量 PUPPY_BACKEND_CONFIG
    2) 当前工作目录下的 preferred_path
    3) 当前工作目录下的 puppyfit_ws/config/backend_config.json（兜底）
    4) 从本文件父目录逐级向上查找上述路径
    """
    env_override = os.getenv("PUPPY_BACKEND_CONFIG", "").strip()
    if env_override:
        path = Path(env_override).expanduser().resolve()
        if path.is_file():
            return path
        raise BackendConfigError(f"配置文件不存在: {path}")

    cwd_candidates = [
        Path.cwd() / preferred_path,
        Path.cwd() / "puppyfit_ws/config/backend_config.json",
        Path.cwd() / "puppyfit_v2_ws/config/backend_config.json",
    ]
    for candidate in cwd_candidates:
        if candidate.is_file():
            return candidate.resolve()

    # 从本文件所在目录向上查找，兼容不同启动目录
    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in (
            preferred_path,
            "puppyfit_ws/config/backend_config.json",
            "puppyfit_v2_ws/config/backend_config.json",
        ):
            candidate = parent / rel
            if candidate.is_file():
                return candidate.resolve()

    raise BackendConfigError(
        "未找到配置文件。已尝试环境变量 PUPPY_BACKEND_CONFIG、"
        f"{preferred_path}、puppyfit_ws/config/backend_config.json、"
        "puppyfit_v2_ws/config/backend_config.json"
    )


def load_backend_config(config_path: str = "puppyfit_ws/config/backend_config.json") -> Dict[str, Any]:
    """
    加载并校验后端配置。

    约定以下字段必须通过环境变量注入：
    - auth.username_env -> auth.username
    - auth.password_env -> auth.password
    - mqtt.username_env -> mqtt.username
    - mqtt.password_env -> mqtt.password
    """
    path = find_config_file(config_path)
    try:
        raw = path.read_text(encoding="utf-8")
        cfg: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendConfigError(f"配置文件 JSON 格式错误 {path}: {exc}") from exc
    except OSError as exc:
        raise BackendConfigError(f"读取配置文件失败 {path}: {exc}") from exc

    required = [
        "device.device_id",
        "backend.http_base_url",
        "backend.ws_camera_base_url",
        "backend.api_paths.login",
        "auth.login_type",
        "auth.username_env",
        "auth.password_env",
        "mqtt.broker_host",
        "mqtt.broker_port",
        "mqtt.use_tls",
        "mqtt.username_env",
        "mqtt.password_env",
        "mqtt.topics.publish_file_notify",
        "mqtt.topics.subscribe_control",
        "mqtt.topics.subscribe_file_status",
    ]
    _validate_required_keys(cfg, required)

    _resolve_env_fields(
        cfg,
        env_mapping=[
            ("auth.username_env", "auth.username"),
            ("auth.password_env", "auth.password"),
            ("mqtt.username_env", "mqtt.username"),
            ("mqtt.password_env", "mqtt.password"),
        ],
    )

    return cfg

