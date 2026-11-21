'''
:brief 单独启动自动找位节点
:desc 需另有节点发布 HumanPose（例如 perception_pkg/human_pose_node 或自建桥接）。
      运动默认使用 /cmd_vel_nav，以便小速度比例控制；机体俯仰使用 /puppy_control/pose。

:author slt
:date 2026/04/07
:version 1.0.0
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'human_pose_topic',
            default_value='/perception/human_pose',
            description='HumanPose 输入话题',
        ),
        DeclareLaunchArgument(
            'use_pose_scan',
            default_value='true',
            description='是否发布 puppy_control Pose 做俯仰扫描（无四足控制栈时可设 false）',
        ),
        DeclareLaunchArgument(
            'autostart',
            default_value='false',
            description='true：启动即找位；false：仅响应 auto_position/control=start',
        ),
        DeclareLaunchArgument(
            'search_timeout_sec',
            default_value='60.0',
            description='SEARCHING 最长时间（秒），<=0 表示不超时；超时发布 failed|timeout',
        ),
        DeclareLaunchArgument(
            'search_angular_z',
            default_value='0.28',
            description='SEARCHING 角速度 z（rad/s）',
        ),
        DeclareLaunchArgument(
            'search_yaw_segment_sec',
            default_value='2.0',
            description='每段同向旋转持续秒数',
        ),
        DeclareLaunchArgument(
            'max_angular_z',
            default_value='0.35',
            description='对中阶段角速度限幅（rad/s）',
        ),
        Node(
            package='exercise_engine_pkg',
            executable='auto_position',
            name='auto_position',
            output='screen',
            parameters=[{
                'human_pose_topic': LaunchConfiguration('human_pose_topic'),
                'use_pose_scan': LaunchConfiguration('use_pose_scan'),
                'twist_topic': '/cmd_vel_nav',
                'pose_topic': '/puppy_control/pose',
                'autostart': ParameterValue(LaunchConfiguration('autostart'), value_type=bool),
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
