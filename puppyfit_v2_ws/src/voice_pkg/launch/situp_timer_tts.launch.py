'''
:brief 仰卧起坐 + 定时 + 计数 TTS（v2）
:desc Include exercise_engine_pkg 的 situp_counter，并启动 timer_interrupt 与 counting_tts。

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
    :desc 组合 situp_counter、timer、counting_tts 等节点与参数。
    :return launch.LaunchDescription 实例
    '''
    pkg_engine = get_package_share_directory("exercise_engine_pkg")
    situp_launch = os.path.join(pkg_engine, "launch", "situp_counter.launch.py")

    return LaunchDescription([
        DeclareLaunchArgument(
            "duration_sec",
            default_value="60",
            description="到时向 situp_control 发送 stop",
        ),
        DeclareLaunchArgument(
            "encouragement_enabled",
            default_value="false",
            description="true：与 situp_voice_full 一致，按间隔播鼓励语",
        ),
        DeclareLaunchArgument(
            "encouragement_interval",
            default_value="5",
            description="鼓励语：每完成多少次播一条",
        ),
        DeclareLaunchArgument(
            "encouragement_phrases",
            default_value="",
            description="鼓励语文案，竖线 | 分隔；空则关（即使 encouragement_enabled 为 true）",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(situp_launch),
        ),
        Node(
            package="timer_interrupt",
            executable="timer",
            name="timer_interrupt",
            output="screen",
            parameters=[{
                "duration_sec": LaunchConfiguration("duration_sec"),
                "control_topic": "situp_control",
                "exercise_name": "仰卧起坐",
            }],
        ),
        Node(
            package="voice_pkg",
            executable="counting_tts",
            name="counting_tts",
            output="screen",
            parameters=[{
                "count_topic": "situp_count",
                "exercise_name": "仰卧起坐",
                "phrase_start": "仰卧起坐，开始计数",
                "phrase_end": "计时结束",
                "encouragement_enabled": LaunchConfiguration("encouragement_enabled"),
                "encouragement_interval": LaunchConfiguration("encouragement_interval"),
                "encouragement_phrases": LaunchConfiguration("encouragement_phrases"),
            }],
        ),
    ])
