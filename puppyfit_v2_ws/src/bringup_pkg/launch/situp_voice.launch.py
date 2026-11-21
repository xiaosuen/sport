'''
:brief 仰卧起坐语音助手一站式启动（v2）
:desc 姿态检测 + 计数 + Web、ASR、定时器（等待 timer/start）、计数 TTS、运动助手编排；
      可选 enable_session_record 将 /pose_image 经 ffmpeg（默认 libx264，可 session_video_encoder）写入 <ws>/record_video/。

:author slt
:date 2026/04/01
:version 1.3.1
:history
    1.3.1 - 2026/04/01
        :brief 默认 record_video 目录：按 install/src 路径正确解析工作空间根（不再误用 install/bringup_pkg）
    1.3.0 - 2026/04/01
        :brief 会话录像注入 video_encoder；launch 参数 session_video_encoder；
    1.2.0 - 2026/03/31
        :brief 可选会话录像：session_record_msgs + video_record_pkg；OpaqueFunction 注入话题与输出目录
    1.1.0 - 2026/03/31
        :brief counting_tts 先于 voice_asr；启用唤醒问候 + tts/done 与 voice_asr 对齐
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充 launch 模块注释
'''

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _workspace_root_from_this_launch() -> Path:
    '''
    :brief 从本 launch 文件路径推断 colcon 工作空间根目录
    :desc 若位于 install/<pkg>/share/...，则取 install 的父目录；若在 src 树下则取含 src 子目录的祖先。
         避免误用 parents[3] 得到 install/bringup_pkg 等非工作空间根路径。
    :return 工作空间根 Path
    '''
    here = Path(__file__).resolve()
    parts = here.parts
    if "install" in parts:
        i = parts.index("install")
        return Path(*parts[:i])
    for ancestor in here.parents:
        if (ancestor / "src").is_dir():
            return ancestor
    return here.parents[3]


def _opaque_setup(context, *args, **kwargs):
    '''
    :brief 按 launch 配置组装节点列表并注入会话录像相关参数
    :desc 解析 enable_session_record、record_output_dir；为 counting_tts、exercise_assistant 注入 session 话题；
          启用录像时追加 session_video_record，并传入 video_encoder 等。
    :param context: launch OpaqueFunction 上下文，用于 perform LaunchConfiguration
    :return 由 Node / IncludeLaunchDescription 组成的 actions 列表
    '''
    pkg_engine = get_package_share_directory("exercise_engine_pkg")
    situp_launch = os.path.join(pkg_engine, "launch", "situp_counter.launch.py")

    enable_raw = LaunchConfiguration("enable_session_record").perform(context).lower().strip()
    enable = enable_raw in ("true", "1", "yes")

    record_dir = LaunchConfiguration("record_output_dir").perform(context).strip()
    if not record_dir:
        record_dir = str(_workspace_root_from_this_launch() / "record_video")
    os.makedirs(record_dir, exist_ok=True)

    start_topic = "session/record_start" if enable else ""
    stop_topic = "session/record_stop" if enable else ""

    actions = [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(situp_launch),
            launch_arguments=[
                ("start_stopped", "true"),
                ("backend_config_path", LaunchConfiguration("backend_config_path")),
                ("use_backend_config", LaunchConfiguration("use_backend_config")),
            ],
        ),
        Node(
            package="voice_pkg",
            executable="counting_tts",
            name="counting_tts",
            output="screen",
            parameters=[{
                "count_topic": "situp_count",
                "exercise_name": "仰卧起坐",
                "phrase_start": "仰卧起坐，开始计数",
                "phrase_end": "计时结束",
                "speak_topic": "tts/speak",
                "start_spoken_notify_topic": "situp/ws_start",
                "tts_done_topic": "tts/done",
                "session_record_start_topic": start_topic,
                "session_record_stop_topic": stop_topic,
            }],
        ),
        Node(
            package="voice_pkg",
            executable="voice_asr",
            name="voice_asr",
            output="screen",
            parameters=[{
                "wakeup_greeting": LaunchConfiguration("wakeup_greeting"),
                "greeting_speak_topic": "tts/speak",
                "wait_for_tts_done": True,
                "tts_done_topic": "tts/done",
                "tts_done_timeout_sec": LaunchConfiguration("tts_done_timeout_sec"),
            }],
        ),
        Node(
            package="timer_interrupt",
            executable="timer",
            name="timer_interrupt",
            output="screen",
            parameters=[{
                "duration_sec": LaunchConfiguration("duration_sec"),
                "control_topic": "situp_control",
                "exercise_name": "仰卧起坐",
                "start_on_launch": False,
            }],
        ),
        Node(
            package="task_manager_pkg",
            executable="exercise_assistant",
            name="exercise_assistant_node",
            output="screen",
            parameters=[{
                "asr_topic": "asr/text",
                "count_topic": "situp_count",
                "tts_speak_topic": "tts/speak",
                "timer_start_topic": "timer/start",
                "control_topic": "situp_control",
                "phrase_ack": "收到，正在检测人体关节点",
                "session_record_start_topic": start_topic,
            }],
        ),
    ]

    if enable:
        actions.append(
            Node(
                package="video_record_pkg",
                executable="session_video_record",
                name="session_video_record",
                output="screen",
                parameters=[{
                    "record_start_topic": start_topic,
                    "record_stop_topic": stop_topic,
                    "image_topic": "/pose_image",
                    "output_dir": record_dir,
                    "fps": 20.0,
                    "file_prefix": "situp",
                    "video_encoder": LaunchConfiguration("session_video_encoder"),
                }],
            )
        )

    return actions


def generate_launch_description():
    '''
    :brief 声明 launch 参数并注册 OpaqueFunction 生成完整描述
    :return LaunchDescription 实例
    '''
    return LaunchDescription([
        DeclareLaunchArgument(
            "duration_sec",
            default_value="60",
            description="检测到人体并开始计数后启动的定时时长（秒）",
        ),
        DeclareLaunchArgument(
            "backend_config_path",
            default_value="/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json",
            description="后端配置文件路径（相对工作空间或绝对路径）",
        ),
        DeclareLaunchArgument(
            "use_backend_config",
            default_value="false",
            description="false 时不加载后端配置，Web 看板可启动（无需 PUPPY_DEVICE_USER）；需云端上报时改为 true 并配置环境变量",
        ),
        DeclareLaunchArgument(
            "wakeup_greeting",
            default_value="我在，有什么可以帮到您",
            description="串口/话题唤醒后先发至 tts/speak；设为空字符串可关闭",
        ),
        DeclareLaunchArgument(
            "tts_done_timeout_sec",
            default_value="12.0",
            description="voice_asr 等待 tts/done 的超时（秒）",
        ),
        DeclareLaunchArgument(
            "enable_session_record",
            default_value="false",
            description="true 时启用会话录像节点，并将 session 话题注入 assistant/counting_tts",
        ),
        DeclareLaunchArgument(
            "record_output_dir",
            default_value="",
            description="录像目录；空则使用工作空间根下 record_video/（与 src 同级）",
        ),
        DeclareLaunchArgument(
            "session_video_encoder",
            default_value="libx264",
            description="会话录像 ffmpeg -c:v；默认可靠软件编码。树莓派 V4L2 可用时可改为 h264_v4l2m2m",
        ),
        OpaqueFunction(function=_opaque_setup),
    ])
