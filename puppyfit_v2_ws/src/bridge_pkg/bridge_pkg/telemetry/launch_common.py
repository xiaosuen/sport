'''
:brief mqtt_telemetry 共用：DeclareLaunchArgument 列表与 telemetry_bridge Node
:desc 供 launch 文件引用，避免重复与 Include 双份 declare。
     合并监控 WebSocket 相关 declare，与 bridge_pkg.monitor.launch_common 衔接。

:author slt
:date 2026/04/02
:version 1.3.2
:history
    1.3.3 - 2026/04/18
        :brief mqtt_telemetry_declare_launch_arguments 可传 declare_backend_config_path=False，
              供与已声明 backend_config_path 的上层 launch（如 situp_voice_full）组合时去重
    1.3.2 - 2026/04/02
        :brief mqtt_telemetry_declare_launch_arguments 可传 enable_monitor_ws_default
    1.3.1 - 2026/04/02
        :brief backend_config_path 默认使用 backend_config_default（本机 v2_ws 绝对路径）
    1.3.0 - 2026/04/02
        :brief 模块迁至 bridge_pkg.telemetry.launch_common
    1.2.0 - 2026/04/02
        :brief 默认 enable_http_heartbeat=true、http_register_on_start=false（与 telemetry.node 一致）
    1.1.0 - 2026/04/02
        :brief 合并 monitor_ws_declare_launch_arguments，供遥测与监控同启
    1.0.0 - 2026/04/02
        :brief 从 mqtt_telemetry.launch 抽取共用 Node 与参数（现位于 bridge_pkg.telemetry.launch_common）
'''

from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH
from bridge_pkg.monitor.launch_common import monitor_ws_declare_launch_arguments


def mqtt_telemetry_declare_launch_arguments(
    *,
    enable_monitor_ws_default: str = "false",
    declare_backend_config_path: bool = True,
) -> list:
    '''
    :brief 与 mqtt 遥测及可选监控 WS 相关的全部 launch 参数声明
    :param enable_monitor_ws_default: 传给 monitor_ws_declare_launch_arguments
    :param declare_backend_config_path: False 时不声明 backend_config_path（由上层 launch 统一声明）
    :return DeclareLaunchArgument 列表
    '''
    backend_cfg = []
    if declare_backend_config_path:
        backend_cfg = [
            DeclareLaunchArgument(
                'backend_config_path',
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description='backend_config.json 路径；可改为空字符串以仅依赖自动查找 / PUPPY_BACKEND_CONFIG',
            ),
        ]
    return [
        DeclareLaunchArgument('device_id', default_value='puppy_001'),
        DeclareLaunchArgument('broker_host', default_value='122.51.12.83'),
        DeclareLaunchArgument('broker_port', default_value='1883'),
        DeclareLaunchArgument('use_tls', default_value='false'),
        DeclareLaunchArgument(
            'mqtt_topic_template',
            default_value='puppy/data/{device_id}',
            description='须与后端订阅一致，默认 puppy/data/{device_id}',
        ),
        DeclareLaunchArgument(
            'voltage_topic',
            default_value='',
            description='Float32 电压话题（伏）；空则仅用 battery_mv_topic',
        ),
        DeclareLaunchArgument(
            'battery_mv_topic',
            default_value='/ros_robot_controller/battery',
            description='UInt16 毫伏（如控制板 battery）；空则不订阅',
        ),
        DeclareLaunchArgument(
            'battery_v_min',
            default_value='6.4',
            description='PuppyPi：0% 对应电压（V）',
        ),
        DeclareLaunchArgument(
            'battery_v_max',
            default_value='8.5',
            description='PuppyPi：100% 对应电压（V）',
        ),
        DeclareLaunchArgument(
            'simulated_voltage_v',
            default_value='7.35',
            description='电压超时回退值（V），默认取 6.4–8.3 中点',
        ),
        DeclareLaunchArgument(
            'enable_http_heartbeat',
            default_value='true',
            description='是否启用 HTTP POST /api/device/status（需 PUPPY_DEVICE_* 与 PUPPY_MQTT_*）',
        ),
        DeclareLaunchArgument(
            'http_heartbeat_interval_sec',
            default_value='30.0',
            description='HTTP 设备状态上报周期（秒），最小 5',
        ),
        *backend_cfg,
        DeclareLaunchArgument(
            'http_register_on_start',
            default_value='false',
            description='启动时是否调用 POST /api/device/register（失败仅告警）',
        ),
        *monitor_ws_declare_launch_arguments(
            enable_monitor_ws_default=enable_monitor_ws_default
        ),
    ]


def mqtt_telemetry_bridge_node() -> Node:
    '''
    :brief telemetry_bridge 节点（参数全部来自 LaunchConfiguration）
    :desc MQTT 遥测与可选 HTTP 心跳，参数见 mqtt_telemetry_declare_launch_arguments。
    :return Node 实例
    '''
    return Node(
        package='bridge_pkg',
        executable='telemetry_bridge',
        name='mqtt_telemetry_bridge',
        output='screen',
        parameters=[
            {
                'device_id': LaunchConfiguration('device_id'),
                'broker_host': LaunchConfiguration('broker_host'),
                'broker_port': ParameterValue(LaunchConfiguration('broker_port'), value_type=int),
                'use_tls': ParameterValue(LaunchConfiguration('use_tls'), value_type=bool),
                'mqtt_topic_template': LaunchConfiguration('mqtt_topic_template'),
                'publish_interval_sec': 5.0,
                'voltage_topic': LaunchConfiguration('voltage_topic'),
                'battery_mv_topic': LaunchConfiguration('battery_mv_topic'),
                'battery_v_min': ParameterValue(
                    LaunchConfiguration('battery_v_min'), value_type=float
                ),
                'battery_v_max': ParameterValue(
                    LaunchConfiguration('battery_v_max'), value_type=float
                ),
                'simulated_voltage_v': ParameterValue(
                    LaunchConfiguration('simulated_voltage_v'), value_type=float
                ),
                'enable_http_heartbeat': ParameterValue(
                    LaunchConfiguration('enable_http_heartbeat'), value_type=bool
                ),
                'http_heartbeat_interval_sec': ParameterValue(
                    LaunchConfiguration('http_heartbeat_interval_sec'),
                    value_type=float,
                ),
                'backend_config_path': LaunchConfiguration('backend_config_path'),
                'http_register_on_start': ParameterValue(
                    LaunchConfiguration('http_register_on_start'), value_type=bool
                ),
            }
        ],
    )
