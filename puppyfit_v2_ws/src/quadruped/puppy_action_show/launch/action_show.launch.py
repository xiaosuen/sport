'''
:brief 启动动作组表演节点
:desc 注册 puppy_run_action_service 参数并启动 action_show_node；需先有 puppy_control 或 puppy_motion_stack。

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
    :desc 启动 puppy_action_show/action_show_node。
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        DeclareLaunchArgument(
            "puppy_run_action_service",
            default_value="/puppy_control/runActionGroup",
            description="puppy_control 提供的 runActionGroup 服务全名",
        ),
        Node(
            package="puppy_action_show",
            executable="action_show_node",
            name="puppy_action_show",
            output="screen",
            parameters=[{
                "puppy_run_action_service": LaunchConfiguration("puppy_run_action_service"),
                "publish_catalog_on_start": True,
            }],
        ),
    ])
