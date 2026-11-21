#!/usr/bin/env python3
'''
:brief 推理时延记录节点
:desc 订阅 pose_inference_ms（Float32），将每帧推理耗时写入 CSV 供论文分析。
      可计算 min / max / avg / P50 / P95 / P99 等统计数据。

:author perf_monitor_pkg
:date 2026/06/05
:version 1.0.0
:history
    1.0.0 - 2026/06/05
        :brief 初始版本
        :desc 订阅 pose_inference_ms（Float32），逐帧写入 inference_raw_*.csv，
              退出时计算 min/max/avg/P50/P95/P99/std 写入 inference_summary_*.csv；
              配合 pose_detector_node 1.0.2 的 monotonic 计时，用于论文单帧推理
              时延分析。ExternalShutdownException 安全处理。run_002 编译验证通过。
'''

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


class InferenceRecorderNode(Node):
    """
    :brief 订阅推理时延话题，将每帧数据写入 CSV
    :desc 参数 duration_sec 控制总时长（0=无限），output_dir 控制输出目录。
          写入两种文件:
            - inference_raw_*.csv: 每帧一行，含时间戳和推理时延
            - inference_summary_*.csv: 结束时计算的统计摘要（min/max/avg/P50/P95/P99）
    """

    def __init__(self) -> None:
        super().__init__('inference_recorder')

        # ---- 参数 ----
        self.declare_parameter('inference_topic', 'pose_inference_ms')
        self.declare_parameter('duration_sec', 0.0)
        self.declare_parameter('output_dir', os.path.expanduser('~/perf_logs'))

        self._inference_topic: str = str(
            self.get_parameter('inference_topic').value
        )
        self._duration: float = float(
            self.get_parameter('duration_sec').value
        )
        self._output_dir: str = str(
            self.get_parameter('output_dir').value
        )
        if not self._output_dir or self._output_dir.strip() == '':
            self._output_dir = os.path.expanduser('~/perf_logs')

        _ensure_dir(self._output_dir)
        timestamp_tag = datetime.now().strftime('%Y%m%d_%H%M%S')

        # ---- 原始数据 CSV ----
        self._raw_path = os.path.join(
            self._output_dir, f'inference_raw_{timestamp_tag}.csv'
        )
        self._raw_file = open(self._raw_path, 'w', newline='', encoding='utf-8')
        self._raw_writer = csv.writer(self._raw_file)
        self._raw_writer.writerow([
            'timestamp_iso', 'frame_index', 'inference_ms',
        ])
        self._raw_file.flush()

        # ---- 统计 ----
        self._frame_idx = 0
        self._values: list[float] = []
        self._start_time = time.monotonic()
        self._shutdown_flag = False

        # ---- 订阅 ----
        self._sub = self.create_subscription(
            Float32,
            self._inference_topic,
            self._inference_cb,
            10,
        )

        self.get_logger().info(
            f'InferenceRecorderNode 启动: topic={self._inference_topic}, '
            f'duration={self._duration}s (0=无限), '
            f'output={self._raw_path}'
        )

    def _inference_cb(self, msg: Float32) -> None:
        if self._shutdown_flag:
            return

        self._frame_idx += 1
        inference_ms = msg.data
        self._values.append(inference_ms)

        self._raw_writer.writerow([
            _iso_now(),
            str(self._frame_idx),
            f'{inference_ms:.3f}',
        ])

        # 每 100 帧刷盘
        if self._frame_idx % 100 == 0:
            self._raw_file.flush()

        # 检查时长
        if self._duration > 0:
            elapsed = time.monotonic() - self._start_time
            if elapsed >= self._duration:
                self.get_logger().info(
                    f'采样时长 {self._duration}s 已到，停止。'
                )
                self._shutdown()

    def _write_summary(self) -> None:
        """计算并写入统计摘要 CSV。"""
        if not self._values:
            return

        sorted_vals = sorted(self._values)
        n = len(sorted_vals)

        def _pctile(p: float) -> float:
            """百分位数（线性插值）。"""
            k = (p / 100.0) * (n - 1)
            f = int(k)
            c = k - f
            if f + 1 < n:
                return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
            return sorted_vals[f]

        avg = sum(sorted_vals) / n
        summary = {
            'frame_count': n,
            'min_ms': sorted_vals[0],
            'max_ms': sorted_vals[-1],
            'avg_ms': avg,
            'p50_ms': _pctile(50),
            'p95_ms': _pctile(95),
            'p99_ms': _pctile(99),
            'std_ms': (sum((v - avg) ** 2 for v in sorted_vals) / n) ** 0.5,
        }

        timestamp_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
        summary_path = os.path.join(
            self._output_dir, f'inference_summary_{timestamp_tag}.csv'
        )
        with open(summary_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['metric', 'value'])
            for key, val in summary.items():
                writer.writerow([key, f'{val:.3f}'])

        self.get_logger().info(
            f'统计摘要: n={n}, avg={avg:.2f}ms, '
            f'min={summary["min_ms"]:.2f}ms, max={summary["max_ms"]:.2f}ms, '
            f'p50={summary["p50_ms"]:.2f}ms, '
            f'p95={summary["p95_ms"]:.2f}ms, p99={summary["p99_ms"]:.2f}ms'
        )
        self.get_logger().info(f'摘要已保存: {summary_path}')

    def _shutdown(self) -> None:
        if self._shutdown_flag:
            return
        self._shutdown_flag = True
        self._write_summary()
        try:
            self._raw_file.flush()
            self._raw_file.close()
        except Exception:
            pass
        self.get_logger().info(
            f'原始数据已保存: {self._raw_path} '
            f'(共 {self._frame_idx} 帧)'
        )

    def destroy_node(self) -> None:
        self._shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = InferenceRecorderNode()
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
