'''
:brief 监控 WebSocket 所需的最小配置读取
:desc 仅解析 backend.ws_camera_base_url 与 device.device_id，不依赖 exercise_engine_pkg，不校验 MQTT 等环境变量。
     支持 PUPPY_BACKEND_CONFIG 与自工作区向上查找 backend_config.json。

:author slt
:date 2026/04/02
:version 1.0.0
:history
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple


class MonitorConfigError(RuntimeError):
    '''
    :brief 监控配置缺失或非法时抛出
    '''


def find_backend_config_file(preferred: str) -> Path:
    '''
    :brief 解析 backend_config.json 路径
    :desc 非空 preferred 为显式路径；否则读 PUPPY_BACKEND_CONFIG 或自 cwd/源码上级查找。
    :param preferred: 非空则视为路径；空则按环境变量与工作目录向上查找
    :return 存在的配置文件 Path
    '''
    env_override = os.getenv("PUPPY_BACKEND_CONFIG", "").strip()
    if env_override:
        p = Path(env_override).expanduser().resolve()
        if p.is_file():
            return p
        raise MonitorConfigError(f"PUPPY_BACKEND_CONFIG 指向的文件不存在: {p}")

    if preferred.strip():
        p = Path(preferred.strip()).expanduser().resolve()
        if p.is_file():
            return p
        raise MonitorConfigError(f"配置文件不存在: {p}")

    cwd_candidates = [
        Path.cwd() / "puppyfit_v2_ws/config/backend_config.json",
        Path.cwd() / "puppyfit_ws/config/backend_config.json",
        Path.cwd() / "config/backend_config.json",
    ]
    for c in cwd_candidates:
        if c.is_file():
            return c.resolve()

    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in (
            "puppyfit_v2_ws/config/backend_config.json",
            "config/backend_config.json",
        ):
            cand = parent / rel
            if cand.is_file():
                return cand.resolve()

    raise MonitorConfigError(
        "未找到 backend_config.json，请设置 launch 参数 backend_config_path 或环境变量 PUPPY_BACKEND_CONFIG"
    )


def load_ws_camera_and_device_id(config_path: str) -> Tuple[str, str]:
    '''
    :brief 读取 WebSocket 基址与设备 ID
    :desc 自 JSON 的 backend 与 device 节取值；缺字段或解析失败抛 MonitorConfigError。
    :param config_path: 配置文件路径或空串触发自动查找
    :return (ws_camera_base_url, device_id) 元组
    '''
    path = find_backend_config_file(config_path)
    try:
        raw = path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw)
        base = str(data.get("backend", {}).get("ws_camera_base_url", "")).strip()
        did = str(data.get("device", {}).get("device_id", "")).strip()
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise MonitorConfigError(f"读取或解析配置失败 {path}: {exc}") from exc
    if not base:
        raise MonitorConfigError(f"配置缺少 backend.ws_camera_base_url: {path}")
    if not did:
        raise MonitorConfigError(f"配置缺少 device.device_id: {path}")
    return base, did
