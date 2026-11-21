'''
:brief 仰卧起坐 + 自动找位 + 四足运动栈 一键启动
:desc 先 Include puppy_control/puppy_motion_stack（控制板 + puppy_control），再 Include
      exercise_engine_pkg/situp_with_auto_position，保证 /cmd_vel_nav、/puppy_control/pose 有订阅方。
      无硬件联调时可传 start_motion_stack:=false，仅起视觉与找位节点。

:author slt
:date 2026/04/08
:version 1.0.0
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    puppy_share = get_package_share_directory('puppy_control')
    motion_stack = os.path.join(puppy_share, 'launch', 'puppy_motion_stack.launch.py')

    engine_share = get_package_share_directory('exercise_engine_pkg')
    situp_auto = os.path.join(engine_share, 'launch', 'situp_with_auto_position.launch.py')

    return LaunchDescription([
        DeclareLaunchArgument(
            'start_motion_stack',
            default_value='true',
            description='true：先起 ros_robot_controller + puppy_control；false：仅 situp_with_auto_position（无舵机订阅）',
        ),
        DeclareLaunchArgument(
            'start_stopped',
            default_value='false',
            description='透传 situp_counter：true 时等 situp_control start 再计数',
        ),
        DeclareLaunchArgument(
            'use_backend_config',
            default_value='false',
            description='透传 web_dashboard：true 需 PUPPY_DEVICE_* 等环境变量',
        ),
        DeclareLaunchArgument(
            'backend_config_path',
            default_value='/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json',
            description='透传 backend_config.json 路径',
        ),
        DeclareLaunchArgument(
            'use_pose_scan',
            default_value='true',
            description='透传 auto_position：是否下发 /puppy_control/pose 俯仰扫描',
        ),
        DeclareLaunchArgument(
            'auto_position_autostart',
            default_value='true',
            description='透传 auto_position：启动即找位；编排驱动时请 false',
        ),
        DeclareLaunchArgument(
            'search_timeout_sec',
            default_value='15.0',
            description='透传 auto_position：SEARCHING 超时（秒），<=0 不超时',
        ),
        DeclareLaunchArgument(
            'search_angular_z',
            default_value='0.28',
            description='透传 auto_position：SEARCHING 角速度 z（rad/s）',
        ),
        DeclareLaunchArgument(
            'search_yaw_segment_sec',
            default_value='2.0',
            description='透传 auto_position：每段同向旋转秒数',
        ),
        DeclareLaunchArgument(
            'max_angular_z',
            default_value='0.35',
            description='透传 auto_position：对中角速度限幅',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(motion_stack),
            condition=IfCondition(LaunchConfiguration('start_motion_stack')),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(situp_auto),
            launch_arguments=[
                ('start_stopped', LaunchConfiguration('start_stopped')),
                ('use_backend_config', LaunchConfiguration('use_backend_config')),
                ('backend_config_path', LaunchConfiguration('backend_config_path')),
                ('use_pose_scan', LaunchConfiguration('use_pose_scan')),
                ('auto_position_autostart', LaunchConfiguration('auto_position_autostart')),
                ('search_timeout_sec', LaunchConfiguration('search_timeout_sec')),
                ('search_angular_z', LaunchConfiguration('search_angular_z')),
                ('search_yaw_segment_sec', LaunchConfiguration('search_yaw_segment_sec')),
                ('max_angular_z', LaunchConfiguration('max_angular_z')),
            ],
        ),
    ])
