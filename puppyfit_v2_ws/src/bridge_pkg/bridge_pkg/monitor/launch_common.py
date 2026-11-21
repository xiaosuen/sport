'''
:brief 监控 WebSocket launch 共用：DeclareLaunchArgument 与 Node
:desc 供 monitor_ws.launch.py、telemetry.launch_common、monitor.launch_include 引用，避免重复 declare。
     与遥测共用 backend_config_path；设备覆盖使用 monitor_override_device_id。

:author slt
:date 2026/04/02
:version 1.0.2
:history
    1.0.2 - 2026/04/02
        :brief monitor_ws_declare_launch_arguments 支持 enable_monitor_ws_default
    1.0.1 - 2026/04/02
        :brief 模块迁至 bridge_pkg.monitor.launch_common
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def monitor_ws_declare_launch_arguments(
    *, enable_monitor_ws_default: str = "false"
) -> list:
    '''
    :brief 监控节点所需的 DeclareLaunchArgument 列表
    :desc 不含 backend_config_path（由 mqtt 侧或 monitor_ws.launch 单独声明）。
    :param enable_monitor_ws_default: enable_monitor_ws 的默认字符串（如组合 launch 需默认开监控传 \"true\"）
    :return DeclareLaunchArgument 列表
    '''
    return [
        DeclareLaunchArgument(
            "enable_monitor_ws",
            default_value=enable_monitor_ws_default,
            description="true：启动监控 WebSocket 客户端连接后端 /ws/camera/{device_id}",
        ),
        DeclareLaunchArgument(
            "ws_camera_base_url",
            default_value="",
            description="非空则与 device_id 同时覆盖配置文件中的 WebSocket 基址",
        ),
        DeclareLaunchArgument(
            "monitor_override_device_id",
            default_value="",
            description="非空则与 ws_camera_base_url 同时覆盖配置中的 device_id（避免与遥测 launch 的 device_id 重名）",
        ),
        DeclareLaunchArgument("image_topic", default_value="/pose_image"),
        DeclareLaunchArgument("count_topic", default_value="/situp_count"),
        DeclareLaunchArgument("push_interval_sec", default_value="0.25"),
        DeclareLaunchArgument("push_jpeg", default_value="true"),
        DeclareLaunchArgument("jpeg_quality", default_value="80"),
        DeclareLaunchArgument("heartbeat_interval_sec", default_value="30.0"),
        DeclareLaunchArgument("reconnect_backoff_initial_sec", default_value="1.0"),
        DeclareLaunchArgument("reconnect_backoff_max_sec", default_value="60.0"),
    ]


def monitor_ws_bridge_node_action() -> Node:
    '''
    :brief 构建带 IfCondition 的 monitor_ws_bridge 节点
    :return launch_ros.actions.Node
    '''
    return Node(
        package="bridge_pkg",
        executable="monitor_ws_bridge",
        name="monitor_ws_bridge",
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_monitor_ws")),
        parameters=[
            {
                "enable_monitor_ws": True,
                "backend_config_path": LaunchConfiguration("backend_config_path"),
                "ws_camera_base_url": LaunchConfiguration("ws_camera_base_url"),
                "device_id": LaunchConfiguration("monitor_override_device_id"),
                "image_topic": LaunchConfiguration("image_topic"),
                "count_topic": LaunchConfiguration("count_topic"),
                "push_interval_sec": ParameterValue(
                    LaunchConfiguration("push_interval_sec"), value_type=float
                ),
                "push_jpeg": ParameterValue(LaunchConfiguration("push_jpeg"), value_type=bool),
                "jpeg_quality": ParameterValue(
                    LaunchConfiguration("jpeg_quality"), value_type=int
                ),
                "heartbeat_interval_sec": ParameterValue(
                    LaunchConfiguration("heartbeat_interval_sec"), value_type=float
                ),
                "reconnect_backoff_initial_sec": ParameterValue(
                    LaunchConfiguration("reconnect_backoff_initial_sec"),
                    value_type=float,
                ),
                "reconnect_backoff_max_sec": ParameterValue(
                    LaunchConfiguration("reconnect_backoff_max_sec"),
                    value_type=float,
                ),
            }
        ],
    )
