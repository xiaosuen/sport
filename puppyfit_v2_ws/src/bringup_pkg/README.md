# bringup_pkg

**本包整体作用**：集中管理整机与场景的 **ROS 2 launch 入口**，将四足运动栈、仰卧起坐引擎、语音编排、云端遥测与监控等组合为可一条命令启动的流程。

下文每条均含 **作用**、**流程**、**操作**。

---

## `situp_with_motion_stack.launch.py`

**作用**：一条命令起四足栈（可选）+ 仰卧起坐自动找位与计数（`situp_with_auto_position`）。

**流程**：可选 `puppy_motion_stack`（控制板 + `puppy_control`）→ `pose_detector` / `situp_counter` / `auto_position` / `web_dashboard` 等。

**操作**：

```bash
ros2 launch bringup_pkg situp_with_motion_stack.launch.py
```

无底盘仅调视觉：`start_motion_stack:=false`。其余参数与 `situp_with_auto_position` 一致，`--show-args` 查看。

---

## `situp_voice_full.launch.py`

**作用**：语音唤醒 + 关键词 → 自动找位 → `situp_control` 计数 + 定时 + 成绩口播；可选训练会话桥、会话录像、**录像上传 COS（STS→notify）**、四足栈。

**流程**：唤醒 TTS → ASR（须含配置关键词）→ 确认语 → `auto_position` → 就绪后计数与口播（**`counting_tts` 可选按完成个数播鼓励语 `encouragement_*`，以及定周期报当前个数 `periodic_announce_*`**）→ 结束播成绩；若开启 **`enable_result_upload`**，则在 **`enable_session_record`** 为真时额外启动 **`video_cos_upload`**，订阅 `session/record_done`。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py
```

`auto_position_autostart` 默认 `false`（关键词后才找位）。参数：`ros2 launch ... --show-args`。

**找位搜索阶段转速**（`auto_position` 的 **SEARCHING**，经 **`/cmd_vel_nav` 的 `angular.z`**）：若转太快易错过人体关节点，可下调。本 launch 对 **`search_angular_z` / `search_yaw_segment_sec` / `max_angular_z`** 有声明，默认比引擎包单独启动时**更慢**（利于视觉稳定检出）；更慢可再覆盖，例如：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py \
  search_angular_z:=0.10 \
  search_yaw_segment_sec:=3.0
```

含义见下表 `situp_voice_full` 参数表。节点侧完整列表仍以 `exercise_engine_pkg` 的 `auto_position` 为准。

**录像 + 上传（需后端 STS/notify 与 `cos-python-sdk-v5`）**：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py \
  enable_session_record:=true \
  enable_result_upload:=true \
  backend_config_path:=/path/to/puppyfit_v2_ws/config/backend_config.json
```

详见 [video_upload_pkg/README.md](../video_upload_pkg/README.md)。

**定周期口播（报数字 + 可选句末鼓励）** 参数与行为见 [voice_pkg/README.md](../voice_pkg/README.md) 中 **「`counting_tts`：定周期口播」** 一节。默认约每 **20** 秒播一次「你已经做了{count}个了」，且句末可追加随机鼓励短句；关闭定周期：`periodic_announce_sec:=0`。

---

## `situp_voice_full_with_cloud_monitor.launch.py`

**作用**：在 `situp_voice_full` 上叠加 **MQTT/HTTP 遥测**（`telemetry_bridge`）与 **监控 WebSocket**（`monitor_ws_bridge`），不另起一套 `situp_counter`（避免双开感知/计数）。

**流程**：与 `situp_voice_full` 相同；并行：`/ros_robot_controller/battery` → 遥测；`/pose_image`、`situp_count` → `monitor_ws_bridge`。

**操作**：

```bash
cd <puppyfit_v2_ws>
source /opt/ros/humble/setup.bash && source install/setup.bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py
```

需云端上报时先配置 `PUPPY_MQTT_*`（及 HTTP 心跳时的 `PUPPY_DEVICE_*`）。已与 `situp_voice_full` 共用 `bridge_pkg/situp_counter_monitor_cloud` 时不要叠用后者。详情：`doc/plan/plan418.md`。

**定周期口播** 等与 `situp_voice_full` 相同，继承 `situp_voice_full.launch.py` 里的**默认值**（约每 **20** 秒、`你已经做了{count}个了`、句末可追随机鼓励）；不覆盖时直接 `ros2 launch ... situp_voice_full_with_cloud_monitor.launch.py` 即可。找位搜索角速度、每段旋转时长、对中角速度限幅等 **与 `situp_voice_full` 同一张参数表**（`search_angular_z` 等），见上节 **找位搜索阶段转速** 与下表。

**常用一条**（定周期 15s、句末随机鼓励、找位 SEARCHING 不按时间判失败）：

```bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py \
  periodic_announce_sec:=15 \
  periodic_announce_add_encouragement:=true \
  search_timeout_sec:=0.0
