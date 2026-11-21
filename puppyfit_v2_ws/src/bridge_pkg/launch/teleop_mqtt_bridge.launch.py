'''
:brief 云遥控 MQTT → ROS2 桥接启动
:desc 启动 teleop_mqtt_bridge：订阅 puppy/control/{device_id}/teleop，发布至 puppy_control 与 /cmd_vel_nav。
      参数前缀 tp_ 便于与 mqtt_telemetry 等同文件组合时避免同名冲突。

:author slt
:date 2026/04/26
:version 1.0.0
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'tp_backend_config_path',
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description='backend_config.json（tp_ 前缀避免与其他 launch 的 backend_config_path 冲突）',
            ),
            DeclareLaunchArgument('tp_device_id', default_value=''),
            DeclareLaunchArgument('tp_broker_host', default_value=''),
            DeclareLaunchArgument('tp_broker_port', default_value=''),
            DeclareLaunchArgument('tp_use_tls', default_value=''),
            DeclareLaunchArgument('mqtt_username', default_value=''),
            DeclareLaunchArgument('mqtt_password', default_value=''),
            DeclareLaunchArgument('mqtt_client_id', default_value=''),
            DeclareLaunchArgument('mqtt_qos', default_value='1'),
            DeclareLaunchArgument(
                'teleop_topic_template',
                default_value='puppy/control/{device_id}/teleop',
            ),
            DeclareLaunchArgument('velocity_move_topic', default_value='/puppy_control/velocity_move'),
            DeclareLaunchArgument('pose_topic', default_value='/puppy_control/pose'),
            DeclareLaunchArgument('cmd_vel_nav_topic', default_value='/cmd_vel_nav'),
            DeclareLaunchArgument('command_hold_sec', default_value='0.3'),
            DeclareLaunchArgument('seq_idle_reset_sec', default_value='2.0'),
            Node(
                package='bridge_pkg',
                executable='teleop_mqtt_bridge',
                name='teleop_mqtt_bridge',
                output='screen',
                parameters=[
                    {
                        'backend_config_path': LaunchConfiguration('tp_backend_config_path'),
                        'device_id': LaunchConfiguration('tp_device_id'),
                        'broker_host': LaunchConfiguration('tp_broker_host'),
                        'broker_port': LaunchConfiguration('tp_broker_port'),
                        'use_tls': LaunchConfiguration('tp_use_tls'),
                        'mqtt_username': LaunchConfiguration('mqtt_username'),
                        'mqtt_password': LaunchConfiguration('mqtt_password'),
                        'mqtt_client_id': LaunchConfiguration('mqtt_client_id'),
                        'mqtt_qos': ParameterValue(LaunchConfiguration('mqtt_qos'), value_type=int),
                        'teleop_topic_template': LaunchConfiguration('teleop_topic_template'),
                        'velocity_move_topic': LaunchConfiguration('velocity_move_topic'),
                        'pose_topic': LaunchConfiguration('pose_topic'),
                        'cmd_vel_nav_topic': LaunchConfiguration('cmd_vel_nav_topic'),
                        'command_hold_sec': ParameterValue(
                            LaunchConfiguration('command_hold_sec'), value_type=float
                        ),
                        'seq_idle_reset_sec': ParameterValue(
                            LaunchConfiguration('seq_idle_reset_sec'), value_type=float
                        ),
                    }
                ],
            ),
        ]
    )
