'''
:brief 语音找位全流程 + 云端监控 WebSocket + MQTT/HTTP 遥测（单 launch）
:desc Include situp_voice_full（不双开 pose_detector / situp_counter）；叠加 telemetry_bridge 与
      monitor_ws_bridge，行为对齐 bridge_pkg/situp_counter_monitor_cloud 中的遥测与监控部分。
      不 Include situp_counter.launch.py；include_puppy_motion 为 true 时不重复启动 ros_robot_controller。
      设计说明见 puppyfit/doc/plan/plan418.md。

:author slt
:date 2026/04/18
:version 1.0.1
:history
    1.0.1 - 2026/04/27
        :brief 透传训练桥录像联动与会话录像时长上限参数
        :desc 新增 session_record_max_duration_sec、training_record_enabled、
              training_record_start_topic、training_record_stop_topic，保证云监控组合入口下
              云端 start_training 同样能触发录制并复用自动上传链路。
    1.0.0 - 2026/04/18
        :brief 初始版本
        :desc 复用 situp_voice_full 并叠加 telemetry_bridge / monitor_ws_bridge，
              在单 launch 中提供语音找位计数与云端监控能力。
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from bridge_pkg.monitor.launch_include import monitor_ws_declare_and_include
from bridge_pkg.telemetry.launch_common import (
    mqtt_telemetry_bridge_node,
    mqtt_telemetry_declare_launch_arguments,
)


def generate_launch_description():
    bringup_share = get_package_share_directory('bringup_pkg')
    voice_full_launch = os.path.join(bringup_share, 'launch', 'situp_voice_full.launch.py')

    return LaunchDescription(
        [
            DeclareLaunchArgument('enable_video_overlay', default_value='true'),
            DeclareLaunchArgument('raw_image_topic', default_value='/pose_image'),
            DeclareLaunchArgument('overlay_image_topic', default_value='/pose_image_overlay'),
            DeclareLaunchArgument('stats_topic', default_value='/pose_video_stats'),
            DeclareLaunchArgument('session_record_max_duration_sec', default_value='600.0'),
            DeclareLaunchArgument('training_record_enabled', default_value='true'),
            DeclareLaunchArgument('training_record_start_topic', default_value='session/record_start'),
            DeclareLaunchArgument('training_record_stop_topic', default_value='session/record_stop'),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(voice_full_launch),
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
            *mqtt_telemetry_declare_launch_arguments(
                enable_monitor_ws_default='true',
                declare_backend_config_path=False,
            ),
            *monitor_ws_declare_and_include(),
            mqtt_telemetry_bridge_node(),
        ]
    )
