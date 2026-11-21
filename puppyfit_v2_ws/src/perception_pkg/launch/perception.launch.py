'''
:brief perception_pkg 启动文件
:desc 启动 human_pose_node；可通过 launch 参数覆盖常用 ROS 参数。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.0 - 2026/03/28
        :brief 初始 launch
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 补充 :history
'''

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    '''
    :brief 构建 LaunchDescription
    :desc 声明图像话题等参数并启动 human_pose_node。
    :return LaunchDescription 实例
    '''
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'image_topic',
                default_value='',
                description=(
                    '为空：human_pose_node 使用 cv2.VideoCapture(camera_id) 直连本机摄像头（默认 /dev/video0 对应 camera_id=0）。'
                    '非空：订阅该图像话题（例如与 v4l2_camera 等节点配合）。'
                ),
            ),
            DeclareLaunchArgument('camera_id', default_value='0'),
            DeclareLaunchArgument(
                'camera_frame_id',
                default_value='camera_optical_frame',
            ),
            DeclareLaunchArgument('publish_rate', default_value='30.0'),
            DeclareLaunchArgument('publish_debug_image', default_value='false'),
            DeclareLaunchArgument(
                'show_debug_window',
                default_value='false',
                description=(
                    'true：OpenCV 弹窗显示骨架（需本机桌面或 DISPLAY）；'
                    'false：仅用话题 /perception/debug_image（配合 rqt_image_view 等）'
                ),
            ),
            Node(
                package='perception_pkg',
                executable='human_pose_node',
                name='human_pose_node',
                output='screen',
                parameters=[
                    {
                        'image_topic': LaunchConfiguration('image_topic'),
                        'camera_id': LaunchConfiguration('camera_id'),
                        'camera_frame_id': LaunchConfiguration('camera_frame_id'),
                        'publish_rate': LaunchConfiguration('publish_rate'),
                        'publish_debug_image': LaunchConfiguration('publish_debug_image'),
                        'show_debug_window': LaunchConfiguration('show_debug_window'),
                    }
                ],
            ),
        ]
    )