```

`search_timeout_sec` 透传 `auto_position`；**`0.0` 表示 SEARCHING 阶段不判超时**（需已使用支持该语义的 `exercise_engine_pkg` 构建；否则请用较大秒数如 `120.0`）。定周期句末鼓励依赖非空的 `encouragement_phrases`，见 [voice_pkg/README.md](../voice_pkg/README.md) 中「`counting_tts`：定周期口播」。

找位转太快、漏检人体时可同时压低搜索角速度（与 `situp_voice_full` 同参）：

```bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py \
  search_angular_z:=0.10 \
  search_yaw_segment_sec:=3.0
```

仅改周期或关闭句末鼓励：

```bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py \
  periodic_announce_sec:=15 \
  periodic_announce_add_encouragement:=false
```

---

## `situp_voice_full_with_cloud_monitor_and_teleop.launch.py`

**作用**：在 `situp_voice_full_with_cloud_monitor` 基础上，额外叠加 **MQTT 遥控桥**（`teleop_mqtt_bridge`），形成“语音训练全流程 + 云端监控/遥测 + 远程控制”单入口；**不**重复启动 `ros_robot_controller` 或 `puppy_motion_stack`。

**流程**：先沿用 `situp_voice_full_with_cloud_monitor` 的语音编排、自动找位、计数、遥测与监控链路；并行再订阅 `puppy/control/{device_id}/teleop`，把云端遥控 JSON 转发到 `/puppy_control/velocity_move`、`/puppy_control/pose`、`/cmd_vel_nav`。

**操作**：

```bash
cd <puppyfit_v2_ws>
source /opt/ros/humble/setup.bash && source install/setup.bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor_and_teleop.launch.py \
  tp_device_id:=puppy_001 \
  tp_broker_host:=122.51.12.83
```

若 MQTT 用户名/密码不在 launch 中显式传入，则仍可沿用环境变量 `PUPPY_MQTT_USER` / `PUPPY_MQTT_PASS`。若自动找位正在发 `/cmd_vel_nav` 或 `/puppy_control/pose`，远控可能与其抢控制；需要人工遥控时可先向 `/auto_position/control` 发送 `stop`。

---

## `situp_voice.launch.py`

**作用**：语音助手编排 + `situp_counter.launch` 计数链（**无** `auto_position`，旧编排）。

**流程**：唤醒 → ASR → `situp_control` → 定时 → 口播；不含自动找位。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice.launch.py
```

常用覆盖：`wakeup_greeting:=''`、`use_backend_config:=true`、`enable_session_record:=true`、`duration_sec:=90` 等，`--show-args` 查看。

---

## 停止 launch

**作用**：结束整条进程树，避免残留占端口（如 `8090`）。

**流程**：launch 子进程命令行通常不含 `ros2`，故 `pkill -f ros2` 往往无效。

**操作**：在启动该 launch 的终端 **`Ctrl+C`**（可连按两次）；仍有残留则：

```bash
pkill -f '<你的>/puppyfit_v2_ws/install'
```

端口占用：`ss -tlnp | grep 8090` 后 `kill` 对应 PID。

---

## Launch 参数表

下列参数均可通过 `ros2 launch bringup_pkg <某.launch.py> --show-args` 查看声明与默认值。表中「作用」为简短说明与典型用法；布尔参数一般写 `true` / `false`。

### `situp_with_motion_stack.launch.py`

