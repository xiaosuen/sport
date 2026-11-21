#!/usr/bin/env python3
'''
:brief ROS2 主题统计脚本（实验后离线运行）
:desc 对指定的话题列表依次调用 ros2 topic hz / ros2 topic bw，
      解析输出，汇总为 CSV 供论文使用。

      用法:
        python3 perf_report.py \\
            --topics "/cmd_vel_nav,/pose_image,/situp_count,/auto_position/status" \\
            --hz-window 10 \\
            --output ~/perf_data/topic_stats.csv

      也可搭配 ros2 topic list 自动发现所有话题:
        python3 perf_report.py --all-topics --hz-window 10 --output stats.csv

:author perf_monitor_pkg
:date 2026/06/04
:version 1.0.0
'''

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple


def _run_ros2_topic_hz(topic: str, window: int = 10, timeout: float = 15.0) -> Optional[float]:
    """
    运行 ros2 topic hz <topic> --window <window> 并解析平均频率。

    :return: 平均频率（Hz），失败则返回 None
    """
    cmd = ['ros2', 'topic', 'hz', topic, '--window', str(window)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # ros2 topic hz 输出到 stderr（ROS2 Humble 行为）
        output = proc.stderr + proc.stdout
        # 匹配 "average rate: 25.341"
        match = re.search(r'average rate:\s*([\d.]+)', output)
        if match:
            return float(match.group(1))
        # 匹配不到可能是话题无数据
        if 'no messages received' in output.lower() or 'no publishers' in output.lower():
            return 0.0
        return None
    except subprocess.TimeoutExpired:
        print(f'  [WARN] ros2 topic hz {topic} 超时 ({timeout}s)')
        return None
    except FileNotFoundError:
        print('  [ERROR] ros2 命令不可用，请先 source ROS2 环境')
        return None


def _run_ros2_topic_bw(topic: str, window: int = 10, timeout: float = 15.0) -> Optional[float]:
    """
    运行 ros2 topic bw <topic> --window <window> 并解析平均带宽。

    :return: 平均带宽（B/s），失败则返回 None
    """
    cmd = ['ros2', 'topic', 'bw', topic, '--window', str(window)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stderr + proc.stdout
        # 匹配 "average bandwidth: 1.234 MB/s" 或 "1234 B/s" 或 "1.2 KB/s"
        match = re.search(
            r'average bandwidth:\s*([\d.]+)\s*(MB/s|KB/s|B/s|GB/s)',
            output,
        )
        if match:
            value = float(match.group(1))
            unit = match.group(2)
            # 统一转换为 B/s
            multipliers = {'B/s': 1.0, 'KB/s': 1024.0, 'MB/s': 1024.0 ** 2, 'GB/s': 1024.0 ** 3}
            return value * multipliers.get(unit, 1.0)
        return None
    except subprocess.TimeoutExpired:
        print(f'  [WARN] ros2 topic bw {topic} 超时 ({timeout}s)')
        return None
    except FileNotFoundError:
        return None


def _run_ros2_topic_info(topic: str, timeout: float = 5.0) -> Tuple[Optional[str], int, int]:
    """
    运行 ros2 topic info <topic> 获取类型和发布/订阅数。

    :return: (type_name, publisher_count, subscriber_count)
    """
    cmd = ['ros2', 'topic', 'info', topic]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stdout + proc.stderr

        # 匹配 Type: std_msgs/msg/String
        type_match = re.search(r'Type:\s*(\S+)', output)
        type_name = type_match.group(1) if type_match else 'unknown'

        # 匹配 Publisher count: 1
        pub_match = re.search(r'Publisher count:\s*(\d+)', output)
        pub_count = int(pub_match.group(1)) if pub_match else 0

        # 匹配 Subscription count: 3
        sub_match = re.search(r'Subscription count:\s*(\d+)', output)
        sub_count = int(sub_match.group(1)) if sub_match else 0

        return type_name, pub_count, sub_count
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, 0, 0


def _get_all_topics(timeout: float = 5.0) -> List[str]:
    """获取所有 ROS2 话题列表。"""
    try:
        proc = subprocess.run(
            ['ros2', 'topic', 'list'],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return [t.strip() for t in proc.stdout.splitlines() if t.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='ROS2 主题统计 — 采集话题频率与带宽，输出 CSV',
    )
    parser.add_argument(
        '--topics',
        type=str,
        default='',
        help='逗号分隔的话题列表，例如 "/topic1,/topic2"',
    )
    parser.add_argument(
        '--all-topics',
        action='store_true',
        help='自动发现所有话题（忽略 --topics）',
    )
    parser.add_argument(
        '--hz-window',
        type=int,
        default=10,
        help='ros2 topic hz/bw 采样窗口大小（默认 10）',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=15.0,
        help='每个 topic hz/bw 调用超时（秒，默认 15）',
    )
    parser.add_argument(
        '--output',
        type=str,
        default='topic_stats.csv',
        help='输出 CSV 路径（默认 topic_stats.csv）',
    )
    args = parser.parse_args()

    # 确定话题列表
    if args.all_topics:
        print('正在获取所有话题...')
        topics = _get_all_topics()
        if not topics:
            print('[ERROR] 获取话题列表失败，请确认 ROS2 环境已 source 且有节点在运行')
            sys.exit(1)
        print(f'共发现 {len(topics)} 个话题')
    elif args.topics:
        topics = [t.strip() for t in args.topics.split(',') if t.strip()]
    else:
        print('[ERROR] 请指定 --topics 或 --all-topics')
        sys.exit(1)

    # 写入 CSV
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'topic', 'type', 'avg_hz', 'avg_bw_bytes_per_sec',
            'avg_bw_kbps', 'publisher_count', 'subscriber_count',
        ])

        for i, topic in enumerate(topics):
            print(f'[{i + 1}/{len(topics)}] 正在分析: {topic}')

            # 获取话题类型和发布/订阅数
            type_name, pub_count, sub_count = _run_ros2_topic_info(topic, timeout=args.timeout)
            if type_name is None:
                type_name = 'unknown'

            # 获取频率
            avg_hz = _run_ros2_topic_hz(topic, window=args.hz_window, timeout=args.timeout)
            if avg_hz is not None and avg_hz > 0:
                print(f'  频率: {avg_hz:.2f} Hz')
            elif avg_hz == 0.0:
                print(f'  频率: 无数据（无发布者或无消息）')
                avg_hz = 0.0
            else:
                print(f'  频率: 获取失败')
                avg_hz = -1.0

            # 获取带宽
            avg_bw = _run_ros2_topic_bw(topic, window=args.hz_window, timeout=args.timeout)
            if avg_bw is not None:
                bw_kbps = avg_bw / 1024.0
                print(f'  带宽: {bw_kbps:.2f} KB/s ({avg_bw:.1f} B/s)')
            else:
                avg_bw = -1.0
                bw_kbps = -1.0
                print(f'  带宽: 获取失败')

            writer.writerow([
                topic,
                type_name,
                f'{avg_hz:.2f}' if avg_hz >= 0 else 'N/A',
                f'{avg_bw:.1f}' if avg_bw >= 0 else 'N/A',
                f'{bw_kbps:.2f}' if bw_kbps >= 0 else 'N/A',
                str(pub_count),
                str(sub_count),
            ])

    print(f'\n统计结果已保存到: {args.output}')


if __name__ == '__main__':
    main()
