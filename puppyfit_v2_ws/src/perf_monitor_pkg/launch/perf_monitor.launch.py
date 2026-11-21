'''
:brief 性能监控独立启动
:desc 仅启动 system_profiler 与 position_timer 两个监控节点。
      可在另一终端中与主系统并行运行，互不干扰。

      节点动态发现 ROS2 节点列表，因此可在主系统启动前或后运行。

:author perf_monitor_pkg
:date 2026/06/04
:version 1.0.1
:history
    1.0.0 - 2026/06/04
        :brief 初始版本
        :desc 仅 system_profiler + position_timer 两监控节点，独立于主系统运行。
    1.0.1 - 2026/06/05
        :brief 新增 inference_recorder 节点与 inference_topic 参数
        :desc 与 perf_monitor_with_system 保持一致的三监控节点集合，
              可独立或并行使用。
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        # ---- 通用参数 ----
        DeclareLaunchArgument(
            'output_dir',
            default_value='',
            description='CSV 输出目录；空则使用 ~/perf_logs',
        ),
        DeclareLaunchArgument(
            'status_topic',
            default_value='auto_position/status',
            description='找位状态话题（position_timer 监听）',
        ),

        # ---- system_profiler 参数 ----
        DeclareLaunchArgument(
            'sample_interval_sec',
            default_value='1.0',
            description='CPU/内存采样间隔（秒）',
        ),
        DeclareLaunchArgument(
            'duration_sec',
            default_value='0.0',
            description='采样总时长（秒），0=直到 Ctrl+C',
        ),

        # ---- system_profiler 节点 ----
        Node(
            package='perf_monitor_pkg',
            executable='system_profiler',
            name='system_profiler',
            output='screen',
            parameters=[{
                'sample_interval_sec': LaunchConfiguration('sample_interval_sec'),
                'duration_sec': LaunchConfiguration('duration_sec'),
                'output_dir': LaunchConfiguration('output_dir'),
            }],
        ),

        # ---- position_timer 节点 ----
        Node(
            package='perf_monitor_pkg',
            executable='position_timer',
            name='position_timer',
            output='screen',
            parameters=[{
                'status_topic': LaunchConfiguration('status_topic'),
                'output_dir': LaunchConfiguration('output_dir'),
            }],
        ),

        # ---- inference_recorder 参数 ----
        DeclareLaunchArgument(
            'inference_topic',
            default_value='pose_inference_ms',
            description='推理时延话题（inference_recorder 监听）',
        ),

        # ---- inference_recorder 节点 ----
        Node(
            package='perf_monitor_pkg',
            executable='inference_recorder',
            name='inference_recorder',
            output='screen',
            parameters=[{
                'inference_topic': LaunchConfiguration('inference_topic'),
                'duration_sec': LaunchConfiguration('duration_sec'),
                'output_dir': LaunchConfiguration('output_dir'),
            }],
        ),
    ])