| 参数 | 作用 |
|------|------|
| `start_motion_stack` | 是否先起 `puppy_motion_stack`。**false**：只起 `situp_with_auto_position`（无舵机/运动栈订阅，适合纯视觉联调）。 |
| `start_stopped` | 透传 `situp_counter`：**true** 时须收到 `situp_control=start` 后才计数。 |
| `use_backend_config` | 透传 `web_dashboard`：**true** 时加载 `backend_config_path` 并需 `PUPPY_DEVICE_*` 等。 |
| `backend_config_path` | `backend_config.json` 绝对/相对路径。 |
| `use_pose_scan` | 透传 `auto_position`：**true** 时找位会发 `/puppy_control/pose` 俯仰扫描。 |
| `auto_position_autostart` | 透传 `auto_position`：**true** 启动即找位；语音编排流程应用 **false**（等 `auto_position/control`）。 |
| `search_timeout_sec` | 透传 `auto_position`：找位 **SEARCHING** 超时（秒），超时发 failed。 |
| `search_angular_z` | 透传 `auto_position`：**SEARCHING** 时原地转向角速度（**rad/s**），默认与节点侧 `0.28` 一致；过大会易漏检关节点。 |
| `search_yaw_segment_sec` | 透传 `auto_position`：SEARCHING 每段**同向旋转**持续秒数。 |
| `max_angular_z` | 透传 `auto_position`：**对中/调节**阶段 `angular.z` 上限（**rad/s**），与搜索阶段独立。 |

### `situp_voice_full.launch.py`

