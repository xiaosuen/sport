'''
:brief voice_pkg 一键启动 launch
:desc 同时启动 voice_asr 与 voice_tts 两个节点；参数与 remap 可在后续版本中用 LaunchConfiguration 扩展。

:author ubuntu
:date 2026/03/28
:version 1.0.2
:history
    1.0.2 - 2026/03/29
        :brief 按 doc/注释.md 补充 history 版本行
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 初始 launch
'''

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :return launch.LaunchDescription 实例
    '''
    return LaunchDescription(
        [
            Node(
                package="voice_pkg",
                executable="voice_asr",
                name="voice_asr",
                output="screen",
            ),
            Node(
                package="voice_pkg",
                executable="voice_tts",
                name="voice_tts",
                output="screen",
            ),
        ]
    )
