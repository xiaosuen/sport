'''
:brief 启动 puppy_control 节点
:desc 注册 joint_state 相关参数并启动 puppy 可执行文件。

:author ubuntu
:date 2026/03/30
:version 1.2.0
:history
    1.2.0 - 2026/03/30
        :brief 增加 startup_use_servo_batch、startup_read_servo_positions 与节点默认值一致（默认关闭批量与回读）
    1.1.0 - 2026/03/30
        :brief 传入 startup_stance_servo_time_ms（默认 3000），与 puppy_control 启动同步到位策略一致
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 单节点 puppy_control。
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        Node(
            package='puppy_control',
            executable='puppy_control',
            name='puppy',
            output='screen',
            parameters=[
                {'joint_state_pub_topic': 'true'},
                {'joint_state_controller_pub_topic': 'true'},
                # 批量同步：true 时 startup_stance_servo_time_ms 为整段插值时长(ms)；false（默认）为逐路下发，遥控最稳
                {'startup_use_servo_batch': False},
                {'startup_stance_servo_time_ms': 3000},
                {'startup_read_servo_positions': False},
            ],
        ),
    ]
    )
