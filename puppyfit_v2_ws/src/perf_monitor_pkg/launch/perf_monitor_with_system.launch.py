'''
:brief 主系统 + 性能监控 组合启动（论文实验单入口）
:desc 先启动主系统（situp_voice_full_with_cloud_monitor_and_teleop），
      随后启动 system_profiler 与 position_timer 两个监控节点。
      所有主系统参数均有默认值，用户可覆盖；监控参数也可独立覆盖。

      示例:
        ros2 launch perf_monitor_pkg perf_monitor_with_system.launch.py \
            duration_sec:=60.0 \
            sample_interval_sec:=1.0 \
            output_dir:=/home/ubuntu/perf_data/run_001

:author perf_monitor_pkg
:date 2026/06/04
:version 1.0.1
:history
    1.0.0 - 2026/06/04
        :brief 初始版本
        :desc Include 主系统 launch + system_profiler + position_timer 两监控节点。
    1.0.1 - 2026/06/05
        :brief 新增 inference_recorder 节点，补全三监控节点
        :desc 追加 inference_topic 参数声明与 inference_recorder Node，
              单入口即可同时采集 CPU/内存、找位时间、推理时延三类数据；
              run_002 实测三节点均正常启停并输出 CSV。
'''

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    bringup_share = get_package_share_directory('bringup_pkg')

    main_launch_path = os.path.join(
        bringup_share,
        'launch',
        'situp_voice_full_with_cloud_monitor_and_teleop.launch.py',
    )

    return LaunchDescription([
        # ============================================================
        # 性能监控参数
        # ============================================================
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

        # ============================================================
        # 主系统 launch（所有参数使用其自身的默认值）
        # 如需覆盖主系统参数，直接在命令行传入即可，
        # 例如 search_timeout_sec:=30.0 duration_sec:=120
        # ============================================================
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(main_launch_path),
        ),

        # ============================================================
        # system_profiler 节点
        # ============================================================
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

        # ============================================================
        # position_timer 节点
        # ============================================================
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

        # ============================================================
        # inference_recorder 节点（单帧推理时延）
        # ============================================================
        DeclareLaunchArgument(
            'inference_topic',
            default_value='pose_inference_ms',
            description='推理时延话题（inference_recorder 监听）',
        ),
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
