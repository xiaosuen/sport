#!/usr/bin/env python3
'''
:brief 手柄遥控节点（Joy → Puppy 速度）
:desc 订阅 /joy，驱动 PuppyPi：默认发 puppy_control_msgs/Velocity 到 /puppy_control/velocity_move。
      左摇杆：竖直前后平移，水平左右转向；可选右摇杆垂直轴调节机体高度；可选 L1/L2 调节俯仰（抬头/低头），
      均通过 puppy_control_msgs/Pose 发至 /puppy_control/pose（与 puppy 运动学 stance pitch 一致，等效前后腿协调）。
      joy 无新包时 stale_timeout 默认关闭。

:author ubuntu
:date 2026/03/29
:version 1.3.0
:history
    1.3.0 - 2026/03/29
        :brief L1/L2 映射 Pose.pitch 实现抬头/低头，与高度共用 Pose 发布
    1.2.0 - 2026/03/29
        :brief 高度轴默认改为 3、禁止与左摇杆轴相同、仅线速度空闲时调高度以防耦合
    1.1.0 - 2026/03/29
        :brief 右摇杆垂直轴发布 Pose 调节 puppy_control 机体 height
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块与类注释
'''

from __future__ import annotations

import math
from typing import Optional

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from puppy_control_msgs.msg import Pose, Velocity
from sensor_msgs.msg import Joy

# twist_nav -> Cmd_vel_nav -> VelocityFun：|x_cm_s|<=35 且 |yaw|<=51° 才 move
_PUPPY_NAV_MAX_LINEAR_X = 0.35
_PUPPY_NAV_MAX_YAW_RAD = math.radians(50.9)
# velocity_move：x 为 cm/s，与 puppy_demo 一致；限幅避免过激
_VMOVE_MAX_CM_S = 35.0
_VMOVE_MAX_YAW_RAD = math.radians(50.9)
# 与 puppy_control PoseFun 一致：abs(pitch) <= 31°
_PITCH_LIMIT_RAD = math.radians(31.0)


def _deadzone_scalar(value: float, deadzone: float) -> float:
    if deadzone <= 0.0:
        return value
    a = abs(value)
    if a < deadzone:
        return 0.0
    sign = 1.0 if value > 0.0 else -1.0
    return sign * (a - deadzone) / max(1e-6, 1.0 - deadzone)


def _axis_value(msg: Joy, index: int) -> float:
    if index < 0 or index >= len(msg.axes):
        return 0.0
    return float(msg.axes[index])


def _button_pressed(msg: Joy, index: int) -> bool:
    if index < 0 or index >= len(msg.buttons):
        return False
    return int(msg.buttons[index]) != 0


