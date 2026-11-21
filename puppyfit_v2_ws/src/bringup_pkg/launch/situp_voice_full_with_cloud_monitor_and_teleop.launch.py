'''
:brief 语音仰卧起坐全流程 + 云端监控 + MQTT 遥控（单 launch）
:desc 复用 bringup_pkg/situp_voice_full_with_cloud_monitor 现有训练与云桥接流程，
      额外 Include bridge_pkg/teleop_mqtt_bridge 以接收远程遥控指令。
      仅新增 teleop MQTT 桥，不重复启动 ros_robot_controller / puppy_motion_stack。

:author slt
:date 2026/04/27
:version 1.0.1
:history
    1.0.1 - 2026/04/27
        :brief 透传训练桥录像联动与会话录像时长上限参数
        :desc 新增 session_record_max_duration_sec、training_record_enabled、
              training_record_start_topic、training_record_stop_topic，并继续向 teleop 组合入口透传，
              保证遥控场景下也复用同一套录像/上传链路。
    1.0.0 - 2026/04/27
        :brief 初始版本
        :desc 在 situp_voice_full_with_cloud_monitor 基础上叠加 teleop_mqtt_bridge，
              提供语音训练、云监控和远程遥控的单入口启动。
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    bringup_share = get_package_share_directory('bringup_pkg')
    bridge_share = get_package_share_directory('bridge_pkg')

    voice_cloud_launch = os.path.join(
        bringup_share,
        'launch',
        'situp_voice_full_with_cloud_monitor.launch.py',
    )
    teleop_bridge_launch = os.path.join(
        bridge_share,
        'launch',
        'teleop_mqtt_bridge.launch.py',
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument('tp_backend_config_path', default_value=''),
            DeclareLaunchArgument('tp_device_id', default_value=''),
            DeclareLaunchArgument('tp_broker_host', default_value=''),
            DeclareLaunchArgument('tp_broker_port', default_value=''),
            DeclareLaunchArgument('tp_use_tls', default_value=''),
            DeclareLaunchArgument('enable_video_overlay', default_value='true'),
            DeclareLaunchArgument('raw_image_topic', default_value='/pose_image'),
            DeclareLaunchArgument('overlay_image_topic', default_value='/pose_image_overlay'),
            DeclareLaunchArgument('stats_topic', default_value='/pose_video_stats'),
            DeclareLaunchArgument('session_record_max_duration_sec', default_value='600.0'),
            DeclareLaunchArgument('training_record_enabled', default_value='true'),
            DeclareLaunchArgument('training_record_start_topic', default_value='session/record_start'),
            DeclareLaunchArgument('training_record_stop_topic', default_value='session/record_stop'),
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
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(voice_cloud_launch),
                launch_arguments=[
                    ('enable_video_overlay', LaunchConfiguration('enable_video_overlay')),
                    ('raw_image_topic', LaunchConfiguration('raw_image_topic')),
                    ('overlay_image_topic', LaunchConfiguration('overlay_image_topic')),
                    ('stats_topic', LaunchConfiguration('stats_topic')),
                    ('session_record_max_duration_sec', LaunchConfiguration('session_record_max_duration_sec')),
                    ('training_record_enabled', LaunchConfiguration('training_record_enabled')),
                    ('training_record_start_topic', LaunchConfiguration('training_record_start_topic')),
                    ('training_record_stop_topic', LaunchConfiguration('training_record_stop_topic')),
                ],
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