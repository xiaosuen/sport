'''
:brief 启动 MQTT 遥测桥接节点
:desc 注册 broker、设备 ID、TLS、PuppyPi 电池话题（UInt16 mV）与 6.4–8.3V 电量映射等参数；
      密码请通过环境变量 PUPPY_MQTT_PASS 传入。
      参数与节点定义见 bridge_pkg.telemetry.launch_common；可选 Include 监控 WebSocket。

:author slt
:date 2026/04/01
:version 1.3.2
:history
    1.3.2 - 2026/04/02
        :brief 共用 bridge_pkg.telemetry.launch_common：HTTP 心跳默认开、启动注册默认关
    1.3.1 - 2026/04/02
        :brief Include 监控 WebSocket（monitor_ws_declare_and_include）
    1.3.0 - 2026/04/02
        :brief 抽取 telemetry.launch_common，与一键带控制板 launch 共用
    1.2.0 - 2026/04/01
        :brief 增加 HTTP 设备状态上报参数 enable_http_heartbeat、http_heartbeat_interval_sec、backend_config_path
    1.1.2 - 2026/04/01
        :brief 默认接 ros_robot_controller 电池毫伏 + PuppyPi 百分比映射；可改 voltage_topic 兼容旧 Float32
    1.0.0 - 2026/03/25
        :brief 初始版本：mqtt_telemetry.launch.py
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 统一 launch 模块注释格式
'''

from launch import LaunchDescription

from bridge_pkg.monitor.launch_include import monitor_ws_declare_and_include
from bridge_pkg.telemetry.launch_common import (
    mqtt_telemetry_bridge_node,
    mqtt_telemetry_declare_launch_arguments,
)


def generate_launch_description() -> LaunchDescription:
    '''
    :brief 构建 LaunchDescription
    :desc 遥测桥 + 可选监控 WS + MQTT/HTTP 参数。
    :return LaunchDescription 实例
    '''
    return LaunchDescription(
        [
            *mqtt_telemetry_declare_launch_arguments(),
            *monitor_ws_declare_and_include(),
            mqtt_telemetry_bridge_node(),
        ]
    )