class JoyTeleopNode(Node):
    '''
    :brief Joy 映射 ROS2 节点
    :desc 将摇杆轴映射为 Twist 或 Velocity；可选 Pose 调节 height 与 pitch（L1/L2）。
    '''

    def __init__(self) -> None:
        super().__init__("puppy_joy_teleop")

        self.declare_parameter("joy_topic", "/joy")
        self.declare_parameter(
            "output_mode",
            "velocity_move",
        )
        self.declare_parameter("cmd_vel_topic", "/cmd_vel_nav")
        self.declare_parameter("velocity_move_topic", "/puppy_control/velocity_move")
        self.declare_parameter("publish_rate", 30.0)
        self.declare_parameter("axis_linear", 1)
        self.declare_parameter(
            "axis_angular",
            0,
        )
        self.declare_parameter("invert_linear", False)
        self.declare_parameter("invert_angular", False)
        self.declare_parameter("scale_linear", 0.35)
        self.declare_parameter("scale_angular", 0.85)
        self.declare_parameter("max_linear", 0.35)
        self.declare_parameter("max_angular", 0.85)
        self.declare_parameter("velocity_move_max_cm_s", 28.0)
        self.declare_parameter("deadzone", 0.12)
        self.declare_parameter("require_enable_button", False)
        self.declare_parameter("enable_button", 4)
        self.declare_parameter(
            "stale_timeout_sec",
            0.0,
        )
        self.declare_parameter("debug_log_throttle_sec", 0.0)
        # 右摇杆（或指定轴）调节 puppy_control 机体高度：向 /puppy_control/pose 发 Pose（与 puppy.py PoseFun 一致）
        self.declare_parameter("enable_height_control", True)
        self.declare_parameter("pose_topic", "/puppy_control/pose")
        # 右摇杆竖直：常见映射为 axes[3]（顺序 LX,LY,RX,RY）；Xbox 类带扳机键时 RY 常为 axes[4]，请按 `ros2 topic echo /joy` 核对
        self.declare_parameter("axis_height", 3)
        self.declare_parameter(
            "height_deadzone",
            0.12,
        )
        # True：仅当左摇杆线速度轴在死区内时才调节高度，避免与前进/后退耦合（防止错轴或驱动串扰）
        self.declare_parameter("height_only_when_linear_idle", True)
        self.declare_parameter(
            "height_axis_scale",
            -1.0,
        )
        self.declare_parameter("height_rate_cm_per_s", 5.0)
        self.declare_parameter("height_min", -15.0)
        self.declare_parameter("height_max", -5.0)
        self.declare_parameter("height_initial", -10.0)
        self.declare_parameter("pose_roll", 0.0)
        self.declare_parameter("pose_pitch", 0.0)
        self.declare_parameter("pose_yaw", 0.0)
        self.declare_parameter("pose_x_shift", -0.5)
        self.declare_parameter("pose_stance_x", 0)
        self.declare_parameter("pose_stance_y", 0)
        self.declare_parameter("pose_run_time", 0)
        # 俯仰：L1 抬头（pitch 增大）、L2 扳机模拟量低头（pitch 减小）；由 stance pitch 实现整机抬头/低头
        self.declare_parameter("enable_pitch_control", True)
        self.declare_parameter("button_pitch_up", 6)
        self.declare_parameter("axis_pitch_down", 5)
        self.declare_parameter("pitch_rate_rad_per_s", 0.45)
        self.declare_parameter("pitch_down_rate_rad_per_s", 0.45)
        self.declare_parameter("l2_axis_rest_value", 1.0)
        self.declare_parameter("l2_axis_pull_min", -1.0)
        self.declare_parameter("l2_pull_deadzone", 0.03)
        self.declare_parameter("pitch_only_when_linear_idle", True)

        joy_topic = self.get_parameter("joy_topic").get_parameter_value().string_value or "/joy"
        self._mode = (
            self.get_parameter("output_mode").get_parameter_value().string_value or "velocity_move"
        ).strip().lower()
        cmd_topic = self.get_parameter("cmd_vel_topic").get_parameter_value().string_value or "/cmd_vel_nav"
        vel_topic = (
            self.get_parameter("velocity_move_topic").get_parameter_value().string_value
            or "/puppy_control/velocity_move"
        )
        rate = float(self.get_parameter("publish_rate").value)
        if rate <= 0.0:
            rate = 30.0

        self._axis_linear = int(self.get_parameter("axis_linear").value)
        self._axis_angular = int(self.get_parameter("axis_angular").value)
        self._invert_linear = bool(self.get_parameter("invert_linear").value)
        self._invert_angular = bool(self.get_parameter("invert_angular").value)
        self._scale_linear = float(self.get_parameter("scale_linear").value)
        self._scale_angular = float(self.get_parameter("scale_angular").value)
        self._max_linear = float(self.get_parameter("max_linear").value)
        self._max_angular = float(self.get_parameter("max_angular").value)
        self._vmove_max_cm = float(self.get_parameter("velocity_move_max_cm_s").value)
        self._deadzone = float(self.get_parameter("deadzone").value)
        self._require_enable = bool(self.get_parameter("require_enable_button").value)
        self._enable_button = int(self.get_parameter("enable_button").value)
        self._stale_timeout = float(self.get_parameter("stale_timeout_sec").value)
        self._debug_log_dt = float(self.get_parameter("debug_log_throttle_sec").value)
        self._last_debug_log = 0.0

        self._enable_height = bool(self.get_parameter("enable_height_control").value)
        pose_topic = (
            self.get_parameter("pose_topic").get_parameter_value().string_value or "/puppy_control/pose"
        )
        self._axis_height = int(self.get_parameter("axis_height").value)
        if self._axis_height in (self._axis_linear, self._axis_angular):
            self.get_logger().error(
                f"axis_height={self._axis_height} 与左摇杆轴冲突 "
                f"(axis_linear={self._axis_linear}, axis_angular={self._axis_angular})，已关闭高度控制"
            )
            self._enable_height = False
        self._height_deadzone = float(self.get_parameter("height_deadzone").value)
        self._height_only_when_linear_idle = bool(
            self.get_parameter("height_only_when_linear_idle").value
        )
        self._height_axis_scale = float(self.get_parameter("height_axis_scale").value)
        self._height_rate = float(self.get_parameter("height_rate_cm_per_s").value)
        self._height_min = float(self.get_parameter("height_min").value)
        self._height_max = float(self.get_parameter("height_max").value)
        self._height_state = float(self.get_parameter("height_initial").value)
        self._height_state = max(self._height_min, min(self._height_max, self._height_state))
        self._pose_roll = float(self.get_parameter("pose_roll").value)
        self._pose_pitch = float(self.get_parameter("pose_pitch").value)
        self._pose_yaw = float(self.get_parameter("pose_yaw").value)
        self._pose_x_shift = float(self.get_parameter("pose_x_shift").value)
        self._pose_stance_x = int(self.get_parameter("pose_stance_x").value)
        self._pose_stance_y = int(self.get_parameter("pose_stance_y").value)
        self._pose_run_time = int(self.get_parameter("pose_run_time").value)

        self._enable_pitch = bool(self.get_parameter("enable_pitch_control").value)
        self._button_pitch_up = int(self.get_parameter("button_pitch_up").value)
        self._axis_pitch_down = int(self.get_parameter("axis_pitch_down").value)
        self._pitch_rate = float(self.get_parameter("pitch_rate_rad_per_s").value)
        self._pitch_down_rate = float(self.get_parameter("pitch_down_rate_rad_per_s").value)
        self._l2_rest = float(self.get_parameter("l2_axis_rest_value").value)
        self._l2_pull_min = float(self.get_parameter("l2_axis_pull_min").value)
        self._l2_pull_deadzone = float(self.get_parameter("l2_pull_deadzone").value)
        self._pitch_only_when_linear_idle = bool(
            self.get_parameter("pitch_only_when_linear_idle").value
        )
        self._pitch_state = float(self._pose_pitch)
        self._pitch_state = max(
            -_PITCH_LIMIT_RAD, min(_PITCH_LIMIT_RAD, self._pitch_state)
        )

        self._last_joy: Optional[Joy] = None
        self._last_joy_time_sec: float = 0.0

        self.create_subscription(Joy, joy_topic, self._on_joy, 10)

        self._pub_twist: Optional[object] = None
        self._pub_velocity: Optional[object] = None
        if self._mode == "twist_nav":
            self._pub_twist = self.create_publisher(Twist, cmd_topic, 10)
        elif self._mode == "velocity_move":
            self._pub_velocity = self.create_publisher(Velocity, vel_topic, 10)
        else:
            self.get_logger().warn(
                f"未知 output_mode={self._mode!r}，回退 velocity_move"
            )
            self._mode = "velocity_move"
            self._pub_velocity = self.create_publisher(Velocity, vel_topic, 10)

        period = 1.0 / rate
        self._period = period
        self.create_timer(period, self._on_timer)

        self._pub_pose: Optional[object] = None
        if self._enable_height or self._enable_pitch:
            self._pub_pose = self.create_publisher(Pose, pose_topic, 10)

        if self._mode == "twist_nav":
            self.get_logger().info(
                f"puppy_joy_teleop: joy={joy_topic} -> Twist {cmd_topic} "
                f"(linear_axis={self._axis_linear}, yaw_axis={self._axis_angular})"
            )
        else:
            self.get_logger().info(
                f"puppy_joy_teleop: joy={joy_topic} -> Velocity {vel_topic} "
                f"(linear_axis={self._axis_linear}, yaw_axis={self._axis_angular}, max_cm_s={self._vmove_max_cm})"
            )
        if self._pub_pose is not None:
            if self._enable_height:
                self.get_logger().info(
                    f"puppy_joy_teleop: height -> Pose {pose_topic} "
                    f"(axis_height={self._axis_height}, scale={self._height_axis_scale}, "
                    f"rate_cm/s={self._height_rate}, range=[{self._height_min}, {self._height_max}], "
                    f"only_when_linear_idle={self._height_only_when_linear_idle})"
                )
            if self._enable_pitch:
                self.get_logger().info(
                    f"puppy_joy_teleop: pitch -> Pose {pose_topic} "
                    f"(L1=buttons[{self._button_pitch_up}] 抬头, L2=axes[{self._axis_pitch_down}] 低头, "
                    f"rate={math.degrees(self._pitch_rate):.1f}°/s, limit=±31°, "
                    f"only_when_linear_idle={self._pitch_only_when_linear_idle})"
                )

    def _on_joy(self, msg: Joy) -> None:
        self._last_joy = msg
        self._last_joy_time_sec = self.get_clock().now().nanoseconds / 1e9

    def _maybe_debug_log(self, text: str, now_sec: float) -> None:
        if self._debug_log_dt <= 0.0:
            return
        if now_sec - self._last_debug_log < self._debug_log_dt:
            return
        self._last_debug_log = now_sec
        self.get_logger().info(text)

    def _on_timer(self) -> None:
        now_sec = self.get_clock().now().nanoseconds / 1e9

        if self._last_joy is None:
            self._publish_stop()
            return

        if self._stale_timeout > 0.0 and (now_sec - self._last_joy_time_sec) > self._stale_timeout:
            self._publish_stop()
            return

        msg = self._last_joy
        # 高度/俯仰与使能键解耦：未按使能键仍可调 Pose
        self._maybe_publish_pose(msg, now_sec)

        if self._require_enable and not _button_pressed(msg, self._enable_button):
            self._publish_stop()
            return

        lin_axis = _axis_value(msg, self._axis_linear)
        ang_axis = _axis_value(msg, self._axis_angular)
        if self._invert_linear:
            lin_axis = -lin_axis
        if self._invert_angular:
            ang_axis = -ang_axis

        lin_axis = _deadzone_scalar(lin_axis, self._deadzone)
        ang_axis = _deadzone_scalar(ang_axis, self._deadzone)

        if self._mode == "velocity_move":
            x_cm = max(
                -_VMOVE_MAX_CM_S,
                min(
                    _VMOVE_MAX_CM_S,
                    lin_axis * self._vmove_max_cm,
                ),
            )
            yaw = max(
                -_VMOVE_MAX_YAW_RAD,
                min(_VMOVE_MAX_YAW_RAD, ang_axis * self._scale_angular),
            )
            if abs(x_cm) < 1e-3:
                x_cm = 0.0
            if abs(yaw) < 1e-4:
                yaw = 0.0
            out = Velocity()
            out.x = float(x_cm)
            out.y = 0.0
            out.yaw_rate = float(yaw)
            if self._pub_velocity is not None:
                self._pub_velocity.publish(out)
            self._maybe_debug_log(
                f"cmd velocity_move x={x_cm:.1f} cm/s yaw={yaw:.3f} rad/s",
                now_sec,
            )
            return

        twist = Twist()
        twist.linear.x = max(
            -self._max_linear, min(self._max_linear, lin_axis * self._scale_linear)
        )
        twist.linear.y = 0.0
        twist.linear.z = 0.0
        twist.angular.x = 0.0
        twist.angular.y = 0.0
        twist.angular.z = max(
            -self._max_angular, min(self._max_angular, ang_axis * self._scale_angular)
        )

        if abs(twist.linear.x) < 1e-6:
            twist.linear.x = 0.0
        if abs(twist.angular.z) < 1e-6:
            twist.angular.z = 0.0

        twist.linear.x = max(
            -_PUPPY_NAV_MAX_LINEAR_X, min(_PUPPY_NAV_MAX_LINEAR_X, twist.linear.x)
        )
        twist.angular.z = max(
            -_PUPPY_NAV_MAX_YAW_RAD, min(_PUPPY_NAV_MAX_YAW_RAD, twist.angular.z)
        )

        if self._pub_twist is not None:
            self._pub_twist.publish(twist)
        self._maybe_debug_log(
            f"cmd twist_nav linear.x={twist.linear.x:.3f} angular.z={twist.angular.z:.3f}",
            now_sec,
        )

    def _linear_axis_idle(self, msg: Joy) -> bool:
        '''左摇杆线速度轴是否在死区内（用于与高度解耦）。'''
        v = _axis_value(msg, self._axis_linear)
        if self._invert_linear:
            v = -v
        v = _deadzone_scalar(v, self._deadzone)
        return abs(v) < 1e-6

    def _l2_pull_normalized(self, msg: Joy) -> float:
        '''L2 扳机拉量归一化到 [0,1]：未拉为 0，拉满为 1（适配 axes 静止约 1.0、拉满约 -1.0）。'''
        ax = _axis_value(msg, self._axis_pitch_down)
        span = self._l2_rest - self._l2_pull_min
        if span <= 1e-6:
            return 0.0
        pull = max(0.0, min(1.0, (self._l2_rest - ax) / span))
        if pull < self._l2_pull_deadzone:
            return 0.0
        return pull

    def _maybe_publish_pose(self, msg: Joy, now_sec: float) -> None:
        '''
        :brief 根据右摇杆竖直积分 height、L1/L2 调节 pitch，向 puppy_control 发布 Pose
        :desc 与 puppy.py PoseFun 一致；pitch 由运动学实现整机俯仰（前后腿协调）。yaw 固定发 0.0 以满足校验。
        '''
        if self._pub_pose is None:
            return

        updated = False
        linear_ok_for_pose = self._linear_axis_idle(msg)

        if self._enable_height:
            if not self._height_only_when_linear_idle or linear_ok_for_pose:
                h_axis = _axis_value(msg, self._axis_height)
                h_axis = _deadzone_scalar(h_axis, self._height_deadzone)
                if abs(h_axis) >= 1e-6:
                    delta_h = h_axis * self._height_axis_scale * self._height_rate * self._period
                    self._height_state = max(
                        self._height_min, min(self._height_max, self._height_state + delta_h)
                    )
                    updated = True

        if self._enable_pitch:
            if not self._pitch_only_when_linear_idle or linear_ok_for_pose:
                if _button_pressed(msg, self._button_pitch_up):
                    self._pitch_state += self._pitch_rate * self._period
                    updated = True
                pull = self._l2_pull_normalized(msg)
                if pull > 0.0:
                    self._pitch_state -= pull * self._pitch_down_rate * self._period
                    updated = True
            self._pitch_state = max(
                -_PITCH_LIMIT_RAD, min(_PITCH_LIMIT_RAD, self._pitch_state)
            )

        if not updated:
            return

        p = Pose()
        p.roll = float(self._pose_roll)
        p.pitch = float(self._pitch_state)
        p.yaw = 0.0
        p.height = float(self._height_state)
        p.x_shift = float(self._pose_x_shift)
        p.stance_x = float(self._pose_stance_x)
        p.stance_y = float(self._pose_stance_y)
        p.run_time = int(self._pose_run_time)
        self._pub_pose.publish(p)
        self._maybe_debug_log(
            f"cmd pose height={self._height_state:.2f} pitch_deg={math.degrees(self._pitch_state):.1f}",
            now_sec,
        )

    def _publish_stop(self) -> None:
        if self._mode == "velocity_move" and self._pub_velocity is not None:
            self._pub_velocity.publish(Velocity(x=0.0, y=0.0, yaw_rate=0.0))
        elif self._pub_twist is not None:
            self._pub_twist.publish(Twist())


def main(args: Optional[list[str]] = None) -> None:
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = JoyTeleopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
