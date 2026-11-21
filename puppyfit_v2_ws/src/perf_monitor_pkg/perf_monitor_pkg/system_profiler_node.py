#!/usr/bin/env python3
'''
:brief 系统性能采样节点
:desc 按固定周期采集 ROS2 各节点的 CPU 占用率与内存（RSS/VSZ），以及系统整体 CPU/内存，
      写入 CSV 文件供论文性能分析使用。
      通过 ros2 node info 获取节点→PID 映射，后台线程定期刷新。

:author perf_monitor_pkg
:date 2026/06/04
:version 1.0.2
:history
    1.0.0 - 2026/06/04
        :brief 初始版本
        :desc 基于 psutil 定时采样各 ROS2 节点 CPU/RSS/VSZ 与系统整体 CPU/内存，
              写入 CSV；通过 ros2 node info 获取节点→PID 映射。
    1.0.1 - 2026/06/05
        :brief CLI 定位 ros2 可执行文件，新增 /proc 扫描 fallback
        :desc shutil.which('ros2') 优先，再尝试常见路径；均失败时扫描
              /proc/[pid]/cmdline 匹配 __node:= 提取节点名，保证子进程
              PATH 未继承时仍可发现节点。
    1.0.2 - 2026/06/05
        :brief ExternalShutdownException 处理、_shutdown 幂等、编译验证
        :desc timeout 杀死进程时捕获 ExternalShutdownException 避免崩溃；
              _shutdown 加 _shutdown_flag 防重复写 CSV；colcon 编译后
              run_002 实测 14 节点 × 28 次采样，分节点 RSS 数据正确。
'''

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import psutil
import rclpy
from rclpy.node import Node


