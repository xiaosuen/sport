'''
:brief 供 mqtt_telemetry*.launch.py 挂载监控 WebSocket 节点
:desc 声明已由 mqtt_telemetry_declare_launch_arguments() 合并 monitor_ws_declare_launch_arguments()，此处仅追加 Node。

:author slt
:date 2026/04/02
:version 1.0.1
:history
    1.0.1 - 2026/04/02
        :brief 模块迁至 bridge_pkg.monitor.launch_include
    1.0.0 - 2026/04/02
        :brief 初始版本
'''

from bridge_pkg.monitor.launch_common import monitor_ws_bridge_node_action


def monitor_ws_declare_and_include() -> list:
    '''
    :brief 返回仅含 monitor_ws 节点的动作列表
    :return 供 LaunchDescription 展开的 list
    '''
    return [monitor_ws_bridge_node_action()]
