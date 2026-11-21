'''
:brief 延迟启动机械臂测试节点的 launch 示例
:desc 先启动 puppy_control，再通过 TimerAction 延迟启动 puppy_arm_test（若包内仍提供该可执行文件）。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

from launch import LaunchDescription
from launch.actions import ExecuteProcess, RegisterEventHandler, TimerAction
from launch.event_handlers import OnProcessStart
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc puppy_control + 延时 arm_test 节点。
    :return LaunchDescription 实例
    '''
    # Define the main control node(定义主控制节点)
    puppy_control_node = Node(
        package='puppy_control',
        executable='puppy_control',
        name='puppy',
        output='screen',
        parameters=[
            {'joint_state_pub_topic': 'true'},
            {'joint_state_controller_pub_topic': 'true'},
        ],
    )

    # Define the test node to start with a delay(定义要延迟启动的测试节点)
    arm_test_node = Node(
        package='puppy_control', 
        executable='puppy_arm_test',
        name='arm_test',
        output='screen'
    )

    delayed_arm_test = TimerAction(
        period=3.0,
        actions=[arm_test_node]
    )

    return LaunchDescription([
        puppy_control_node,
        delayed_arm_test
    ])
