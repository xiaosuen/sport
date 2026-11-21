'''
:brief 仰卧起坐计数启动文件
:desc 同时启动姿态检测节点、计数节点与 Web 展示等（见文件内 Node 列表）。

:author slt&zxh
:date 2026/03/03
:version 1.0.3
:history
    1.0.0 - 2026/03/03
        :brief 初始版本
    1.0.1 - 2026/03/15
        :brief 增加语音助手模式：启动即停止，等用户说「开始」后收 start 再计数
    1.0.2 - 2026/03/24
        :brief 增加后端配置加载：启用后会校验环境变量，缺失即启动失败
    1.0.3 - 2026/03/29
        :brief 按 doc/注释.md 统一 launch 注释格式
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 生成启动描述
    :desc 声明启动参数并注册 pose_detector、situp_counter、web_dashboard 等节点。
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        DeclareLaunchArgument(
            "start_stopped",
            default_value="false",
            description="若为 true，计数节点启动时处于停止状态，需 situp_control 发 start 后才计数（用于语音助手流程）",
        ),
        DeclareLaunchArgument(
            "use_backend_config",
            default_value="true",
            description="是否启用后端配置加载（启用后会校验环境变量，缺失即启动失败）",
        ),
        DeclareLaunchArgument(
            "backend_config_path",
            default_value="/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json",
            description="后端配置文件路径（建议统一使用工作空间内配置）",
        ),
        DeclareLaunchArgument(
            'enable_video_overlay',
            default_value='true',
            description='true 时启用视频叠字节点，输出 overlay 图像供 dashboard 与录像使用',
        ),
        DeclareLaunchArgument(
            'raw_image_topic',
            default_value='/pose_image',
            description='pose_detector 原始图像输出话题',
        ),
        DeclareLaunchArgument(
            'overlay_image_topic',
            default_value='/pose_image_overlay',
            description='video_overlay 输出图像话题',
        ),
        DeclareLaunchArgument(
            'dashboard_video_topic',
            default_value='/pose_image_overlay',
            description='web_dashboard 内置视频流订阅话题',
        ),
        DeclareLaunchArgument(
            'stats_topic',
            default_value='/pose_video_stats',
            description='视频 FPS 状态话题',
        ),
        # 姿态检测节点
        Node(
            package='exercise_engine_pkg',
            executable='pose_detector',
            name='pose_detector',
            output='screen',
            parameters=[{
                'camera_id': 0,
                'publish_rate': 30.0,
                'min_detection_confidence': 0.5,
                'min_tracking_confidence': 0.5,
                'stats_topic': LaunchConfiguration('stats_topic'),
                'source_image_topic': LaunchConfiguration('raw_image_topic'),
            }]
        ),
        Node(
            package='exercise_engine_pkg',
            executable='video_overlay',
            name='video_overlay',
            output='screen',
            condition=IfCondition(LaunchConfiguration('enable_video_overlay')),
            parameters=[{
                'input_image_topic': LaunchConfiguration('raw_image_topic'),
                'output_image_topic': LaunchConfiguration('overlay_image_topic'),
                'count_topic': '/situp_count',
                'stats_topic': LaunchConfiguration('stats_topic'),
                'show_fps': True,
                'show_state': True,
                'show_count': True,
            }],
        ),
        # 仰卧起坐计数节点
        Node(
            package='exercise_engine_pkg',
            executable='situp_counter',
            name='situp_counter',
            output='screen',
            parameters=[{
                'auto_reset': True,
                'reset_timeout': 5.0,
                'start_stopped': LaunchConfiguration('start_stopped', default='false'),
            }]
        ),
        # Web 展示节点（浏览器查看计数）
        Node(
            package='exercise_engine_pkg',
            executable='web_dashboard',
            name='situp_web_dashboard',
            output='screen',
            parameters=[{
                'host': '0.0.0.0',
                'port': 8090,
                # 内置视频流：本节点订阅 /pose_image 并对外提供 /stream，无需 v4l2_camera 与 web_video_server
                'serve_video_stream': True,
                'video_topic': LaunchConfiguration('dashboard_video_topic'),
                'video_stream_url': '',
                'video_viewer_url': '',
                'video_stream_port': 8081,
                'video_stream_topic': LaunchConfiguration('dashboard_video_topic'),
                'video_stream_host': '',
                'stats_topic': LaunchConfiguration('stats_topic'),
                # 后端配置统一入口（WS地址和设备ID从配置读取）
                'use_backend_config': LaunchConfiguration('use_backend_config', default='true'),
                'backend_config_path': LaunchConfiguration(
                    'backend_config_path',
                    default='/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json',
                ),
                # 语音助手流程下（start_stopped=true）等待 situp_control start 后再开始上传
                'ws_wait_for_control_start': LaunchConfiguration('start_stopped', default='false'),
                # 若配置该触发话题，则将「开始上传」严格延后到收到通知（默认语音助手会在播报开始计数后发）
                'ws_start_trigger_topic': 'situp/ws_start',
            }]
        ),
    ])
