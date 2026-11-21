#!/usr/bin/env python3
# encoding: utf-8
"""将 puppypi_control 目录加入 sys.path（优先 puppypi_vendor，可环境变量覆盖）。"""
import os
import sys


def resolve_puppypi_control_root() -> str:
    override = os.environ.get('PUPPYPI_CONTROL_PATH')
    if override:
        return os.path.abspath(override)
    try:
        from ament_index_python.packages import get_package_share_directory

        return os.path.join(
            get_package_share_directory('puppypi_vendor'), 'puppypi_control'
        )
    except Exception:
        return '/home/ubuntu/software/puppypi_control'


def ensure_puppypi_path() -> str:
    root = resolve_puppypi_control_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    return root
