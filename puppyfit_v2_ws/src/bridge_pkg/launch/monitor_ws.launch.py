'''
:brief 实时监控 WebSocket 上报（可单独启动）
:desc 参数与节点定义见 bridge_pkg.monitor.launch_common；与 mqtt_telemetry*.launch 共用同一套 declare，避免重复。
     单独启动时在此文件内声明 backend_config_path。

:author slt
:date 2026/04/02
:version 1.0.2
:history
    1.0.2 - 2026/04/02
        :brief backend_config_path 默认与 backend_config_default 一致
    1.0.1 - 2026/04/02
        :brief 按 doc/注释.md 补全模块头与 backend_config_path 声明
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH
from bridge_pkg.monitor.launch_common import (
    monitor_ws_bridge_node_action,
    monitor_ws_declare_launch_arguments,
)


def generate_launch_description() -> LaunchDescription:
    '''
    :brief 构建 LaunchDescription
    :return LaunchDescription 实例
    '''
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "backend_config_path",
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description="backend_config.json；可改为空以仅自动查找 / PUPPY_BACKEND_CONFIG",
            ),
            *monitor_ws_declare_launch_arguments(),
            monitor_ws_bridge_node_action(),
        ]
    )
