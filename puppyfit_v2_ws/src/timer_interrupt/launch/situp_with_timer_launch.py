'''
:brief 仰卧起坐 + 定时中断 统一启动
:desc Include situp_counter.launch.py，并并行启动 timer_interrupt 节点，到时可自动停止计数。

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
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc Include 仰卧起坐 launch 与 timer 节点。
    :return LaunchDescription 实例
    '''
    pkg_pose_counter = get_package_share_directory('exercise_engine_pkg')
    situp_launch = os.path.join(pkg_pose_counter, 'launch', 'situp_counter.launch.py')

    return LaunchDescription([
        DeclareLaunchArgument(
            'duration_sec',
            default_value='60',
            description='定时时长（秒），到时后仰卧起坐计数进入停止状态',
        ),
        # 仰卧起坐模块：姿态检测 + 计数 + Web 展示
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(situp_launch),
        ),
        # 定时中断节点：到时向 situp_control 发送 stop（参数化便于与俯卧撑等共用同一节点）
        Node(
            package='timer_interrupt',
            executable='timer',
            name='timer_interrupt',
            output='screen',
            parameters=[{
                'duration_sec': LaunchConfiguration('duration_sec'),
                'control_topic': 'situp_control',
                'exercise_name': '仰卧起坐',
            }],
        ),
    ])
