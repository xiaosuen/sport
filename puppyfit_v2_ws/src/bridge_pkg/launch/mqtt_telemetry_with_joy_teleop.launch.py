'''
:brief 手柄遥运 + 运动栈 + MQTT/HTTP 遥测一键启动
:desc Include puppy_joy_teleop.launch.py（默认含 ros_robot_controller + puppy_control + joy），再启动 telemetry_bridge。
      与 mqtt_telemetry_with_controller.launch.py 不同：板卡仅由 puppy_motion_stack 起一份，避免重复节点与串口冲突。
      可选监控 WebSocket 与遥测同启。

:author slt
:date 2026/04/02
:version 1.0.2
:history
    1.0.3 - 2026/04/26
        :brief 可选 Include teleop_mqtt_bridge（与手柄同抢话题时请谨慎开启）
    1.0.2 - 2026/04/02
        :brief 共用参数默认：HTTP 心跳开、启动注册关
    1.0.1 - 2026/04/02
        :brief Include 监控 WebSocket（monitor_ws_declare_and_include）
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
    :desc 手柄运动栈、遥测桥、可选监控 WS、可选云遥控 MQTT 桥（与遥测共享 device / broker 参数映射）。
    :return LaunchDescription 实例
    '''
    joy_share = get_package_share_directory('puppy_joy_teleop')
    joy_launch = os.path.join(joy_share, 'launch', 'puppy_joy_teleop.launch.py')
    bridge_share = get_package_share_directory('bridge_pkg')
    teleop_bridge_launch = os.path.join(bridge_share, 'launch', 'teleop_mqtt_bridge.launch.py')

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'start_puppy_stack',
                default_value='true',
                description=(
                    'true：puppy_joy_teleop 内启动 ros_robot_controller + puppy_control（有电池话题）；'
                    'false：仅 joy 节点，无板卡则无真实电量'
                ),
            ),
            DeclareLaunchArgument(
                'joy_dev',
                default_value='0',
                description='Linux joy 编号，对应 /dev/input/js0 → 0',
            ),
            DeclareLaunchArgument(
                'include_teleop_mqtt_bridge',
                default_value='false',
                description='true 时同时启动云遥控桥（puppy/control/.../teleop → ROS）；与手柄可能抢同一组话题，建议分时或关手柄栈',
            ),
            *mqtt_telemetry_declare_launch_arguments(),
            *monitor_ws_declare_and_include(),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(joy_launch),
                launch_arguments=[
                    ('start_puppy_stack', LaunchConfiguration('start_puppy_stack')),
                    ('joy_dev', LaunchConfiguration('joy_dev')),
                ],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(teleop_bridge_launch),
                condition=IfCondition(LaunchConfiguration('include_teleop_mqtt_bridge')),
                launch_arguments=[
                    ('tp_backend_config_path', LaunchConfiguration('backend_config_path')),
                    ('tp_device_id', LaunchConfiguration('device_id')),
                    ('tp_broker_host', LaunchConfiguration('broker_host')),
                    ('tp_broker_port', LaunchConfiguration('broker_port')),
                    ('tp_use_tls', LaunchConfiguration('use_tls')),
                ],
            ),
            mqtt_telemetry_bridge_node(),
        ]
    )
