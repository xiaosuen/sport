'''
:brief 语音唤醒仰卧起坐全流程（找位 + 计数 + 成绩口播）
:desc Include situp_with_auto_position；可选 Include puppy_motion_stack（真机底盘/姿态）；
      counting_tts + phrase_end_notify → situp_result_tts 播成绩；situp_voice_orchestrator 编排。
      默认流程：唤醒问候 TTS → 用户说含关键词语句 → 确认「收到，正在调整位置」→ auto_position 找位
      （失败「没有找到合适的位置」；就绪后计数链播报「仰卧起坐开始计数」）→ 定时结束一句
      「计时结束，您的成绩是{count}个」。与 situp_voice.launch.py + exercise_assistant 二选一。

:author slt
:date 2026/04/10
:version 1.4.7
:history
    1.4.7 - 2026/04/27
        :brief 贯通云端训练触发录像与录像时长上限参数
        :desc 新增并透传 session_record_max_duration_sec、training_record_enabled、
              training_record_start_topic、training_record_stop_topic；保持语音入口与云端开始训练入口
              共用同一套录像/上传链路。
    1.4.6 - 2026/04/27
        :brief 找位稳态化默认参数 + 训练桥接等待参数透传
        :desc 调整 search_timeout_sec/search_angular_z/search_yaw_segment_sec/max_angular_z 默认值；
              新增并透传 training_wait_auto_position_ready/training_ap_ready_timeout_sec，降低 AUTO_POSITION_FAILED 误触发。
    1.4.5 - 2026/04/25
        :brief 默认开启 enable_session_record / enable_result_upload；default_user_id 默认从环境 PUPPY_VIDEO_USER_ID
    1.4.4 - 2026/04/25
        :brief video_cos_upload 透传 default_user_id（notify 与后端 user_id 必填一致）
    1.4.3 - 2026/04/25
        :brief 透传 auto_position 找位转速：search_angular_z / search_yaw_segment_sec / max_angular_z（语音流程默认较慢）
    1.4.2 - 2026/04/23
        :brief counting_tts 透传 periodic_announce_*：定周期口播当前个数，可选句末追随机鼓励
    1.4.1 - 2026/04/18
        :brief training_session_bridge Include 映射改为 ts_* 参数名，避免与组合 launch 中 mqtt_telemetry 等同名冲突
    1.4.0 - 2026/04/13
        :brief 接入 bridge_pkg/training_session_bridge：在 _opaque_setup 中按 enable_training_session_bridge 条件 Include；
                新增 training_device_id/training_broker_host/training_broker_port/training_use_tls/
                training_count_report_interval_sec/training_complete_on_target 参数透传，形成「前端开始训练→终端闭环」入口
    1.3.0 - 2026/04/11
        :brief asr_repeat_record_on_keyword_miss 默认 false：未命中只播一次，不重录
    1.2.0 - 2026/04/11
        :brief voice_asr 关键词门控：未命中则 TTS「抱歉我没有听清」再录音（可调 asr_* 参数）
    1.1.0 - 2026/04/10
        :brief 默认文案对齐：确认语/找位失败/开始计数/成绩一句播
'''

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _workspace_root_from_this_launch() -> Path:
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
    pkg_engine = get_package_share_directory("exercise_engine_pkg")
    situp_ap = os.path.join(pkg_engine, "launch", "situp_with_auto_position.launch.py")
    bridge_share = get_package_share_directory("bridge_pkg")
    training_bridge_launch = os.path.join(
        bridge_share,
        "launch",
        "training_session_bridge.launch.py",
    )

    enable_raw = LaunchConfiguration("enable_session_record").perform(context).lower().strip()
    enable = enable_raw in ("true", "1", "yes")

    upload_raw = LaunchConfiguration("enable_result_upload").perform(context).lower().strip()
    enable_upload = upload_raw in ("true", "1", "yes") and enable

    record_dir = LaunchConfiguration("record_output_dir").perform(context).strip()
    if not record_dir:
        record_dir = str(_workspace_root_from_this_launch() / "record_video")
    os.makedirs(record_dir, exist_ok=True)

    start_topic = "session/record_start" if enable else ""
    stop_topic = "session/record_stop" if enable else ""

    phrase_end_done = "situp/voice/phrase_end_done"

    asr_kw_raw = LaunchConfiguration("asr_require_command_keywords").perform(context).lower().strip()
    asr_require_kw = asr_kw_raw in ("true", "1", "yes")
    asr_mismatch = LaunchConfiguration("asr_keyword_mismatch_phrase").perform(context).strip() or "抱歉我没有听清"
    try:
        asr_max_rounds = int(LaunchConfiguration("asr_keyword_match_max_rounds").perform(context).strip() or "0")
    except ValueError:
        asr_max_rounds = 0
    asr_kw_list = [
        x.strip()
        for x in LaunchConfiguration("asr_command_keywords").perform(context).split(",")
        if x.strip()
    ]
    if not asr_kw_list:
        asr_kw_list = ["开始", "计数", "仰卧起坐"]

    asr_repeat_raw = LaunchConfiguration("asr_repeat_record_on_keyword_miss").perform(context).lower().strip()
    asr_repeat_record = asr_repeat_raw in ("true", "1", "yes")

    overlay_enable_raw = LaunchConfiguration("enable_video_overlay").perform(context).lower().strip()
    enable_video_overlay = overlay_enable_raw in ("true", "1", "yes")
    raw_image_topic = (LaunchConfiguration("raw_image_topic").perform(context) or "").strip() or "/pose_image"
    overlay_image_topic = (
        LaunchConfiguration("overlay_image_topic").perform(context) or ""
    ).strip() or "/pose_image_overlay"
    stats_topic = (LaunchConfiguration("stats_topic").perform(context) or "").strip() or "/pose_video_stats"
    dashboard_video_topic = overlay_image_topic if enable_video_overlay else raw_image_topic
    record_image_topic = overlay_image_topic if enable_video_overlay else raw_image_topic

    actions = []

    include_motion_raw = LaunchConfiguration("include_puppy_motion").perform(context).lower().strip()
    include_motion = include_motion_raw in ("true", "1", "yes")
    if include_motion:
        puppy_share = get_package_share_directory("puppy_control")
        motion_stack_launch = os.path.join(puppy_share, "launch", "puppy_motion_stack.launch.py")
        actions.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(motion_stack_launch),
            )
        )

    actions.append(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(situp_ap),
            launch_arguments=[
                ("start_stopped", "true"),
                ("backend_config_path", LaunchConfiguration("backend_config_path")),
                ("use_backend_config", LaunchConfiguration("use_backend_config")),
                ("use_pose_scan", LaunchConfiguration("use_pose_scan")),
                # 须等用户关键词后由 orchestrator 发 auto_position/control=start，避免上电即找位
                ("auto_position_autostart", "false"),
                ("search_timeout_sec", LaunchConfiguration("search_timeout_sec")),
                ("search_angular_z", LaunchConfiguration("search_angular_z")),
                ("search_yaw_segment_sec", LaunchConfiguration("search_yaw_segment_sec")),
                ("max_angular_z", LaunchConfiguration("max_angular_z")),
                ("enable_video_overlay", LaunchConfiguration("enable_video_overlay")),
                ("raw_image_topic", raw_image_topic),
                ("overlay_image_topic", overlay_image_topic),
                ("dashboard_video_topic", dashboard_video_topic),
                ("stats_topic", stats_topic),
            ],
        )
    )
    actions.append(
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(training_bridge_launch),
            condition=IfCondition(LaunchConfiguration("enable_training_session_bridge")),
            launch_arguments=[
                ("ts_backend_config_path", LaunchConfiguration("backend_config_path")),
                ("ts_device_id", LaunchConfiguration("training_device_id")),
                ("ts_broker_host", LaunchConfiguration("training_broker_host")),
                ("ts_broker_port", LaunchConfiguration("training_broker_port")),
                ("ts_use_tls", LaunchConfiguration("training_use_tls")),
                ("wait_auto_position_ready", LaunchConfiguration("training_wait_auto_position_ready")),
                ("auto_position_ready_timeout_sec", LaunchConfiguration("training_ap_ready_timeout_sec")),
                ("record_enabled", LaunchConfiguration("training_record_enabled")),
                ("record_start_topic", LaunchConfiguration("training_record_start_topic")),
                ("record_stop_topic", LaunchConfiguration("training_record_stop_topic")),
                ("count_report_interval_sec", LaunchConfiguration("training_count_report_interval_sec")),
                ("complete_on_target", LaunchConfiguration("training_complete_on_target")),
                ("control_topic", "situp_control"),
                ("ts_count_topic", "situp_count"),
            ],
        )
    )

    actions.extend(
        [
            Node(
                package="voice_pkg",
                executable="counting_tts",
                name="counting_tts",
                output="screen",
                parameters=[
                    {
                        "count_topic": "situp_count",
                        "exercise_name": "仰卧起坐",
                        "phrase_start": ParameterValue(
                            LaunchConfiguration("phrase_start"), value_type=str
                        ),
                        "phrase_end": ParameterValue(LaunchConfiguration("phrase_end"), value_type=str),
                        "speak_topic": "tts/speak",
                        "start_spoken_notify_topic": "situp/ws_start",
                        "tts_done_topic": "tts/done",
                        "session_record_start_topic": start_topic,
                        "session_record_stop_topic": stop_topic,
                        "phrase_end_notify_topic": phrase_end_done,
                        # 强制以字符串下发，避免 YAML 把 true/数字解析为 BOOL 导致与 counting_tts 声明类型冲突、节点起不来
                        "encouragement_enabled": ParameterValue(
                            LaunchConfiguration("encouragement_enabled"), value_type=str
                        ),
                        "encouragement_interval": ParameterValue(
                            LaunchConfiguration("encouragement_interval"), value_type=str
                        ),
                        "encouragement_phrases": ParameterValue(
                            LaunchConfiguration("encouragement_phrases"), value_type=str
                        ),
                        "periodic_announce_sec": ParameterValue(
                            LaunchConfiguration("periodic_announce_sec"), value_type=str
                        ),
                        "periodic_announce_template": ParameterValue(
                            LaunchConfiguration("periodic_announce_template"), value_type=str
                        ),
                        "periodic_announce_add_encouragement": ParameterValue(
                            LaunchConfiguration("periodic_announce_add_encouragement"),
                            value_type=str,
                        ),
                    }
                ],
            ),
            Node(
                package="voice_pkg",
                executable="voice_asr",
                name="voice_asr",
                output="screen",
                parameters=[
                    {
                        "output_topic": "asr/text",
                        "wakeup_greeting": LaunchConfiguration("wakeup_greeting"),
                        "greeting_speak_topic": "tts/speak",
                        "wait_for_tts_done": True,
                        "tts_done_topic": "tts/done",
                        "tts_done_timeout_sec": LaunchConfiguration("tts_done_timeout_sec"),
                        "require_command_keywords": asr_require_kw,
                        "command_keywords": asr_kw_list,
                        "keyword_mismatch_phrase": asr_mismatch,
                        "keyword_match_max_rounds": asr_max_rounds,
                        "repeat_record_on_keyword_miss": asr_repeat_record,
                    }
                ],
            ),
            Node(
                package="timer_interrupt",
                executable="timer",
                name="timer_interrupt",
                output="screen",
                parameters=[
                    {
                        "duration_sec": LaunchConfiguration("duration_sec"),
                        "control_topic": "situp_control",
                        "exercise_name": "仰卧起坐",
                        "start_on_launch": False,
                    }
                ],
            ),
            Node(
                package="task_manager_pkg",
                executable="situp_voice_orchestrator",
                name="situp_voice_orchestrator",
                output="screen",
                parameters=[
                    {
                        "asr_topic": "asr/text",
                        "count_topic": "situp_count",
                        "tts_speak_topic": "tts/speak",
                        "timer_start_topic": "timer/start",
                        "control_topic": "situp_control",
                        "auto_position_control_topic": "auto_position/control",
                        "auto_position_status_topic": "auto_position/status",
                        "phrase_ack": LaunchConfiguration("phrase_ack"),
                        "phrase_no_person": LaunchConfiguration("phrase_no_person"),
                        "start_spoken_notify_topic": "situp/ws_start",
                        "session_record_start_topic": start_topic,
                        "ap_start_delay_sec": ParameterValue(
                            LaunchConfiguration("ap_start_delay_sec"),
                            value_type=float,
                        ),
                    }
                ],
            ),
            Node(
                package="voice_pkg",
                executable="situp_result_tts",
                name="situp_result_tts",
                output="screen",
                parameters=[
                    {
                        "count_topic": "situp_count",
                        "phrase_end_done_topic": phrase_end_done,
                        "result_delay_sec": 0.1,
                        "phrase_result_template": LaunchConfiguration("phrase_result_template"),
                        "exercise_name": "仰卧起坐",
                    }
                ],
            ),
        ]
    )

    if enable:
        actions.append(
            Node(
                package="video_record_pkg",
                executable="session_video_record",
                name="session_video_record",
                output="screen",
                parameters=[
                    {
                        "record_start_topic": start_topic,
                        "record_stop_topic": stop_topic,
                        "image_topic": record_image_topic,
                        "output_dir": record_dir,
                        "fps": 20.0,
                        "file_prefix": "situp",
                        "video_encoder": LaunchConfiguration("session_video_encoder"),
                        "max_record_duration_sec": ParameterValue(
                            LaunchConfiguration("session_record_max_duration_sec"),
                            value_type=float,
                        ),
                    }
                ],
            )
        )

    if enable_upload:
        actions.append(
            Node(
                package="video_upload_pkg",
                executable="video_cos_upload",
                name="video_cos_upload",
                output="screen",
                parameters=[
                    {
                        "backend_config_path": LaunchConfiguration("backend_config_path"),
                        "record_done_topic": "session/record_done",
                        "default_user_id": LaunchConfiguration("default_user_id"),
                    }
                ],
            )
        )

    return actions


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "duration_sec",
                default_value="60",
                description="收到 timer/start 后的倒计时时长（秒），到时向 situp_control 发 stop",
            ),
            DeclareLaunchArgument(
                "backend_config_path",
                default_value="/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json",
                description="后端配置文件路径",
            ),
            DeclareLaunchArgument(
                "use_backend_config",
                default_value="false",
                description="false 时 Web 看板可不加载后端配置；true 时需环境等到位",
            ),
            DeclareLaunchArgument(
                "wakeup_greeting",
                default_value="我在，有什么可以帮到您",
                description="唤醒后先发至 tts/speak；空字符串可关闭",
            ),
            DeclareLaunchArgument(
                "tts_done_timeout_sec",
                default_value="12.0",
                description="voice_asr 等待 tts/done 的超时（秒）",
            ),
            DeclareLaunchArgument(
                "asr_require_command_keywords",
                default_value="true",
                description="true：识别句须含关键词才发布 asr/text，否则播 asr_keyword_mismatch_phrase 再录",
            ),
            DeclareLaunchArgument(
                "asr_command_keywords",
                default_value="开始,计数,仰卧起坐",
                description="逗号分隔，须与 situp_voice_orchestrator 触发词一致",
            ),
            DeclareLaunchArgument(
                "asr_keyword_mismatch_phrase",
                default_value="抱歉我没有听清",
                description="未命中关键词时的 TTS 提示",
            ),
            DeclareLaunchArgument(
                "asr_keyword_match_max_rounds",
                default_value="0",
                description="0：仅内部 100 轮上限；>0：达该轮数后仍发布最后一次识别（避免无限循环）",
            ),
            DeclareLaunchArgument(
                "asr_repeat_record_on_keyword_miss",
                default_value="false",
                description="true：未命中时播提示后再录音（可多轮）；false：只播一次，等下次唤醒",
            ),
            DeclareLaunchArgument(
                "enable_session_record",
                default_value="true",
                description="true：启用会话录像并注入 counting_tts / 编排器；默认 true，本地纯测可 false",
            ),
            DeclareLaunchArgument(
                "record_output_dir",
                default_value="",
                description="录像目录；空则使用工作空间根下 record_video/",
            ),
            DeclareLaunchArgument(
                "session_video_encoder",
                default_value="libx264",
                description="会话录像 ffmpeg 视频编码器",
            ),
            DeclareLaunchArgument(
                "session_record_max_duration_sec",
                default_value="600.0",
                description="会话录像最大时长（秒），超过自动停录并进入上传流程；<=0 表示不限制",
            ),
            DeclareLaunchArgument(
                "include_puppy_motion",
                default_value="true",
                description="true：先启动 ros_robot_controller + puppy_control（与 auto_position /cmd_vel_nav、pose 约定一致）",
            ),
            DeclareLaunchArgument(
                "use_pose_scan",
                default_value="true",
                description="auto_position 是否下发机体俯仰扫描；无硬件时可 false",
            ),
            DeclareLaunchArgument(
                "search_timeout_sec",
                default_value="45.0",
                description="auto_position 搜索阶段超时（秒），超时 status 含 failed，编排播 phrase_no_person",
            ),
            DeclareLaunchArgument(
                "search_angular_z",
                default_value="0.10",
                description="找位 SEARCHING 角速度（rad/s），默认更保守以提升视觉稳定检出",
            ),
            DeclareLaunchArgument(
                "search_yaw_segment_sec",
                default_value="3.0",
                description="SEARCHING 每段同向旋转时长（秒），略长利于单帧检测稳定",
            ),
            DeclareLaunchArgument(
                "max_angular_z",
                default_value="0.18",
                description="对中阶段角速度上限（rad/s），略低于默认 0.35，减少摆过",
            ),
            DeclareLaunchArgument(
                "enable_video_overlay",
                default_value="true",
                description="true 时新增 video_overlay 节点，并让 dashboard/录像使用叠字图像话题",
            ),
            DeclareLaunchArgument(
                "raw_image_topic",
                default_value="/pose_image",
                description="pose_detector 原始图像话题",
            ),
            DeclareLaunchArgument(
                "overlay_image_topic",
                default_value="/pose_image_overlay",
                description="video_overlay 输出图像话题",
            ),
            DeclareLaunchArgument(
                "stats_topic",
                default_value="/pose_video_stats",
                description="视频 FPS 状态话题",
            ),
            DeclareLaunchArgument(
                "ap_start_delay_sec",
                default_value="0.6",
                description="phrase_ack 发出后延迟多少秒再发 auto_position start；便于先播完短确认语再找位（0=立即找位，与旧行为一致）",
            ),
            DeclareLaunchArgument(
                "phrase_ack",
                default_value="收到，正在调整位置",
                description="命中关键词后对用户的短确认 TTS",
            ),
            DeclareLaunchArgument(
                "phrase_no_person",
                default_value="没有找到合适的位置",
                description="找位失败时播报",
            ),
            DeclareLaunchArgument(
                "phrase_start",
                default_value="仰卧起坐开始计数",
                description="找位就绪且计数初始化后播报（与 counting_tts phrase_start 一致）",
            ),
            DeclareLaunchArgument(
                "phrase_end",
                default_value="",
                description="计时结束时先播的短句；空则只触发成绩口播（见 phrase_result_template）",
            ),
            DeclareLaunchArgument(
                "phrase_result_template",
                default_value="计时结束，您的成绩是{count}个",
                description="phrase_end 播完（或为空直接衔接）后播报，{count} 为实时个数",
            ),
            DeclareLaunchArgument(
                "encouragement_enabled",
                default_value="true",
                description="true：每完成 encouragement_interval 个（默认 5）随机播一条鼓励语",
            ),
            DeclareLaunchArgument(
                "encouragement_interval",
                default_value="5",
                description="从 counting_tts 参数传入：鼓励语间隔（完成次数）",
            ),
            DeclareLaunchArgument(
                "encouragement_phrases",
                default_value="加油，你是最棒的！|核心收紧，感受肌肉的发力。|非常标准的动作！|保持呼吸，不要憋气。|还剩最后一点点，坚持就是胜利！",
                description="用竖线 | 分隔多条，传入 counting_tts；换行可改为 |",
            ),
            DeclareLaunchArgument(
                "periodic_announce_sec",
                default_value="20",
                description="定周期口播：每隔多少秒报一次当前个数；0 为关闭。仅在 UP/DOWN 计数中触发",
            ),
            DeclareLaunchArgument(
                "periodic_announce_template",
                default_value="你已经做了{count}个了",
                description="口播模板，必须含 {count} 占位；可与 periodic_announce_add_encouragement 联用",
            ),
            DeclareLaunchArgument(
                "periodic_announce_add_encouragement",
                default_value="true",
                description="true：在模板句后追加一条 encouragement_phrases 中的随机短句",
            ),
            DeclareLaunchArgument(
                "enable_result_upload",
                default_value="true",
                description="true 且 enable_session_record：启动 video_cos_upload（STS→COS→notify，需后端接口与 cos-python-sdk-v5）；默认 true，无后端可 false",
            ),
            DeclareLaunchArgument(
                "default_user_id",
                default_value=EnvironmentVariable("PUPPY_VIDEO_USER_ID", default_value=""),
                description="video_cos_upload：POST video_notify 的 user_id；未在命令行覆盖时取环境 PUPPY_VIDEO_USER_ID，否则为空（可先 source 工作区 .env）",
            ),
            DeclareLaunchArgument(
                "enable_training_session_bridge",
                default_value="true",
                description="true：接入训练会话桥接（MQTT 控制 + HTTP confirm/complete/error）",
            ),
            DeclareLaunchArgument(
                "training_device_id",
                default_value="",
                description="训练桥接设备 ID 覆盖；空则使用 backend_config.json 的 device.device_id",
            ),
            DeclareLaunchArgument(
                "training_broker_host",
                default_value="",
                description="训练桥接 MQTT host 覆盖；空则使用 backend_config.json",
            ),
            DeclareLaunchArgument(
                "training_broker_port",
                default_value="",
                description="训练桥接 MQTT port 覆盖；空则使用 backend_config.json",
            ),
            DeclareLaunchArgument(
                "training_use_tls",
                default_value="",
                description="训练桥接 MQTT TLS 覆盖；空则使用 backend_config.json",
            ),
            DeclareLaunchArgument(
                "training_count_report_interval_sec",
                default_value="1.0",
                description="训练桥接计数上报节流周期（秒）",
            ),
            DeclareLaunchArgument(
                "training_record_enabled",
                default_value="true",
                description="训练桥接是否发布会话录像 start/stop（云端开始训练触发录像）",
            ),
            DeclareLaunchArgument(
                "training_record_start_topic",
                default_value="session/record_start",
                description="训练桥接发布录像开始话题",
            ),
            DeclareLaunchArgument(
                "training_record_stop_topic",
                default_value="session/record_stop",
                description="训练桥接发布录像结束话题",
            ),
            DeclareLaunchArgument(
                "training_wait_auto_position_ready",
                default_value="true",
                description="训练桥接是否等待 auto_position ready 后再开始计数",
            ),
            DeclareLaunchArgument(
                "training_ap_ready_timeout_sec",
                default_value="75.0",
                description="训练桥接等待 auto_position ready 超时（秒），建议大于 search_timeout_sec",
            ),
            DeclareLaunchArgument(
                "training_complete_on_target",
                default_value="true",
                description="true：计数达到 target 时自动上报 complete 并下发 situp_control stop",
            ),
            OpaqueFunction(function=_opaque_setup),
        ]
    )
