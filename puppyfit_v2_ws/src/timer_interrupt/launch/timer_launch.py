'''
:brief 通用定时中断 launch
:desc 仅启动 timer 节点，通过参数 control_topic / duration_sec / exercise_name 适配不同运动。
      仰卧起坐用 situp_control，俯卧撑用 pushup_control，其它运动同理。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 声明定时与 control_topic 参数并启动 timer 可执行文件。
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        DeclareLaunchArgument(
            'duration_sec',
            default_value='60',
            description='定时时长（秒），到时向 control_topic 发送 stop',
        ),
        DeclareLaunchArgument(
            'control_topic',
            default_value='situp_control',
            description='控制话题名，计数节点订阅此话题接收 stop/start（如 situp_control、pushup_control）',
        ),
        DeclareLaunchArgument(
            'exercise_name',
            default_value='仰卧起坐',
            description='运动名称，仅用于日志展示（如 仰卧起坐、俯卧撑）',
        ),
        Node(
            package='timer_interrupt',
            executable='timer',
            name='timer_interrupt',
            output='screen',
            parameters=[{
                'duration_sec': LaunchConfiguration('duration_sec'),
                'control_topic': LaunchConfiguration('control_topic'),
                'exercise_name': LaunchConfiguration('exercise_name'),
            }],
        ),
    ])
