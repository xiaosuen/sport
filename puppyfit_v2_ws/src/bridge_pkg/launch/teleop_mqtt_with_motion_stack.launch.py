'''
:brief 一键联启：底层运动栈 + 云遥控网桥
:desc 同时启动 puppy_control/puppy_motion_stack 与 bridge_pkg/teleop_mqtt_bridge，
      便于单终端联调前端按钮遥控。

:author GitHub Copilot
:date 2026/04/27
:version 1.0.0
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def generate_launch_description() -> LaunchDescription:
    bridge_share = get_package_share_directory('bridge_pkg')
    puppy_share = get_package_share_directory('puppy_control')

    teleop_bridge_launch = os.path.join(bridge_share, 'launch', 'teleop_mqtt_bridge.launch.py')
    motion_stack_launch = os.path.join(puppy_share, 'launch', 'puppy_motion_stack.launch.py')

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'tp_backend_config_path',
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description='teleop 网桥读取的 backend_config.json 绝对路径',
            ),
            DeclareLaunchArgument('tp_device_id', default_value=''),
            DeclareLaunchArgument('tp_broker_host', default_value=''),
            DeclareLaunchArgument('tp_broker_port', default_value=''),
            DeclareLaunchArgument('tp_use_tls', default_value=''),
            DeclareLaunchArgument('mqtt_username', default_value=''),
            DeclareLaunchArgument('mqtt_password', default_value=''),
            DeclareLaunchArgument('mqtt_client_id', default_value=''),
            DeclareLaunchArgument('mqtt_qos', default_value='1'),
            DeclareLaunchArgument('teleop_topic_template', default_value='puppy/control/{device_id}/teleop'),
            DeclareLaunchArgument('velocity_move_topic', default_value='/puppy_control/velocity_move'),
            DeclareLaunchArgument('pose_topic', default_value='/puppy_control/pose'),
            DeclareLaunchArgument('cmd_vel_nav_topic', default_value='/cmd_vel_nav'),
            DeclareLaunchArgument('command_hold_sec', default_value='0.3'),
            DeclareLaunchArgument('seq_idle_reset_sec', default_value='2.0'),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(motion_stack_launch),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(teleop_bridge_launch),
                launch_arguments=[
                    ('tp_backend_config_path', LaunchConfiguration('tp_backend_config_path')),
                    ('tp_device_id', LaunchConfiguration('tp_device_id')),
                    ('tp_broker_host', LaunchConfiguration('tp_broker_host')),
                    ('tp_broker_port', LaunchConfiguration('tp_broker_port')),
                    ('tp_use_tls', LaunchConfiguration('tp_use_tls')),
                    ('mqtt_username', LaunchConfiguration('mqtt_username')),
                    ('mqtt_password', LaunchConfiguration('mqtt_password')),
                    ('mqtt_client_id', LaunchConfiguration('mqtt_client_id')),
                    ('mqtt_qos', LaunchConfiguration('mqtt_qos')),
                    ('teleop_topic_template', LaunchConfiguration('teleop_topic_template')),
                    ('velocity_move_topic', LaunchConfiguration('velocity_move_topic')),
                    ('pose_topic', LaunchConfiguration('pose_topic')),
                    ('cmd_vel_nav_topic', LaunchConfiguration('cmd_vel_nav_topic')),
                    ('command_hold_sec', LaunchConfiguration('command_hold_sec')),
                    ('seq_idle_reset_sec', LaunchConfiguration('seq_idle_reset_sec')),
                ],
            ),
        ]
    )