| 参数 | 作用 |
|------|------|
| `duration_sec` | 定时器时长。**收到 `timer/start` 后** 倒计时，到时向 `situp_control` 发 `stop`。单位：秒。 |
| `backend_config_path` | 后端 `backend_config.json` 路径；**录像上传**、训练桥、看板共用。 |
| `use_backend_config` | **true** 时 `web_dashboard` 加载上述配置；需环境变量就绪，否则可 **false** 先跑通视觉。 |
| `wakeup_greeting` | 唤醒后首句 TTS；**空字符串** 可关问候。 |
| `tts_done_timeout_sec` | `voice_asr` 等 **tts/done** 的等待超时（秒）。 |
| `asr_require_command_keywords` | **true**：识别句须含 `asr_command_keywords` 之一才出 `asr/text`。 |
| `asr_command_keywords` | 逗号分隔关键词，须与编排器触发词（如 开始,计数,仰卧起坐）一致。 |
| `asr_keyword_mismatch_phrase` | 未命中关键词时 TTS 提示文案。 |
| `asr_keyword_match_max_rounds` | **0** 为内部轮数上限；**>0** 达轮数后仍发布最后一次识别。 |
| `asr_repeat_record_on_keyword_miss` | **true**：未命中则播提示再录（可多轮）；**false**：只播一次等下次唤醒。 |
| `enable_session_record` | **true**：起 `session_video_record`，并向 `counting_tts` / 编排器注入开停录话题。**默认 true**；纯测可 `false`。 |
| `record_output_dir` | 录像输出目录；**空** 用工作空间根下 `record_video/`。 |
| `session_video_encoder` | 会话录像 **ffmpeg -c:v**，如 `libx264` 或树莓派 `h264_v4l2m2m`。 |
| `include_puppy_motion` | **true**：先 `Include puppy_motion_stack`；**false** 不启四足栈（`auto_position` 仍发话题，无订阅则通常不动机）。 |
| `use_pose_scan` | 透传 `auto_position`：是否发机体 **俯仰 pose** 扫描。 |
| `search_timeout_sec` | `auto_position` 搜索超时（秒），超时编排播 `phrase_no_person`。 |
| `search_angular_z` | 透传 `auto_position`：SEARCHING 角速度（**rad/s**）。**默认 0.14**（较引擎节点默认 0.28 减半，利于稳定检出关节点）；仍快可 **0.10** 等。 |
| `search_yaw_segment_sec` | 透传 `auto_position`：每段同向转 **秒数**。**默认 2.5**（原 2.0 略长，单帧/连续帧更稳）。 |
| `max_angular_z` | 透传 `auto_position`：对中阶段角速度上限（**rad/s**）。**默认 0.22**（低于节点 0.35，减轻对中过冲）。 |
| `ap_start_delay_sec` | 确认语 `phrase_ack` 发出后，延迟多少秒再发 **auto_position start**；默认 **0.6**，先播完短句再找位；**0** 为与旧版一致（立刻找位）。 |
| `phrase_ack` | 命中关键词后的短确认 TTS（如「收到，正在调整位置」）。 |
| `phrase_no_person` | 找位失败 TTS。 |
| `phrase_start` | 找位就绪、计数起来后的「开始计数」口播。 |
| `phrase_end` | 计时结束**先**播的短句；**空** 则跳过，直接衔接成绩口播。 |
| `phrase_result_template` | 成绩句模板，**`{count}`** 为实时个数。 |
| `encouragement_enabled` | **true**（默认）：`counting_tts` 每完成 **`encouragement_interval`** 个随机播一条鼓励语。 |
| `encouragement_interval` | 鼓励语间隔（完成次数），**默认 5**。 |
| `encouragement_phrases` | 鼓励语，**竖线 `|` 分句**；与 `counting_tts` 的 `encouragement_phrases` 一致。 |
| `periodic_announce_sec` | **定周期口播**间隔（秒）；**0** 关闭。仅在 `UP`/`DOWN` 计数中触发；默认约 **20**。 |
| `periodic_announce_template` | 口播模板，须含 **`{count}`**；透传 `counting_tts`。 |
| `periodic_announce_add_encouragement` | **true**：模板句后追加 `encouragement_phrases` 中随机一句；语料为空则只播模板。 |
| `enable_result_upload` | **true** 且已 `enable_session_record`：起 `video_cos_upload`（需后端 STS/notify、`cos-python-sdk-v5`）。**默认 true**；无后端可 `false`。 |
| `default_user_id` | 透传 `video_cos_upload` 的 `notify` **user_id**。未在命令行覆盖时 **默认取环境 `PUPPY_VIDEO_USER_ID`**（可先 `source` 工作区 `.env`）；空则 notify 可能 400。 |
| `enable_training_session_bridge` | **true**：`Include training_session_bridge`（MQTT + HTTP 会话桥）。单测本地语音可 **false**。 |
| `training_device_id` | 桥接用设备 ID；**空** 用 `backend_config.json` 的 `device_id`。 |
| `training_broker_host` / `training_broker_port` / `training_use_tls` | 覆盖桥接 **MQTT**；**空** 用 `backend_config.json` 的 `mqtt` 段。 |
| `training_count_report_interval_sec` | 桥接**计数上报**最小间隔（秒）。 |
| `training_complete_on_target` | **true**：计数达 target 则上报 complete 并发 `situp_control` **stop**。 |

**说明**：本 launch 内将 `auto_position_autostart` 固化为 **false**（须关键词后再找位），`start_stopped` 固化为 **true**，不在上表重复列出。找位**搜索转速**的 `search_angular_z` 等**未固化**，上表**默认值**已针对「语音确认后再找位」略降速；仍可按场景覆盖。

### `situp_voice.launch.py`

| 参数 | 作用 |
|------|------|
| `duration_sec` | 与 `timer_interrupt` 一致：**`timer/start` 后** 倒计时，到时发 `stop`。 |
| `backend_config_path` | `backend_config.json` 路径，透传 `situp_counter.launch` / 看板。 |
| `use_backend_config` | **true** 时看板加载后端；无账号可 **false**。 |
| `wakeup_greeting` | 唤醒 TTS；**空字符串** 关闭。 |
| `tts_done_timeout_sec` | 等待 **tts/done** 超时（秒）。 |
| `enable_session_record` | **true**：追加 `session_video_record` 并注入开停录话题。 |
| `record_output_dir` | 录像目录；**空** 为 `<ws>/record_video/`。 |
| `session_video_encoder` | 会话录像 **ffmpeg 编码器**（`libx264` / `h264_v4l2m2m` 等）。 |

### `situp_voice_full_with_cloud_monitor.launch.py`

