'''
:brief 今日作业语音桥接启动文件
:desc 启动 homework_voice_bridge 节点，订阅 asr/text 并在关键词命中后调用后端 HTTP 接口。

:author slt
:date 2026/04/29
:version 1.0.0
:history
    1.0.0 - 2026/04/29
        :brief 初始版本
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from bridge_pkg.backend_config_default import DEFAULT_BACKEND_CONFIG_PATH


def generate_launch_description() -> LaunchDescription:
    '''构建 LaunchDescription。'''
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'backend_config_path',
                default_value=DEFAULT_BACKEND_CONFIG_PATH,
                description='backend_config.json 路径',
            ),
            DeclareLaunchArgument('enabled', default_value='true'),
            DeclareLaunchArgument('api_path_key', default_value='homework_query'),
            DeclareLaunchArgument('device_id', default_value=''),
            DeclareLaunchArgument('asr_topic', default_value='asr/text'),
            DeclareLaunchArgument('tts_speak_topic', default_value='tts/speak'),
            DeclareLaunchArgument('cooldown_sec', default_value='3.0'),
            DeclareLaunchArgument('http_timeout_sec', default_value='8.0'),
            Node(
                package='bridge_pkg',
                executable='homework_voice_bridge',
                name='homework_voice_bridge',
                output='screen',
                parameters=[
                    {
                        'enabled': ParameterValue(LaunchConfiguration('enabled'), value_type=bool),
                        'backend_config_path': LaunchConfiguration('backend_config_path'),
                        'api_path_key': LaunchConfiguration('api_path_key'),
                        'device_id': LaunchConfiguration('device_id'),
                        'asr_topic': LaunchConfiguration('asr_topic'),
                        'tts_speak_topic': LaunchConfiguration('tts_speak_topic'),
                        'cooldown_sec': ParameterValue(
                            LaunchConfiguration('cooldown_sec'),
                            value_type=float,
                        ),
                        'http_timeout_sec': ParameterValue(
                            LaunchConfiguration('http_timeout_sec'),
                            value_type=float,
                        ),
                    }
                ],
            ),
        ]
    )