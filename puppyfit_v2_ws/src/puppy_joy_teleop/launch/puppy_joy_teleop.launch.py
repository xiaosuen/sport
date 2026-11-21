'''
:brief 一键启动：可选四足运动栈 + joy + 手柄映射
:desc start_puppy_stack:=true（默认）时 Include puppy_control/launch/puppy_motion_stack.launch.py；
      再通过 OpaqueFunction 启动 joy_node 与 puppy_joy_teleop。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _joy_stack(context, *_args, **_kwargs):
    '''
    :brief 按上下文创建 joy_node 与 puppy_joy_teleop 节点列表
    :return 待加入 LaunchDescription 的 Action 列表
    '''
    dev_str = LaunchConfiguration("joy_dev").perform(context)
    try:
        device_id = int(dev_str)
    except ValueError:
        device_id = 0

    cmd_vel = LaunchConfiguration("cmd_vel_topic").perform(context)
    joy_topic = LaunchConfiguration("joy_topic").perform(context)
    output_mode = LaunchConfiguration("output_mode").perform(context)
    vel_move_topic = LaunchConfiguration("velocity_move_topic").perform(context)
    pose_topic = LaunchConfiguration("pose_topic").perform(context)
    enable_height_control = LaunchConfiguration("enable_height_control").perform(context)
    axis_height = LaunchConfiguration("axis_height").perform(context)
    height_axis_scale = LaunchConfiguration("height_axis_scale").perform(context)
    height_only_when_linear_idle = LaunchConfiguration("height_only_when_linear_idle").perform(
        context
    )
    enable_pitch_control = LaunchConfiguration("enable_pitch_control").perform(context)
    button_pitch_up = LaunchConfiguration("button_pitch_up").perform(context)
    axis_pitch_down = LaunchConfiguration("axis_pitch_down").perform(context)
    pitch_only_when_linear_idle = LaunchConfiguration("pitch_only_when_linear_idle").perform(
        context
    )

    joy_node = Node(
        package="joy",
        executable="joy_node",
        name="joy_node",
        output="screen",
        parameters=[
            {"device_id": device_id},
            {"deadzone": 0.0},
            {"autorepeat_rate": 0.0},
        ],
    )

    teleop_node = Node(
        package="puppy_joy_teleop",
        executable="joy_teleop_node",
        name="puppy_joy_teleop",
        output="screen",
        parameters=[
            {"joy_topic": joy_topic},
            {"cmd_vel_topic": cmd_vel},
            {"output_mode": output_mode},
            {"velocity_move_topic": vel_move_topic},
            {"pose_topic": pose_topic},
            {"enable_height_control": enable_height_control.lower() in ("true", "1", "yes")},
            {"axis_height": int(axis_height)},
            {"height_axis_scale": float(height_axis_scale)},
            {
                "height_only_when_linear_idle": height_only_when_linear_idle.lower()
                in ("true", "1", "yes")
            },
            {"enable_pitch_control": enable_pitch_control.lower() in ("true", "1", "yes")},
            {"button_pitch_up": int(button_pitch_up)},
            {"axis_pitch_down": int(axis_pitch_down)},
            {
                "pitch_only_when_linear_idle": pitch_only_when_linear_idle.lower()
                in ("true", "1", "yes")
            },
        ],
    )

    return [joy_node, teleop_node]


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 可选运动栈 + 手柄设备与输出模式参数 + OpaqueFunction 子图。
    :return LaunchDescription 实例
    '''
    puppy_share = get_package_share_directory("puppy_control")
    motion_stack_launch = os.path.join(puppy_share, "launch", "puppy_motion_stack.launch.py")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "start_puppy_stack",
                default_value="true",
                description="true：先启动 ros_robot_controller + puppy_control；仿真或仅调试手柄时可设 false",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(motion_stack_launch),
                condition=IfCondition(LaunchConfiguration("start_puppy_stack")),
            ),
            DeclareLaunchArgument(
                "joy_dev",
                default_value="0",
                description="Linux joy 设备编号（对应 /dev/input/js0 → 0）",
            ),
            DeclareLaunchArgument(
                "output_mode",
                default_value="velocity_move",
                description="velocity_move（默认）或 twist_nav",
            ),
            DeclareLaunchArgument(
                "velocity_move_topic",
                default_value="/puppy_control/velocity_move",
                description="output_mode=velocity_move 时的 Velocity 话题",
            ),
            DeclareLaunchArgument(
                "cmd_vel_topic",
                default_value="/cmd_vel_nav",
                description="output_mode=twist_nav 时的 Twist 话题",
            ),
            DeclareLaunchArgument(
                "joy_topic",
                default_value="/joy",
                description="sensor_msgs/Joy 订阅话题",
            ),
            DeclareLaunchArgument(
                "pose_topic",
                default_value="/puppy_control/pose",
                description="puppy_control_msgs/Pose，用于调节机体 height（与 puppy_control 订阅名一致）",
            ),
            DeclareLaunchArgument(
                "enable_height_control",
                default_value="true",
                description="true：右摇杆垂直轴（见 axis_height）调节机体高度",
            ),
            DeclareLaunchArgument(
                "axis_height",
                default_value="3",
                description="右摇杆竖直轴索引；常见 4 轴布局为 3（LX,LY,RX,RY），Xbox 带扳机时多为 4，请 echo /joy 确认",
            ),
            DeclareLaunchArgument(
                "height_axis_scale",
                default_value="-1.0",
                description="与轴值相乘后再积分；方向反了改为 1.0",
            ),
            DeclareLaunchArgument(
                "height_only_when_linear_idle",
                default_value="true",
                description="true：左摇杆不前/后推时才调高度，避免与平移耦合；需边跑边调高度时设 false",
            ),
            DeclareLaunchArgument(
                "enable_pitch_control",
                default_value="true",
                description="true：L1 抬头、L2 低头（Pose.pitch，与 README 手柄映射一致）",
            ),
            DeclareLaunchArgument(
                "button_pitch_up",
                default_value="6",
                description="抬头：Joy.buttons 下标（本机 L1 为 6）",
            ),
            DeclareLaunchArgument(
                "axis_pitch_down",
                default_value="5",
                description="低头：L2 扳机 Joy.axes 下标（本机为 5，静止约 1.0、拉满约 -1.0）",
            ),
            DeclareLaunchArgument(
                "pitch_only_when_linear_idle",
                default_value="true",
                description="true：与 height 相同，仅左摇杆线速度在死区内时才调俯仰",
            ),
            OpaqueFunction(function=_joy_stack),
        ]
    )
