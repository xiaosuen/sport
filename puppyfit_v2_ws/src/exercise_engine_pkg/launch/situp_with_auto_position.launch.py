'''
:brief 仰卧起坐 + 自动找位（同一网络内话题）
:desc 启动 pose_detector、situp_counter、web_dashboard，并启动 auto_position。
      pose_detector 发布 pose_landmarks；若需 HumanPose，由 bridge 节点将 PoseLandmarks 转为
      HumanPose（见同包 human_pose_bridge_node），避免双开摄像头。

:author slt
:date 2026/04/07
:version 1.0.5
:history
    1.0.5 - 2026/04/27
        :brief 找位与视觉检出稳态化默认参数
        :desc 调整 search_angular_z/search_yaw_segment_sec 默认值；
              下调 pose_detector min_detection_confidence/min_tracking_confidence，提升 HumanPose 稳定检出率。
    1.0.4 - 2026/04/25
        :brief 透传 auto_position：search_angular_z / search_yaw_segment_sec / max_angular_z
    1.0.3 - 2026/04/11
        :brief launch 参数 search_timeout_sec 透传 auto_position（SEARCHING 阶段超时秒数）
    1.0.2 - 2026/04/08
        :brief auto_position 默认 autostart=true（与 plan 编排发 start 等价；可关）
    1.0.1 - 2026/04/08
        :brief use_backend_config 默认 false，避免未 export PUPPY_DEVICE_* 时 web_dashboard 崩溃
    1.0.0 - 2026/04/07
        :brief 初始版本
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'start_stopped',
            default_value='false',
            description='true 时计数节点等待 situp_control start',
        ),
        DeclareLaunchArgument(
            'use_backend_config',
            default_value='false',
            description='web_dashboard 是否 load_backend_config；true 需 PUPPY_DEVICE_* / PUPPY_MQTT_*',
        ),
        DeclareLaunchArgument(
            'backend_config_path',
            default_value='/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json',
            description='后端配置文件路径',
        ),
        DeclareLaunchArgument(
            'use_pose_scan',
            default_value='true',
            description='auto_position 是否下发 /puppy_control/pose',
        ),
        DeclareLaunchArgument(
            'auto_position_autostart',
            default_value='true',
            description='true：启动后立即找位；false：仅响应 auto_position/control=start（见 doc/plan/plan.md §7）',
        ),
        DeclareLaunchArgument(
            'search_timeout_sec',
            default_value='60.0',
            description='auto_position SEARCHING 最长时间（秒），<=0 不超时；超时发布 failed|timeout',
        ),
        DeclareLaunchArgument(
            'search_angular_z',
            default_value='0.18',
            description='SEARCHING 阶段 /cmd_vel_nav 的角速度 z（rad/s），建议 0.10~0.20 以提升视觉稳定检出',
        ),
        DeclareLaunchArgument(
            'search_yaw_segment_sec',
            default_value='2.5',
            description='SEARCHING 每段同向旋转持续时间（秒），可略增利于视觉稳定出框',
        ),
        DeclareLaunchArgument(
            'max_angular_z',
            default_value='0.35',
            description='对中 / 稳姿阶段角速度限幅（rad/s），与 search_angular_z 独立',
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
        Node(
            package='exercise_engine_pkg',
            executable='pose_detector',
            name='pose_detector',
            output='screen',
            parameters=[{
                'camera_id': 0,
                'publish_rate': 30.0,
                'min_detection_confidence': 0.55,
                'min_tracking_confidence': 0.45,
                'stats_topic': LaunchConfiguration('stats_topic'),
                'source_image_topic': LaunchConfiguration('raw_image_topic'),
            }],
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
        Node(
            package='exercise_engine_pkg',
            executable='situp_counter',
            name='situp_counter',
            output='screen',
            parameters=[{
                'auto_reset': True,
                'reset_timeout': 5.0,
                'start_stopped': LaunchConfiguration('start_stopped'),
            }],
        ),
        Node(
            package='exercise_engine_pkg',
            executable='web_dashboard',
            name='situp_web_dashboard',
            output='screen',
            parameters=[{
                'host': '0.0.0.0',
                'port': 8090,
                'serve_video_stream': True,
                'video_topic': LaunchConfiguration('dashboard_video_topic'),
                'video_stream_port': 8081,
                'video_stream_topic': LaunchConfiguration('dashboard_video_topic'),
                'stats_topic': LaunchConfiguration('stats_topic'),
                'use_backend_config': LaunchConfiguration('use_backend_config'),
                'backend_config_path': LaunchConfiguration('backend_config_path'),
                'ws_wait_for_control_start': LaunchConfiguration('start_stopped'),
                'ws_start_trigger_topic': 'situp/ws_start',
            }],
        ),
        Node(
            package='exercise_engine_pkg',
            executable='human_pose_bridge',
            name='human_pose_bridge',
            output='screen',
        ),
        Node(
            package='exercise_engine_pkg',
            executable='auto_position',
            name='auto_position',
            output='screen',
            parameters=[{
                'human_pose_topic': '/perception/human_pose',
                'use_pose_scan': LaunchConfiguration('use_pose_scan'),
                'twist_topic': '/cmd_vel_nav',
                'pose_topic': '/puppy_control/pose',
                'autostart': ParameterValue(
                    LaunchConfiguration('auto_position_autostart'),
                    value_type=bool,
                ),
                'search_timeout_sec': ParameterValue(
                    LaunchConfiguration('search_timeout_sec'),
                    value_type=float,
                ),
                'search_angular_z': ParameterValue(
                    LaunchConfiguration('search_angular_z'),
                    value_type=float,
                ),
                'search_yaw_segment_sec': ParameterValue(
                    LaunchConfiguration('search_yaw_segment_sec'),
                    value_type=float,
                ),
                'max_angular_z': ParameterValue(
                    LaunchConfiguration('max_angular_z'),
                    value_type=float,
                ),
            }],
        ),
    ])
