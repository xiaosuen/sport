'''
:brief 训练会话桥接启动文件
:desc 启动 training_session_bridge 节点，处理 MQTT 控制命令与训练会话 HTTP 接口闭环。

:author slt
:date 2026/04/13
:version 1.0.3
:history
    1.0.3 - 2026/04/27
        :brief 新增录像联动参数透传
        :desc 增加 record_enabled / record_start_topic / record_stop_topic，供 training_session_bridge
              在云端训练开始/结束时发布录像控制话题。
    1.0.2 - 2026/04/27
        :brief 新增自动找位联动参数透传
        :desc 增加 auto_position_control_topic / auto_position_status_topic /
              wait_auto_position_ready / auto_position_ready_timeout_sec，
              支持 start_training 先找位再计数的桥接策略。
    1.0.1 - 2026/04/18
        :brief launch 参数 ts_* 前缀：避免与 mqtt_telemetry / monitor_ws 同文件组合时 broker_port 等同名冲突
    1.0.0 - 2026/04/13
        :brief 初始版本
        :desc 启动 training_session_bridge 节点，处理 MQTT 控制命令与训练会话 HTTP 接口闭环。
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def generate_launch_description() -> LaunchDescription:
    '''
    :brief 构建 LaunchDescription
    :return LaunchDescription 实例
    '''
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'ts_backend_config_path',
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description='backend_config.json 路径（ts_ 前缀避免与 mqtt_telemetry 等同名）',
            ),
            DeclareLaunchArgument('http_base_url', default_value=''),
            DeclareLaunchArgument('ts_device_id', default_value=''),
            DeclareLaunchArgument('ts_broker_host', default_value=''),
            DeclareLaunchArgument('ts_broker_port', default_value=''),
            DeclareLaunchArgument('ts_use_tls', default_value=''),
            DeclareLaunchArgument('mqtt_username', default_value=''),
            DeclareLaunchArgument('mqtt_password', default_value=''),
            DeclareLaunchArgument('mqtt_client_id', default_value=''),
            DeclareLaunchArgument('mqtt_qos', default_value='1'),
            DeclareLaunchArgument(
                'control_topic_template',
                default_value='puppy/control/{device_id}',
            ),
            DeclareLaunchArgument(
                'data_topic_template',
                default_value='puppy/data/{device_id}',
            ),
            DeclareLaunchArgument(
                'event_topic_template',
                default_value='puppy/event/{device_id}',
            ),
            DeclareLaunchArgument('control_topic', default_value='situp_control'),
            DeclareLaunchArgument(
                'ts_count_topic',
                default_value='situp_count',
                description='计数话题（ts_ 前缀避免与 monitor_ws 的 count_topic 冲突）',
            ),
            DeclareLaunchArgument(
                'auto_position_control_topic',
                default_value='auto_position/control',
            ),
            DeclareLaunchArgument(
                'auto_position_status_topic',
                default_value='auto_position/status',
            ),
            DeclareLaunchArgument('wait_auto_position_ready', default_value='true'),
            DeclareLaunchArgument('auto_position_ready_timeout_sec', default_value='60.0'),
            DeclareLaunchArgument('record_enabled', default_value='true'),
            DeclareLaunchArgument('record_start_topic', default_value='session/record_start'),
            DeclareLaunchArgument('record_stop_topic', default_value='session/record_stop'),
            DeclareLaunchArgument('count_report_interval_sec', default_value='1.0'),
            DeclareLaunchArgument('complete_on_target', default_value='true'),
            Node(
                package='bridge_pkg',
                executable='training_session_bridge',
                name='training_session_bridge',
                output='screen',
                parameters=[
                    {
                        'backend_config_path': LaunchConfiguration('ts_backend_config_path'),
                        'http_base_url': LaunchConfiguration('http_base_url'),
                        'device_id': LaunchConfiguration('ts_device_id'),
                        'broker_host': LaunchConfiguration('ts_broker_host'),
                        'broker_port': LaunchConfiguration('ts_broker_port'),
                        'use_tls': LaunchConfiguration('ts_use_tls'),
                        'mqtt_username': LaunchConfiguration('mqtt_username'),
                        'mqtt_password': LaunchConfiguration('mqtt_password'),
                        'mqtt_client_id': LaunchConfiguration('mqtt_client_id'),
                        'mqtt_qos': ParameterValue(LaunchConfiguration('mqtt_qos'), value_type=int),
                        'control_topic_template': LaunchConfiguration('control_topic_template'),
                        'data_topic_template': LaunchConfiguration('data_topic_template'),
                        'event_topic_template': LaunchConfiguration('event_topic_template'),
                        'control_topic': LaunchConfiguration('control_topic'),
                        'count_topic': LaunchConfiguration('ts_count_topic'),
                        'auto_position_control_topic': LaunchConfiguration('auto_position_control_topic'),
                        'auto_position_status_topic': LaunchConfiguration('auto_position_status_topic'),
                        'wait_auto_position_ready': ParameterValue(
                            LaunchConfiguration('wait_auto_position_ready'),
                            value_type=bool,
                        ),
                        'auto_position_ready_timeout_sec': ParameterValue(
                            LaunchConfiguration('auto_position_ready_timeout_sec'),
                            value_type=float,
                        ),
                        'record_enabled': ParameterValue(
                            LaunchConfiguration('record_enabled'),
                            value_type=bool,
                        ),
                        'record_start_topic': LaunchConfiguration('record_start_topic'),
                        'record_stop_topic': LaunchConfiguration('record_stop_topic'),
                        'count_report_interval_sec': ParameterValue(
                            LaunchConfiguration('count_report_interval_sec'),
                            value_type=float,
                        ),
                        'complete_on_target': ParameterValue(
                            LaunchConfiguration('complete_on_target'),
                            value_type=bool,
                        ),
                    }
                ],
            ),
        ]
    )
