'''
:brief 俯卧撑 + 定时中断 统一启动（示例）
:desc 当前仅启动定时器节点，向 pushup_control 发 stop；需与俯卧撑计数 launch 联用。
      若已有 pushup_counter_launch，可在此 IncludeLaunchDescription 引入。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 启动面向 pushup_control 的 timer 节点。
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        DeclareLaunchArgument(
            'duration_sec',
            default_value='60',
            description='定时时长（秒），到时俯卧撑计数进入停止状态',
        ),
        # 定时中断节点：到时向 pushup_control 发送 stop
        Node(
            package='timer_interrupt',
            executable='timer',
            name='timer_interrupt',
            output='screen',
            parameters=[{
                'duration_sec': LaunchConfiguration('duration_sec'),
                'control_topic': 'pushup_control',
                'exercise_name': '俯卧撑',
            }],
        ),
    ])
