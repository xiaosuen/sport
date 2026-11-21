#!/usr/bin/env python3
'''
:brief 找位计时节点
:desc 订阅 auto_position/status（std_msgs/String），记录状态转换时间戳，
      计算各阶段耗时（searching、centering、approaching、stabilizing），
      输出到 CSV 供论文分析。

      每次 idle→searching 视为一次新的找位尝试；
      searching→ready 视为成功，searching→failed 视为失败。
      中途丢目标回到 searching 视为同一次尝试内的重搜，记录但不覆写首次 searching 开始时间。

:author perf_monitor_pkg
:date 2026/06/04
:version 1.0.1
:history
    1.0.0 - 2026/06/04
        :brief 初始版本
        :desc 订阅 auto_position/status，状态机跟踪 searching→centering→
              approaching→stabilizing→ready/failed，输出 transition 原始 CSV
              与 summary 阶段耗时 CSV，支持多次找位尝试中断重搜。
    1.0.1 - 2026/06/05
        :brief _shutdown 幂等、ExternalShutdownException 处理、编译验证
        :desc _shutdown 加 _shutdown_flag 防正常完成后再写重复 summary 行；
              timeout 杀死进程时捕获 ExternalShutdownException 避免崩溃；
              run_001 实测成功捕获 1 次完整找位（searching 4.4s + centering
              21.1s + stabilizing 0.9s → ready，总耗时 25.5s）。
'''

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def _iso_now() -> str:
    """返回 ISO 8601 带微秒的当前 UTC 时间字符串。"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')


def _ts_ns() -> int:
    """返回当前时间的纳秒整数，用于精确排序。"""
    return int(datetime.now(timezone.utc).timestamp() * 1e9)


def _ensure_dir(path: str) -> None:
    """确保目录存在。"""
    os.makedirs(path, exist_ok=True)


class PositionTimerNode(Node):
    """
    :brief 监听 auto_position 状态字，记录找位各阶段耗时

    状态机（来自 auto_position_node.py）:
        idle → searching → centering → approaching → stabilizing → ready
                                                              ↘ failed
    发布格式: state[|extra]，例如 "searching"、"centering"、"ready"、"failed|timeout"、
             "stabilizing|5/15"、"stabilizing|wait_ready_pose"。
    """

    # 状态常量（与 auto_position_node 一致）
    ST_IDLE = 'idle'
    ST_SEARCHING = 'searching'
    ST_CENTERING = 'centering'
    ST_APPROACHING = 'approaching'
    ST_STABILIZING = 'stabilizing'
    ST_READY = 'ready'
    ST_FAILED = 'failed'

    # 终态集合
    _TERMINAL_STATES = {ST_READY, ST_FAILED}

    def __init__(self) -> None:
        super().__init__('position_timer')

        # ---- 参数 ----
        self.declare_parameter('status_topic', 'auto_position/status')
        self.declare_parameter('output_dir', os.path.expanduser('~/perf_logs'))

        self._status_topic: str = str(
            self.get_parameter('status_topic').value
        )
        self._output_dir: str = str(
            self.get_parameter('output_dir').value
        )
        if not self._output_dir or self._output_dir.strip() == '':
            self._output_dir = os.path.expanduser('~/perf_logs')

        _ensure_dir(self._output_dir)
        timestamp_tag = datetime.now().strftime('%Y%m%d_%H%M%S')

        # ---- CSV 文件 ----
        # 文件 1: 每次状态转换的原始记录
        self._trans_path = os.path.join(
            self._output_dir, f'position_transitions_{timestamp_tag}.csv'
        )
        self._trans_file = open(self._trans_path, 'w', newline='', encoding='utf-8')
        self._trans_writer = csv.writer(self._trans_file)
        self._trans_writer.writerow([
            'timestamp_ns', 'timestamp_iso', 'state', 'extra',
        ])
        self._trans_file.flush()

        # 文件 2: 每次找位尝试的阶段耗时汇总
        self._summary_path = os.path.join(
            self._output_dir, f'position_summary_{timestamp_tag}.csv'
        )
        self._summary_file = open(self._summary_path, 'w', newline='', encoding='utf-8')
        self._summary_writer = csv.writer(self._summary_file)
        self._summary_writer.writerow([
            'attempt',
            'search_start_iso',
            'search_end_iso',
            'centering_start_iso',
            'centering_end_iso',
            'approaching_start_iso',
            'approaching_end_iso',
            'stabilizing_start_iso',
            'stabilizing_end_iso',
            'ready_iso',
            'failed_iso',
            'total_positioning_time_sec',
            'searching_time_sec',
            'centering_time_sec',
            'approaching_time_sec',
            'stabilizing_time_sec',
            'outcome',
        ])
        self._summary_file.flush()

        # ---- 状态跟踪 ----
        self._shutdown_flag = False
        self._attempt_idx = 0
        self._prev_state: Optional[str] = None
        self._current_attempt: dict = {}
        self._init_attempt()

        # ---- 订阅 ----
        self._sub = self.create_subscription(
            String,
            self._status_topic,
            self._status_cb,
            10,
        )

        self.get_logger().info(
            f'PositionTimerNode 启动: 监听 topic={self._status_topic}, '
            f'output_dir={self._output_dir}'
        )

    def _init_attempt(self) -> None:
        """初始化/重置当前找位尝试的计时数据。"""
        self._current_attempt = {
            'search_start_iso': None,
            'search_end_iso': None,
            'centering_start_iso': None,
            'centering_end_iso': None,
            'approaching_start_iso': None,
            'approaching_end_iso': None,
            'stabilizing_start_iso': None,
            'stabilizing_end_iso': None,
            'ready_iso': None,
            'failed_iso': None,
            'search_start_ns': None,
            'phase_search_end_ns': None,
            'phase_centering_end_ns': None,
            'phase_approaching_end_ns': None,
            'phase_stabilizing_end_ns': None,
        }

    # ---- 回调 ----

    def _status_cb(self, msg: String) -> None:
        """接收状态消息，记录转换并更新阶段计时。"""
        now_iso = _iso_now()
        now_ns = _ts_ns()

        # 解析 state[|extra]
        raw = msg.data.strip()
        parts = raw.split('|', 1)
        state = parts[0].strip()
        extra = parts[1].strip() if len(parts) > 1 else ''

        # ---- 写入转换记录 ----
        self._trans_writer.writerow([str(now_ns), now_iso, state, extra])
        self._trans_file.flush()  # 状态转换较少，每次刷盘

        # ---- 检测新的找位尝试 ----
        # 条件: 从 idle 进入 searching（或首次收到消息就是 searching）
        is_new_attempt = False
        if state == self.ST_SEARCHING:
            if self._prev_state == self.ST_IDLE or self._prev_state is None:
                is_new_attempt = True
            elif self._prev_state in self._TERMINAL_STATES and self._prev_state is not None:
                is_new_attempt = True

        if is_new_attempt:
            # 如果前一次尝试有数据且未完成，先写一个部分汇总
            if self._current_attempt['search_start_iso'] is not None:
                self._maybe_write_partial_summary('interrupted')
            self._attempt_idx += 1
            self._init_attempt()

        # ---- 记录各阶段开始/结束时间 ----
        if state == self.ST_SEARCHING and self._current_attempt['search_start_iso'] is None:
            self._current_attempt['search_start_iso'] = now_iso
            self._current_attempt['search_start_ns'] = now_ns
            self.get_logger().info(
                f'[Attempt #{self._attempt_idx}] SEARCHING 开始 @ {now_iso}'
            )

        elif state == self.ST_CENTERING:
            if self._current_attempt['search_end_iso'] is None:
                self._current_attempt['search_end_iso'] = now_iso
                self._current_attempt['phase_search_end_ns'] = now_ns
            if self._current_attempt['centering_start_iso'] is None:
                self._current_attempt['centering_start_iso'] = now_iso

        elif state == self.ST_APPROACHING:
            if self._current_attempt['centering_end_iso'] is None:
                self._current_attempt['centering_end_iso'] = now_iso
                self._current_attempt['phase_centering_end_ns'] = now_ns
            if self._current_attempt['approaching_start_iso'] is None:
                self._current_attempt['approaching_start_iso'] = now_iso

        elif state == self.ST_STABILIZING:
            if self._current_attempt['approaching_end_iso'] is None:
                self._current_attempt['approaching_end_iso'] = now_iso
                self._current_attempt['phase_approaching_end_ns'] = now_ns
            if self._current_attempt['stabilizing_start_iso'] is None:
                self._current_attempt['stabilizing_start_iso'] = now_iso

        elif state == self.ST_READY:
            self._current_attempt['stabilizing_end_iso'] = now_iso
            self._current_attempt['phase_stabilizing_end_ns'] = now_ns
            self._current_attempt['ready_iso'] = now_iso
            self._write_summary_row(now_ns, 'ready')
            self.get_logger().info(
                f'[Attempt #{self._attempt_idx}] READY — 找位成功'
            )

        elif state == self.ST_FAILED:
            if extra.lower().startswith('timeout'):
                self._current_attempt['stabilizing_end_iso'] = now_iso
                self._current_attempt['phase_stabilizing_end_ns'] = now_ns
            self._current_attempt['failed_iso'] = now_iso
            self._write_summary_row(now_ns, f'failed|{extra}')
            self.get_logger().warn(
                f'[Attempt #{self._attempt_idx}] FAILED — {extra}'
            )

        self._prev_state = state

    # ---- 汇总写入 ----

    def _compute_phase_times(self, end_ns: int) -> dict:
        """根据已记录的时间戳计算各阶段耗时（秒）。"""
        a = self._current_attempt
        result = {
            'searching_time_sec': 0.0,
            'centering_time_sec': 0.0,
            'approaching_time_sec': 0.0,
            'stabilizing_time_sec': 0.0,
            'total_positioning_time_sec': 0.0,
        }

        search_start = a.get('search_start_ns')
        if search_start is None:
            return result

        # 各阶段结束时间戳; 未到达的阶段用 end_ns
        s_end = a.get('phase_search_end_ns') or end_ns
        c_end = a.get('phase_centering_end_ns') or end_ns
        a_end = a.get('phase_approaching_end_ns') or end_ns
        st_end = a.get('phase_stabilizing_end_ns') or end_ns

        result['searching_time_sec'] = max(0.0, (s_end - search_start) / 1e9)
        result['centering_time_sec'] = max(0.0, (c_end - s_end) / 1e9) if a.get('phase_search_end_ns') else 0.0
        result['approaching_time_sec'] = max(0.0, (a_end - c_end) / 1e9) if a.get('phase_centering_end_ns') else 0.0
        result['stabilizing_time_sec'] = max(0.0, (st_end - a_end) / 1e9) if a.get('phase_approaching_end_ns') else 0.0
        result['total_positioning_time_sec'] = max(0.0, (end_ns - search_start) / 1e9)

        return result

    def _write_summary_row(self, end_ns: int, outcome: str) -> None:
        """写入一次完整的找位尝试汇总行。"""
        a = self._current_attempt
        times = self._compute_phase_times(end_ns)

        self._summary_writer.writerow([
            str(self._attempt_idx),
            a['search_start_iso'] or '',
            a['search_end_iso'] or '',
            a['centering_start_iso'] or '',
            a['centering_end_iso'] or '',
            a['approaching_start_iso'] or '',
            a['approaching_end_iso'] or '',
            a['stabilizing_start_iso'] or '',
            a['stabilizing_end_iso'] or '',
            a['ready_iso'] or '',
            a['failed_iso'] or '',
            f'{times["total_positioning_time_sec"]:.3f}',
            f'{times["searching_time_sec"]:.3f}',
            f'{times["centering_time_sec"]:.3f}',
            f'{times["approaching_time_sec"]:.3f}',
            f'{times["stabilizing_time_sec"]:.3f}',
            outcome,
        ])
        self._summary_file.flush()

    def _maybe_write_partial_summary(self, outcome: str) -> None:
        """为未完成的尝试写入部分汇总（如中途 Ctrl+C 或重搜）。"""
        a = self._current_attempt
        if a['search_start_iso'] is None:
            return
        end_ns = a.get('phase_stabilizing_end_ns') or _ts_ns()
        self._write_summary_row(end_ns, outcome)

    # ---- 关闭 ----

    def _shutdown(self) -> None:
        """安全关闭（幂等），如有未完成的尝试则写入部分记录。"""
        if getattr(self, '_shutdown_flag', False):
            return
        self._shutdown_flag = True
        self._maybe_write_partial_summary('shutdown')
        try:
            self._trans_file.flush()
            self._trans_file.close()
        except Exception:
            pass
        try:
            self._summary_file.flush()
            self._summary_file.close()
        except Exception:
            pass
        self.get_logger().info(
            f'文件已保存:\n'
            f'  转换记录: {self._trans_path}\n'
            f'  汇总:     {self._summary_path}'
        )

    def destroy_node(self) -> None:
        self._shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PositionTimerNode()
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
