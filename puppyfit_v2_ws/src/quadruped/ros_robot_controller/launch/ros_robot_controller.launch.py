'''
:brief 启动 ros_robot_controller 节点
:desc 声明 imu_frame 参数并启动控制板桥接节点，用于将 IMU 等消息的 frame_id 与 URDF/TF 对齐。

:author Aiden
:date 2023/08/28
:version 1.0.1
:history
    1.0.0 - 2023/08/28
        :brief 初始 launch 描述
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 统一 launch 注释格式
'''

from launch_ros.actions import Node
from launch import LaunchDescription, LaunchService
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 注册 imu_frame 启动参数与 ros_robot_controller 可执行节点。
    :return LaunchDescription 实例
    '''
    imu_frame = LaunchConfiguration('imu_frame', default='imu_link')
    imu_frame_arg = DeclareLaunchArgument('imu_frame', default_value=imu_frame)

    ros_robot_controller_node = Node(
        package='ros_robot_controller',
        executable='ros_robot_controller',
        output='screen',
        parameters=[{'imu_frame': imu_frame}]
    )

    return LaunchDescription([
        imu_frame_arg,
        ros_robot_controller_node
    ])


if __name__ == '__main__':
    # 独立运行 launch 文件时直接启动 LaunchService
    ld = generate_launch_description()

    ls = LaunchService()
    ls.include_launch_description(ld)
    ls.run()
