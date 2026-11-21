#!/usr/bin/env python3
'''
:brief 自动找位节点
:desc 订阅 /perception/human_pose（可配置），在 SEARCHING 阶段组合水平旋转与机体俯仰扫描；
      检出人体后对中、调距离，稳定后发布 auto_position/status=ready。运动默认发布到 /cmd_vel_nav，
      因 puppy_control 对 /cmd_vel 仅在 |linear.x|>0.5 或 |angular.z|>0.5 时才驱动步态，不利于比例对中。

:author slt
:date 2026/04/07
:version 1.0.3
:history
    1.0.3 - 2026/04/23
        :brief search_timeout_sec<=0 时不触发 SEARCHING 超时
    1.0.2 - 2026/04/23
        :brief 调距离阶段 min_linear_x_forward/back，避免过低速原地踏步
    1.0.1 - 2026/04/08
        :brief 参数 autostart；_cmd_start 与 control=start 共用
    1.0.0 - 2026/04/07
        :brief 初始版本
'''

from __future__ import annotations

import math
from typing import Optional

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from puppy_control_msgs.msg import Pose as PuppyPoseMsg
from robot_msgs.msg import HumanPose
from std_msgs.msg import String


class AutoPositionNode(Node):
    """
    :brief 基于人体框驱动找位状态机，发布速度、可选俯仰和状态字
    :desc 订 HumanPose，定时器里推状态；Twist 走 twist_topic，Pose 走 pose_topic（可选），String 走 status_topic。
          start/autostart：idle→searching；搜到人→centering；搜超时→failed；丢检久了回 searching|lost_target。
          对中用 bbox 水平位置，远近用 bbox 面积，稳够了→ready；stop/reset 回 idle 并停轮、收俯仰。
    """
    # 状态机终态与过程态字符串（与 status_topic 发布内容一致，编排端常以精确串「ready」判定成功）
    STATE_IDLE = 'idle'               # 未使能；stop/reset 回到此态；不主动发非零速度
    STATE_SEARCHING = 'searching'     # 搜人：角速度旋转 + 可选俯仰档；检出->centering，超时->failed
    STATE_CENTERING = 'centering'     # 已检出：航向对准 bbox 水平中心（angular.z）
    STATE_APPROACHING = 'approaching'  # 已居中：按 bbox 面积用 linear.x 近似调节远近
    STATE_STABILIZING = 'stabilizing'  # 几何条件满足：累计稳定帧，可带 |wait_ready_pose 或进度后缀
    STATE_READY = 'ready'             # 成功终态；停轮、复位姿态、发 status
    STATE_FAILED = 'failed'           # 失败终态（如 |timeout）；停轮、复位姿态、发 status

    def __init__(self) -> None:
        super().__init__('auto_position_node')

        # --- 话题 ---
        self.declare_parameter('human_pose_topic', '/perception/human_pose')  # 人体检测输入话题（detected、bbox_center_x、bbox_area、ready_pose）
        self.declare_parameter('control_topic', 'auto_position/control')  # 控制输入话题（start 启动，stop/reset 停止并回 idle）
        self.declare_parameter('status_topic', 'auto_position/status')  # 状态输出话题（searching、centering、stabilizing、ready、failed|...）
        self.declare_parameter('twist_topic', '/cmd_vel_nav')  # 速度输出话题（搜索转向、对中转向、前后调距）
        self.declare_parameter('pose_topic', '/puppy_control/pose')  # 姿态输出话题（俯仰扫描与回基准姿态）
        self.declare_parameter('use_pose_scan', True)  # 搜索阶段是否启用多档俯仰扫描来扩大视野
        # true：节点启动后立即等同执行 start；联调可用，现场建议由编排显式发 control
        self.declare_parameter('autostart', False)

        # --- 控制周期 ---
        self.declare_parameter('control_rate_hz', 20.0)  # 状态机执行频率（Hz），定时器周期=1/rate

        # --- 搜索阶段（SEARCHING）---
        # search_timeout_sec：<=0 表示不判超时；>0 表示搜索超过该秒数仍未检出则 failed|timeout
        self.declare_parameter('search_timeout_sec', 60.0)
        self.declare_parameter('search_yaw_segment_sec', 2.0)  # 单段同向旋转时长（秒），到时后进入下一段
        self.declare_parameter('yaw_segments_before_pitch_step', 1)  # 累计多少段 yaw 后切到下一档俯仰
        self.declare_parameter('search_angular_z', 0.28)  # 搜索阶段角速度（rad/s）
        self.declare_parameter('pitch_settle_sec', 0.6)  # 切换俯仰后静止等待机身稳定的时间（秒）
        self.declare_parameter('pitch_preset_delta_deg', [12.0, 0.0, -10.0, -20.0])  # 俯仰预设增量列表（相对 baseline_pitch，单位度）
        self.declare_parameter('pose_transition_run_time_ms', 150)  # 姿态过渡时间（毫秒），写入 Pose.run_time

        # --- 机体姿态基准（须落在 puppy_control 合法域）---
        self.declare_parameter('baseline_roll_deg', 0.0)  # 基准横滚角（度），用于回正与俯仰扫描叠加
        self.declare_parameter('baseline_pitch_deg', 0.0)  # 基准俯仰角（度），扫描时在此基础上叠加 delta
        self.declare_parameter('baseline_yaw_deg', 0.0)  # 基准偏航角（度），用于回基准姿态
        self.declare_parameter('baseline_height', -10.0)  # 基准机身高度（与 puppy_control 约定保持一致）
        self.declare_parameter('baseline_x_shift', -0.5)  # 基准重心前后偏移 x_shift
        self.declare_parameter('baseline_stance_x', 0.0)  # 基准站姿 stance_x
        self.declare_parameter('baseline_stance_y', 0.0)  # 基准站姿 stance_y

        # --- 对中 / 远近（检出后）---
        self.declare_parameter('center_tolerance', 0.08)  # 对中容差：|bbox_center_x - 0.5| <= 该值视为居中
        self.declare_parameter('target_area_min', 0.08)  # 目标框面积下限：小于该值判定目标偏远，需要前进
        self.declare_parameter('target_area_max', 0.25)  # 目标框面积上限：大于该值判定目标偏近，需要后退
        self.declare_parameter('center_kp', 2.0)  # 对中角速度比例系数（误差 -> angular.z）
        self.declare_parameter('approach_kp', 0.25)  # 调距线速度比例系数（面积误差 -> linear.x）
        self.declare_parameter('max_angular_z', 0.35)  # 对中阶段角速度绝对值上限（rad/s）
        self.declare_parameter('max_linear_x', 0.12)  # 调距阶段线速度绝对值上限（m/s）
        # 线速度过小真机可能只蹭步不移动；分别约束前进和后退的最小速度（m/s）
        self.declare_parameter('min_linear_x_forward', 0.05)
        self.declare_parameter('min_linear_x_backward', 0.05)
        self.declare_parameter('center_yaw_sign', 1.0)  # 对中方向符号（若转向相反可改为 -1）

        # --- 稳定与丢检 ---
        self.declare_parameter('stable_frames', 15)  # 连续满足“已对中且距离合适”的帧数阈值，达到后置 ready
        self.declare_parameter('require_ready_pose', True)  # 是否额外要求 ready_pose=True 才允许累计稳定帧
        self.declare_parameter('lost_detection_frames', 20)  # 连续丢检帧数阈值；达到后从跟踪态退回 searching

        hp_topic = str(self.get_parameter('human_pose_topic').value).strip() or '/perception/human_pose'
        ctrl_topic = str(self.get_parameter('control_topic').value).strip() or 'auto_position/control'
        status_topic = str(self.get_parameter('status_topic').value).strip() or 'auto_position/status'
        twist_topic = str(self.get_parameter('twist_topic').value).strip() or '/cmd_vel_nav'
        pose_topic = str(self.get_parameter('pose_topic').value).strip() or '/puppy_control/pose'

        up = self.get_parameter('use_pose_scan').value
        self._use_pose_scan = up in (True, 'true', 'True', '1', 1)

        rate = float(self.get_parameter('control_rate_hz').value)
        self._period = 1.0 / rate if rate > 0.0 else 0.05

        pp = self.get_parameter('pitch_preset_delta_deg').value
        if isinstance(pp, (list, tuple)):
            self._pitch_delta_deg = [float(x) for x in pp]
        else:
            self._pitch_delta_deg = [12.0, 0.0, -10.0, -20.0]
        if not self._pitch_delta_deg:
            self._pitch_delta_deg = [0.0]

        self._search_timeout_sec = float(self.get_parameter('search_timeout_sec').value)
        self._search_yaw_segment_sec = float(self.get_parameter('search_yaw_segment_sec').value)
        self._yaw_segments_before_pitch = max(
            1, int(self.get_parameter('yaw_segments_before_pitch_step').value)
        )
        self._search_angular_z = float(self.get_parameter('search_angular_z').value)
        self._pitch_settle_sec = float(self.get_parameter('pitch_settle_sec').value)
        self._pose_run_time_ms = int(self.get_parameter('pose_transition_run_time_ms').value)

        self._baseline_roll = math.radians(float(self.get_parameter('baseline_roll_deg').value))
        self._baseline_pitch = math.radians(float(self.get_parameter('baseline_pitch_deg').value))
        self._baseline_yaw = float(self.get_parameter('baseline_yaw_deg').value)
        self._baseline_height = float(self.get_parameter('baseline_height').value)
        self._baseline_x_shift = float(self.get_parameter('baseline_x_shift').value)
        self._baseline_stance_x = float(self.get_parameter('baseline_stance_x').value)
        self._baseline_stance_y = float(self.get_parameter('baseline_stance_y').value)

        self._center_tol = float(self.get_parameter('center_tolerance').value)
        self._area_min = float(self.get_parameter('target_area_min').value)
        self._area_max = float(self.get_parameter('target_area_max').value)
        self._center_kp = float(self.get_parameter('center_kp').value)
        self._approach_kp = float(self.get_parameter('approach_kp').value)
        self._max_w = float(self.get_parameter('max_angular_z').value)
        self._max_vx = float(self.get_parameter('max_linear_x').value)
        self._min_vx_f = max(0.0, float(self.get_parameter('min_linear_x_forward').value))
        self._min_vx_b = max(0.0, float(self.get_parameter('min_linear_x_backward').value))
        self._center_sign = float(self.get_parameter('center_yaw_sign').value)

        self._stable_need = max(1, int(self.get_parameter('stable_frames').value))
        rq = self.get_parameter('require_ready_pose').value
        self._require_ready = rq in (True, 'true', 'True', '1', 1)
        self._lost_frames_thresh = max(1, int(self.get_parameter('lost_detection_frames').value))

        self.create_subscription(HumanPose, hp_topic, self._on_human_pose, 10)
        self.create_subscription(String, ctrl_topic, self._on_control, 10)

        self._twist_pub = self.create_publisher(Twist, twist_topic, 10)
        self._pose_pub = self.create_publisher(PuppyPoseMsg, pose_topic, 10)
        self._status_pub = self.create_publisher(String, status_topic, 10)

        self._timer = self.create_timer(self._period, self._on_timer)

        self._hp: Optional[HumanPose] = None
        self._state = self.STATE_IDLE
        self._enabled = False
        self._search_t0: Optional[rclpy.time.Time] = None
        self._yaw_segment_t0: Optional[rclpy.time.Time] = None
        self._yaw_segments_done = 0
        self._pitch_idx = 0
        self._pitch_applied_idx: Optional[int] = None
        self._pitch_settle_until: Optional[rclpy.time.Time] = None
        self._stable_count = 0
        self._lost_count = 0
        self._last_status = ''

        ast = self.get_parameter('autostart').value
        if ast in (True, 'true', 'True', '1', 1):
            self.get_logger().info('autostart=true，立即进入找位（等同 auto_position/control=start）')
            self._cmd_start()

        self.get_logger().info(
            f'auto_position_node: pose={pose_topic}, twist={twist_topic}, human_pose={hp_topic}, '
            f'use_pose_scan={self._use_pose_scan}'
        )

    def _publish_status(self, s: str, extra: str = '') -> None:
        """
        :brief 发状态到 status_topic，和上次一样就跳过
        :desc 拼 s+extra，变了才 publish，避免刷屏；extra 如 |timeout。
        :param s: 主状态字
        :param extra: 接在后面的后缀，默认空
        """
        msg = String()
        msg.data = f'{s}{extra}'
        if msg.data != self._last_status:
            self._last_status = msg.data
            self._status_pub.publish(msg)
            self.get_logger().info(f'status -> {msg.data}')

    def _stop_motion(self) -> None:
        """
        :brief 发一条全零 Twist，让底盘别动
        :desc 发到 twist_topic。
        """
        t = Twist()
        self._twist_pub.publish(t)

    def _publish_baseline_pose(self) -> None:
        """
        :brief 俯仰扫开关开着时，把机身俯仰拉回基准档
        :desc 等价于 delta=0 的 _publish_pose_at_pitch_delta；关着就不发。
        """
        if not self._use_pose_scan:
            return
        self._publish_pose_at_pitch_delta(0.0)

    def _publish_pose_at_pitch_delta(self, delta_deg: float) -> None:
        """
        :brief 按指定俯仰增量发布一条机身姿态指令
        :desc 在基准姿态的基础上，只调整 pitch；其余姿态参数保持 baseline_* 配置值。
              本函数只负责把目标姿态发出去，不负责等待机身稳定。
        :param delta_deg: 相对 baseline_pitch 额外增加的俯仰角，单位为度
        """
        m = PuppyPoseMsg()
        m.roll = float(self._baseline_roll)
        m.pitch = float(self._baseline_pitch + math.radians(delta_deg))
        m.yaw = float(self._baseline_yaw)
        m.height = float(self._baseline_height)
        m.x_shift = float(self._baseline_x_shift)
        m.stance_x = float(self._baseline_stance_x)
        m.stance_y = float(self._baseline_stance_y)
        m.run_time = int(self._pose_run_time_ms)
        self._pose_pub.publish(m)

    def _apply_pitch_preset_index(self, idx: int) -> None:
        """
        :brief 切换到指定的俯仰预设档位，并进入短暂稳定等待
        :desc 先根据 idx 从俯仰预设列表中选出一个档位；如果 idx 超出列表范围，就按列表长度循环取值。
              姿态发布后，会记录一个等待截止时间；在接下来的 pitch_settle_sec 秒内，SEARCHING 阶段只停住等待，不继续旋转搜索。
        :param idx: 想切换到的俯仰预设索引，例如 0 表示第 1 档，1 表示第 2 档
        """
        idx = idx % len(self._pitch_delta_deg)
        delta = self._pitch_delta_deg[idx]
        self._publish_pose_at_pitch_delta(delta)
        self._pitch_applied_idx = idx
        now = self.get_clock().now()
        self._pitch_settle_until = now + rclpy.duration.Duration(seconds=self._pitch_settle_sec)

    def _cmd_start(self) -> None:
        """
        :brief 启动自动找位流程：进入 searching 并重置本轮计数状态
        :desc 与 control 话题下发 start 的行为一致。
        """
        self._enabled = True
        self._state = self.STATE_SEARCHING
        self._search_t0 = self.get_clock().now()
        self._yaw_segment_t0 = self.get_clock().now()
        self._yaw_segments_done = 0
        self._pitch_idx = 0
        self._pitch_applied_idx = None
        self._stable_count = 0
        self._lost_count = 0
        if self._use_pose_scan:
            self._apply_pitch_preset_index(0)
        self._publish_status(self.STATE_SEARCHING)

    def _on_control(self, msg: String) -> None:
        """
        :brief 处理外部控制指令：start 启动，stop/reset 停止并回 idle
        :desc 大小写不敏感；别的字符串打日志警告。
        :param msg: String，data 为 start / stop / reset
        """
        cmd = (msg.data or '').strip().lower()
        if cmd == 'start':
            self._cmd_start()
        elif cmd in ('stop', 'reset'):
            self._enabled = False
            self._state = self.STATE_IDLE
            self._stop_motion()
            self._publish_baseline_pose()
            self._publish_status(self.STATE_IDLE)
        else:
            self.get_logger().warn(f'未知控制指令: {msg.data!r}（支持 start / stop / reset）')

    def _on_human_pose(self, msg: HumanPose) -> None:
        """
        :brief 接收最新一帧人体检测结果，并缓存为当前观测值
        :desc 这个回调本身不直接控制机器人动作，只负责把最新的 HumanPose 消息保存到 self._hp；
              后续由定时器循环读取这份最新观测，再决定继续搜索、对中、调距离或置 ready。
        :param msg: 当前收到的人体检测消息，类型为 HumanPose，包含 detected、bbox_center_x、bbox_area、ready_pose 等字段
        """
        self._hp = msg

    def _in_pitch_settle(self) -> bool:
        """
        :brief 判断当前是否仍处于俯仰切换后的稳定等待期
        :desc 如果上一条俯仰姿态刚发出去，机身可能还在过渡；在这段等待期内，SEARCHING 阶段不会继续旋转。
        :return: 仍需等待返回 True，否则返回 False
        """
        if self._pitch_settle_until is None:
            return False
        return self.get_clock().now() < self._pitch_settle_until

    def _advance_search_pitch(self) -> None:
        """
        :brief 搜索阶段切换到下一档俯仰预设
        :desc 把当前俯仰档位向后推进一格；如果已经到最后一档，就回到第 1 档继续循环。
              只有 use_pose_scan=True 时才会真的发布姿态指令。
        """
        self._pitch_idx = (self._pitch_idx + 1) % len(self._pitch_delta_deg)
        if self._use_pose_scan:
            self._apply_pitch_preset_index(self._pitch_idx)

    def _search_tick(self, now: rclpy.time.Time) -> None:
        """
        :brief 在 SEARCHING 阶段跑一帧：检查超时/检出，并按策略继续扫描
        :desc 见到人→centering；超时→failed；否则分段转 yaw，段数够了换俯仰档。
        :param now: 当前时间
        """
        if self._search_t0 is None:
            self._search_t0 = now
        elapsed = (now - self._search_t0).nanoseconds / 1e9
        # 注意：未判「>0」时若 timeout==0 会变成 elapsed>=0，首帧即超时并直接进入 failed。
        if self._search_timeout_sec > 0.0 and elapsed >= self._search_timeout_sec:
            self._state = self.STATE_FAILED
            self._enabled = False
            self._stop_motion()
            self._publish_baseline_pose()
            self._publish_status(self.STATE_FAILED, '|timeout')
            return

        hp = self._hp
        if hp is not None and hp.detected:
            self._stop_motion()
            self._publish_baseline_pose()
            self._state = self.STATE_CENTERING
            self._stable_count = 0
            self._lost_count = 0
            self._publish_status(self.STATE_CENTERING)
            return

        if self._yaw_segment_t0 is None:
            self._yaw_segment_t0 = now

        if self._in_pitch_settle():
            self._stop_motion()
            return

        seg_elapsed = (now - self._yaw_segment_t0).nanoseconds / 1e9
        if seg_elapsed >= self._search_yaw_segment_sec:
            self._yaw_segment_t0 = now
            self._yaw_segments_done += 1
            if self._yaw_segments_done >= self._yaw_segments_before_pitch:
                self._yaw_segments_done = 0
                self._advance_search_pitch()

        t = Twist()
        t.linear.x = 0.0
        t.linear.y = 0.0
        t.linear.z = 0.0
        t.angular.x = 0.0
        t.angular.y = 0.0
        t.angular.z = float(self._search_angular_z)
        self._twist_pub.publish(t)

    def _align_tick(self, hp: HumanPose) -> None:
        """
        :brief 人已检出时先对中再调距离，连续稳定后切到 ready
        :desc 先根据 bbox_center_x 把人转到画面中间，再根据 bbox_area 前进或后退调距离；
              当位置和距离连续多帧都达标，且（启用时）ready_pose=True，就切到 ready。
        :param hp: 当前这一帧的人体检测结果（进入本函数前已确认 detected=True）
        """
        cx = float(hp.bbox_center_x)
        err = cx - 0.5
        area = float(hp.bbox_area)

        if abs(err) > self._center_tol:
            self._state = self.STATE_CENTERING
            w = self._center_sign * (-self._center_kp * err)
            w = max(-self._max_w, min(self._max_w, w))
            t = Twist()
            t.angular.z = w
            self._twist_pub.publish(t)
            return

        self._stop_motion()

        if area < self._area_min:
            self._state = self.STATE_APPROACHING
            vx = self._approach_kp * (self._area_min - area)
            vx = max(self._min_vx_f, min(self._max_vx, vx))
            t = Twist()
            t.linear.x = vx
            self._twist_pub.publish(t)
            return

        if area > self._area_max:
            self._state = self.STATE_APPROACHING
            vx = -self._approach_kp * (area - self._area_max)
            vx = max(-self._max_vx, min(-self._min_vx_b, vx))
            t = Twist()
            t.linear.x = vx
            self._twist_pub.publish(t)
            return

        self._state = self.STATE_STABILIZING
        if self._require_ready and not hp.ready_pose:
            self._stable_count = 0
            self._publish_status(self.STATE_STABILIZING, '|wait_ready_pose')
            return

        self._stable_count += 1
        if self._stable_count >= self._stable_need:
            self._state = self.STATE_READY
            self._enabled = False
            self._stop_motion()
            self._publish_baseline_pose()
            self._publish_status(self.STATE_READY)
        elif self._stable_count == 1 or self._stable_count % 5 == 0:
            self._publish_status(self.STATE_STABILIZING, f'|{self._stable_count}/{self._stable_need}')

    def _on_timer(self) -> None:
        """
        :brief 定时器主循环：每个周期根据当前状态执行对应动作
        :desc searching 调 _search_tick；其余状态若丢检超阈值回 searching；持续检出时执行 _align_tick。
        """
        if not self._enabled:
            return
        if self._state in (self.STATE_READY, self.STATE_FAILED):
            return

        now = self.get_clock().now()
        hp = self._hp

        if self._state == self.STATE_SEARCHING:
            self._search_tick(now)
            return

        if hp is None or not hp.detected:
            self._lost_count += 1
            self._stop_motion()
            if self._lost_count >= self._lost_frames_thresh:
                self._state = self.STATE_SEARCHING
                self._search_t0 = now
                self._yaw_segment_t0 = now
                self._yaw_segments_done = 0
                self._pitch_idx = 0
                self._stable_count = 0
                self._lost_count = 0
                if self._use_pose_scan:
                    self._apply_pitch_preset_index(0)
                self._publish_status(self.STATE_SEARCHING, '|lost_target')
            return

        self._lost_count = 0
        self._align_tick(hp)


def main(args: Optional[list] = None) -> None:

    rclpy.init(args=args)
    node = AutoPositionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._stop_motion()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
