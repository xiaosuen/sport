'''
:brief 控制板 + MQTT/HTTP 遥测一键启动
:desc 先启动 ros_robot_controller（发布 /ros_robot_controller/battery），再启动 telemetry_bridge。
      仅 mqtt_telemetry.launch.py 时若无电池 Publisher，后端只能收到模拟电量。

:author slt
:date 2026/04/02
:version 1.0.4
:history
    1.0.4 - 2026/04/02
        :brief 共用参数默认：HTTP 心跳开、启动注册关（见 telemetry.launch_common）
    1.0.3 - 2026/04/02
        :brief Include 监控 WebSocket（monitor_ws_declare_and_include）
    1.0.2 - 2026/04/02
        :brief 与 mqtt_telemetry 共用 telemetry.launch_common，避免 Include 重复 declare
    1.0.1 - 2026/04/02
        :brief 显式转发子 launch 参数（已改为共用 Node）
    1.0.0 - 2026/04/02
        :brief 初始版本
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
    :desc 控制板、遥测桥、可选监控 WS。
    :return LaunchDescription 实例
    '''
    rrc_share = get_package_share_directory('ros_robot_controller')
    rrc_launch = os.path.join(rrc_share, 'launch', 'ros_robot_controller.launch.py')

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'start_ros_robot_controller',
                default_value='true',
                description='false：不启动控制板（无电池 Publisher，遥测仍用模拟电压）',
            ),
            *mqtt_telemetry_declare_launch_arguments(),
            *monitor_ws_declare_and_include(),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(rrc_launch),
                condition=IfCondition(LaunchConfiguration('start_ros_robot_controller')),
            ),
            mqtt_telemetry_bridge_node(),
        ]
    )