**继承**上表 `situp_voice_full` 的全部参数（含 `backend_config_path`），并额外支持下列 **MQTT 遥测 + 监控 WebSocket**（由 `bridge_pkg` 的 `mqtt_telemetry_declare_launch_arguments` 等注入；`backend_config_path` 不重复声明，与 `situp_voice_full` 共用一条）。

| 参数 | 作用 |
|------|------|
| `device_id` | 遥测/监控用设备 ID。 |
| `broker_host` / `broker_port` / `use_tls` | **MQTT  broker** 地址、端口、是否 TLS。 |
| `mqtt_topic_template` | 发布主题模板，须与云端订阅一致，默认 `puppy/data/{device_id}`。 |
| `voltage_topic` | 电压（伏，`Float32`）话题；**空** 则只用 `battery_mv_topic`。 |
| `battery_mv_topic` | 毫伏（`UInt16`），如 `/ros_robot_controller/battery`；**空** 不订阅。 |
| `battery_v_min` / `battery_v_max` | 电压映射到 0%～100% 的上下限（伏）。 |
| `simulated_voltage_v` | 无有效读数时的回退电压（伏）。 |
| `enable_http_heartbeat` | 是否 **POST** `/api/device/status`；需 `PUPPY_DEVICE_*` 等。 |
| `http_heartbeat_interval_sec` | HTTP 心跳周期（秒），最小约 5。 |
| `http_register_on_start` | 启动时是否 **POST** `/api/device/register`。 |
| `enable_monitor_ws` | **true** 时条件启动 `monitor_ws_bridge` 连云端相机 WS。 |
| `ws_camera_base_url` | **非空** 时与下面 ID 一起覆盖配置里的 `ws_camera_base_url`。 |
| `monitor_override_device_id` | **非空** 时覆盖监控用的 `device_id`（避免与 `device_id` 同名冲突时排查用）。 |
| `image_topic` / `count_topic` | 监控推送用的图像与计数话题。 |
| `push_interval_sec` | 推流/推送周期（秒）。 |
| `push_jpeg` / `jpeg_quality` | 是否 JPEG 及质量。 |
| `heartbeat_interval_sec` | 监控侧心跳间隔（秒）。 |
| `reconnect_backoff_initial_sec` / `reconnect_backoff_max_sec` | WS 重连退避起止（秒）。 |

### `situp_voice_full_with_cloud_monitor_and_teleop.launch.py`

**继承**上表 `situp_voice_full_with_cloud_monitor` 的全部参数，并额外支持下列 **MQTT 遥控桥** 参数（参数名前缀 `tp_` 用于避免与遥测的 `device_id` / `broker_host` 冲突）。

| 参数 | 作用 |
|------|------|
| `tp_backend_config_path` | 遥控桥读取的 `backend_config.json` 路径；**空** 时由桥接节点回退到默认配置路径。 |
| `tp_device_id` | 遥控桥用设备 ID；用于展开订阅主题 `puppy/control/{device_id}/teleop`。 |
| `tp_broker_host` / `tp_broker_port` / `tp_use_tls` | 遥控桥连接的 **MQTT broker** 地址、端口与 TLS 开关。 |
| `mqtt_username` / `mqtt_password` | 遥控桥 MQTT 认证；**空** 时回退到环境变量 `PUPPY_MQTT_USER` / `PUPPY_MQTT_PASS`。 |
| `mqtt_client_id` | 遥控桥客户端 ID；**空** 时自动按设备 ID 生成。 |
| `mqtt_qos` | 遥控订阅 QoS，默认 `1`。 |
| `teleop_topic_template` | 遥控主题模板，默认 `puppy/control/{device_id}/teleop`。 |
| `velocity_move_topic` | `velocity_move` 输出话题，默认 `/puppy_control/velocity_move`。 |
| `pose_topic` | 姿态输出话题，默认 `/puppy_control/pose`。 |
| `cmd_vel_nav_topic` | `Twist` 输出话题，默认 `/cmd_vel_nav`。 |
| `command_hold_sec` | 指令保持时间；超时后自动补发停速，默认 `0.3` 秒。 |
| `seq_idle_reset_sec` | `seq` 空闲重置时间；超过该时长后允许较小的新序号重新接管，默认 `2.0` 秒。 |
