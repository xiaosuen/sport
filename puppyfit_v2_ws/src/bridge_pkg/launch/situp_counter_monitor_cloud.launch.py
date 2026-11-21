'''
:brief 仰卧起坐栈 + 云端监控 + MQTT/HTTP 遥测（电池与在线状态）
:desc Include exercise_engine_pkg 的 situp_counter（pose_detector → /pose_image）；
      与 mqtt_telemetry_with_controller 相同地启动 ros_robot_controller（可选，真实电池）、
      telemetry_bridge（MQTT 遥测 + 默认 HTTP 设备状态）、monitor_ws（默认开启推流）。
      需 PUPPY_MQTT_*；HTTP 心跳默认开时需 PUPPY_DEVICE_*（见 telemetry.launch_common）。

:author slt
:date 2026/04/02
:version 1.1.0
:history
    1.1.0 - 2026/04/02
        :brief 并入 ros_robot_controller + telemetry_bridge（电池、MQTT、HTTP 在线）
    1.0.0 - 2026/04/02
        :brief 初始版本：仅 situp + monitor_ws
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

from bridge_pkg.monitor.launch_include import monitor_ws_declare_and_include
from bridge_pkg.telemetry.launch_common import (
    mqtt_telemetry_bridge_node,
    mqtt_telemetry_declare_launch_arguments,
)


def generate_launch_description() -> LaunchDescription:
    '''
    :brief 构建 LaunchDescription
    :return LaunchDescription 实例
    '''
    engine_share = get_package_share_directory('exercise_engine_pkg')
    situp_launch = os.path.join(engine_share, 'launch', 'situp_counter.launch.py')
    rrc_share = get_package_share_directory('ros_robot_controller')
    rrc_launch = os.path.join(rrc_share, 'launch', 'ros_robot_controller.launch.py')

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'use_backend_config',
                default_value='false',
                description=(
                    'situp 里 web_dashboard 是否 load_backend_config；'
                    'true 需已 export PUPPY_DEVICE_* / PUPPY_MQTT_*'
                ),
            ),
            DeclareLaunchArgument(
                'start_ros_robot_controller',
                default_value='true',
                description='false：不启控制板（无 /ros_robot_controller/battery，遥测用模拟电压）',
            ),
            *mqtt_telemetry_declare_launch_arguments(enable_monitor_ws_default='true'),
            *monitor_ws_declare_and_include(),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(situp_launch),
                launch_arguments=[
                    ('use_backend_config', LaunchConfiguration('use_backend_config')),
                    ('backend_config_path', LaunchConfiguration('backend_config_path')),
                ],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(rrc_launch),
                condition=IfCondition(LaunchConfiguration('start_ros_robot_controller')),
            ),
            mqtt_telemetry_bridge_node(),
        ]
    )
