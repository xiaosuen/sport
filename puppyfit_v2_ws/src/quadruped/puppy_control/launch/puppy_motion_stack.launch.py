'''
:brief 同时启动控制板桥接 + Puppy 运动控制节点
:desc 先 Include ros_robot_controller.launch.py，再 Include puppy_control.launch.py。

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
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 串联板卡桥接与四足控制两个 launch。
    :return LaunchDescription 实例
    '''
    rrc_share = get_package_share_directory('ros_robot_controller')
    rrc_launch = os.path.join(rrc_share, 'launch', 'ros_robot_controller.launch.py')

    puppy_share = get_package_share_directory('puppy_control')
    puppy_launch = os.path.join(puppy_share, 'launch', 'puppy_control.launch.py')

    return LaunchDescription(
        [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(rrc_launch),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(puppy_launch),
            ),
        ]
    )