def _iso_now() -> str:
    """返回 ISO 8601 带微秒的当前 UTC 时间字符串。"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')


def _ensure_dir(path: str) -> None:
    """确保目录存在。"""
    os.makedirs(path, exist_ok=True)


def _find_ros2_cmd() -> Optional[str]:
    """定位 ros2 可执行文件路径。"""
    # 1. 从当前进程 PATH 找
    ros2 = shutil.which('ros2')
    if ros2:
        return ros2
    # 2. 尝试常见路径
    for candidate in [
        '/opt/ros/humble/bin/ros2',
        '/opt/ros/rolling/bin/ros2',
        '/opt/ros/iron/bin/ros2',
        '/opt/ros/jazzy/bin/ros2',
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _get_node_pids_via_cli() -> Dict[str, int]:
    """
    通过 ros2 CLI 获取 {node_name: pid} 映射。
    优先使用 ros2 node list + ros2 node info。
    """
    ros2 = _find_ros2_cmd()
    if not ros2:
        return {}

    try:
        result = subprocess.run(
            [ros2, 'node', 'list'],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}

    node_names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    mapping: Dict[str, int] = {}

    for name in node_names:
        try:
            info = subprocess.run(
                [ros2, 'node', 'info', name],
                capture_output=True, text=True, timeout=5,
            )
            pid_match = re.search(r'Process ID:\s*(\d+)', info.stdout)
            if pid_match:
                mapping[name] = int(pid_match.group(1))
        except (subprocess.TimeoutExpired, OSError):
            continue

    return mapping


def _get_node_pids_via_proc() -> Dict[str, int]:
    """
    备用方案：扫描 /proc 文件系统，从进程 cmdline 中提取 ROS2 节点名。

    ROS2 节点进程的 cmdline 包含类似:
        --ros-args -r __node:=pose_detector

    返回 {node_name: pid}。
    """
    mapping: Dict[str, int] = {}
    ros2_name_re = re.compile(r'__node:=(\S+)')

    for pid_dir in os.listdir('/proc'):
        if not pid_dir.isdigit():
            continue
        pid = int(pid_dir)
        cmdline_path = f'/proc/{pid}/cmdline'
        try:
            with open(cmdline_path, 'rb') as f:
                raw = f.read()
            # cmdline 用 \0 分隔
            text = raw.decode('utf-8', errors='replace').replace('\x00', ' ')
        except (OSError, PermissionError):
            continue

        match = ros2_name_re.search(text)
        if match:
            node_name = match.group(1)
            # 如果有同名节点（多个节点在同一进程），优先保留先遇到的；
            # 实际上 ROS2 composable nodes 共享 PID，cmdline 可能含多个 __node:=
            # 这里取第一个匹配，后续改进可用 findall
            if node_name not in mapping:
                mapping[node_name] = pid

    return mapping


def _get_node_pids() -> Dict[str, int]:
    """
    获取 {node_name: pid} 映射。
    优先用 ros2 CLI，失败则回退到 /proc 扫描。
    """
    # 优先 CLI（能区分同一进程内的 composable nodes）
    mapping = _get_node_pids_via_cli()
    if mapping:
        return mapping
    # 回退：/proc 扫描
    return _get_node_pids_via_proc()


class SystemProfilerNode(Node):
    """
    :brief 定时采样各 ROS2 节点与系统 CPU/内存，写入 CSV
    :desc 参数 sample_interval_sec 控制采样周期，duration_sec 控制总时长（0 为无限）。
          输出 CSV 每行包含一个节点在一个采样时刻的快照，系统级指标在每行中重复。
    """

    def __init__(self) -> None:
        super().__init__('system_profiler')

        # ---- 参数 ----
        self.declare_parameter('sample_interval_sec', 1.0)
        self.declare_parameter('duration_sec', 0.0)
        self.declare_parameter('output_dir', os.path.expanduser('~/perf_logs'))

        self._sample_interval: float = float(
            self.get_parameter('sample_interval_sec').value
        )
        self._duration: float = float(
            self.get_parameter('duration_sec').value
        )
        self._output_dir: str = str(
            self.get_parameter('output_dir').value
        )
        if not self._output_dir or self._output_dir.strip() == '':
            self._output_dir = os.path.expanduser('~/perf_logs')

        # ---- 输出目录 ----
        _ensure_dir(self._output_dir)
        timestamp_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._csv_path = os.path.join(
            self._output_dir, f'perf_{timestamp_tag}.csv'
        )

        # ---- CSV 文件 ----
        self._csv_file = open(self._csv_path, 'w', newline='', encoding='utf-8')
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow([
            'timestamp_iso',
            'node_name',
            'pid',
            'cpu_percent',
            'rss_mb',
            'vsz_mb',
            'system_cpu_percent',
            'system_mem_percent',
            'system_mem_used_gb',
            'system_mem_total_gb',
        ])
        self._csv_file.flush()

        # ---- 状态 ----
        self._node_pids: Dict[str, int] = {}
        self._pid_lock = threading.Lock()
        self._sample_count = 0
        self._start_time = time.monotonic()
        self._shutdown_flag = False

        # ---- psutil CPU 种子调用（首次返回 0，必须丢弃） ----
        psutil.cpu_percent(interval=None)
        # 也对每个后续会查询的 Process 做一次种子调用，否则第一次 .cpu_percent() 也是 0
        self._last_proc_cache: Dict[int, psutil.Process] = {}

        # ---- 首次获取节点映射 ----
        self._refresh_node_pids()

        # ---- 定时器 ----
        self._timer = self.create_timer(self._sample_interval, self._timer_cb)

        self.get_logger().info(
            f'SystemProfilerNode 启动: sample_interval={self._sample_interval}s, '
            f'duration={self._duration}s (0=无限), '
            f'output={self._csv_path}'
        )

    def _refresh_node_pids(self) -> None:
        """在后台线程中刷新节点→PID 映射，不阻塞定时器。"""
        def _refresh() -> None:
            mapping = _get_node_pids()
            with self._pid_lock:
                self._node_pids = mapping
                # 清除已不存在的进程缓存
                stale = set(self._last_proc_cache.keys()) - set(mapping.values())
                for pid in stale:
                    self._last_proc_cache.pop(pid, None)
            self.get_logger().debug(
                f'节点→PID 映射已刷新: {len(mapping)} 个节点'
            )

        thread = threading.Thread(target=_refresh, daemon=True)
        thread.start()

    # ---- 定时器回调 ----

    def _timer_cb(self) -> None:
        """每次定时器触发：采样并写入一行。"""
        if self._shutdown_flag:
            return

        self._sample_count += 1

        # 检查运行时长
        elapsed = time.monotonic() - self._start_time
        if self._duration > 0 and elapsed >= self._duration:
            self.get_logger().info(
                f'采样时长 {self._duration}s 已到，共 {self._sample_count} 次采样，停止。'
            )
            self._shutdown()
            return

        # 每 10 次采样刷新一次节点→PID 映射
        if self._sample_count % 10 == 0:
            self._refresh_node_pids()

        # ---- 采样系统级指标 ----
        sys_cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        sys_mem_percent = mem.percent
        sys_mem_used_gb = mem.used / (1024 ** 3)
        sys_mem_total_gb = mem.total / (1024 ** 3)

        # ---- 采样每节点指标 ----
        timestamp = _iso_now()

        with self._pid_lock:
            node_pids = dict(self._node_pids)  # 副本

        if not node_pids:
            # 没有 ROS 节点在运行，至少写一行系统汇总
            self._csv_writer.writerow([
                timestamp, '__system__', 0, 0.0, 0.0, 0.0,
                f'{sys_cpu:.2f}', f'{sys_mem_percent:.1f}',
                f'{sys_mem_used_gb:.3f}', f'{sys_mem_total_gb:.3f}',
            ])
            self._csv_file.flush()
            return

        for node_name, pid in sorted(node_pids.items()):
            cpu_pct = 0.0
            rss_mb = 0.0
            vsz_mb = 0.0

            try:
                if pid not in self._last_proc_cache:
                    self._last_proc_cache[pid] = psutil.Process(pid)
                    # 对新建的 Process 对象做一次种子 cpu_percent 调用
                    self._last_proc_cache[pid].cpu_percent(interval=None)

                proc = self._last_proc_cache[pid]
                cpu_pct = proc.cpu_percent(interval=None)
                mem_info = proc.memory_info()
                rss_mb = mem_info.rss / (1024 * 1024)
                vsz_mb = mem_info.vms / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                # 进程已退出，从缓存中移除
                self._last_proc_cache.pop(pid, None)
                continue

            self._csv_writer.writerow([
                timestamp,
                node_name,
                str(pid),
                f'{cpu_pct:.2f}',
                f'{rss_mb:.2f}',
                f'{vsz_mb:.2f}',
                f'{sys_cpu:.2f}',
                f'{sys_mem_percent:.1f}',
                f'{sys_mem_used_gb:.3f}',
                f'{sys_mem_total_gb:.3f}',
            ])

        # 每 10 次采样刷盘
        if self._sample_count % 10 == 0:
            self._csv_file.flush()

    def _shutdown(self) -> None:
        """安全关闭并保存 CSV（幂等）。"""
        if self._shutdown_flag:
            return  # 已经关闭过，不重复执行
        self._shutdown_flag = True
        if self._timer:
            self._timer.cancel()
        try:
            self._csv_file.flush()
            self._csv_file.close()
        except Exception:
            pass
        self.get_logger().info(
            f'CSV 已保存: {self._csv_path} '
            f'(共 {self._sample_count} 次采样)'
        )

    def destroy_node(self) -> None:
        self._shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SystemProfilerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except rclpy.executors.ExternalShutdownException:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
