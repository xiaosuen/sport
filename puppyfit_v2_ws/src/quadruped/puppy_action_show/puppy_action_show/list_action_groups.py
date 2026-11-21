#!/usr/bin/env python3
'''
:brief 列出已安装动作组文件
:desc 扫描 puppypi_vendor 安装目录下 ActionGroups 中的 .d6a / .d6ac（无需 ROS 节点运行）。
      用法: ros2 run puppy_action_show list_action_groups

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块注释
'''

import sys
from pathlib import Path


def main() -> None:
    try:
        from ament_index_python.packages import get_package_share_directory
    except ImportError:
        print("需要 ament_index_python", file=sys.stderr)
        sys.exit(1)
    try:
        base = Path(get_package_share_directory("puppypi_vendor")) / "puppypi_control" / "ActionGroups"
    except Exception as e:
        print(f"找不到 puppypi_vendor: {e}", file=sys.stderr)
        sys.exit(1)
    if not base.is_dir():
        print(f"目录不存在: {base}", file=sys.stderr)
        sys.exit(1)
    for pat in ("*.d6a", "*.d6ac"):
        for p in sorted(base.glob(pat)):
            print(p.name)


if __name__ == "__main__":
    main()
