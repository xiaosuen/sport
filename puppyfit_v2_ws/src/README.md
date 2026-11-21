# puppyfit_v2_ws 源码包总览

**本工作空间整体作用**：**PuppyFit v2** 的 ROS 2（Humble）软件集合，覆盖仰卧起坐训练场景的 **感知、运动引擎、语音、任务编排、云端桥接、启动管理**；与 **`src/quadruped/`** 下 PuppyPi 四足厂商栈协同（四足包说明见 [`quadruped/README.md`](quadruped/README.md)，本文不展开）。

下文按**典型场景**逐条给出 **作用**、**流程**、**操作**；编译后均需 `source /opt/ros/humble/setup.bash` 与 **`source <工作空间>/install/setup.bash`**。更细的 launch 说明见 **[bringup_pkg/README.md](bringup_pkg/README.md)** 及各包 README。

---

## 场景：仰卧起坐 + 自动找位 + 四足栈（无语音，一条命令）

**作用**：等价于先起四足运动栈，再起 `situp_with_auto_position`（单摄像头计数+找位）。

**流程**：可选 `puppy_motion_stack` → `pose_detector` / `situp_counter` / `human_pose_bridge` / `auto_position` / `web_dashboard` 等。

**操作**：

```bash
ros2 launch bringup_pkg situp_with_motion_stack.launch.py
```

- `start_motion_stack`默认 `true`：先控制板 + `puppy_control`，再 `exercise_engine_pkg/situp_with_auto_position.launch.py`。
- 无狗、只调视觉：`start_motion_stack:=false`（`/cmd_vel_nav` 无订阅属预期）。

透传 `situp_with_auto_position` 参数示例：

```bash
ros2 launch bringup_pkg situp_with_motion_stack.launch.py \
  use_backend_config:=true \
  auto_position_autostart:=false
```

---

## 场景：仰卧起坐 + 语音 + 自动找位 + 成绩口播

**作用**：整机语音入口：唤醒/ASR → 找位 → 计数 + 定时 + 口播成绩。

**流程**：详见 [bringup_pkg/README.md](bringup_pkg/README.md) 中 `situp_voice_full`、`situp_voice_full_with_cloud_monitor`。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py
```

叠加 MQTT/HTTP 遥测与监控 WebSocket（不双开计数栈）：

```bash
ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py
```

---

## 场景：仰卧起坐 + 语音助手（无自动找位，旧编排）

**作用**：`exercise_assistant` 编排 + `situp_counter.launch` 链；**不含** `auto_position`。

**流程**：串口/话题唤醒 →（可选）问候 TTS → 录音 → ASR → 关键词 →（可选）`SessionRecordStart` → `situp_control=start` → 就绪后「开始计数」→ `situp/ws_start` → `timer/start` → 到时 `situp_control=stop` → 「计时结束」→（可选）`SessionRecordStop` → 空闲。姿态与计数由 **`exercise_engine_pkg/situp_counter.launch.py`**提供（**非** `situp_with_auto_position`）。与 **`perception_pkg`** 单独起 `human_pose_node` 的链路 **不是同一条**。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice.launch.py
```

常用示例：

```bash
ros2 launch bringup_pkg situp_voice.launch.py wakeup_greeting:=''
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py use_backend_config:=true
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py \
  use_backend_config:=true \
  backend_config_path:=/home/ubuntu/puppyfit/puppyfit_v2_ws/config/backend_config.json
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py enable_session_record:=true
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py \
  enable_session_record:=true \
  record_output_dir:=/home/ubuntu/Videos/puppyfit_sessions
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py tts_done_timeout_sec:=20.0
```

```bash
ros2 launch bringup_pkg situp_voice.launch.py \
  duration_sec:=90 \
  enable_session_record:=true \
  wakeup_greeting:=''
```

**会话录像**：`enable_session_record:=true`，视频默认 **`record_video/`**（工作空间根下，与 `src` 同级），见 [video_record_pkg/README.md](video_record_pkg/README.md)、[session_record_msgs/README.md](session_record_msgs/README.md)。**上传 COS**：`situp_voice_full` 下另设 **`enable_result_upload:=true`**（须后端 STS/notify），见 [video_upload_pkg/README.md](video_upload_pkg/README.md)。

---

## 场景：仅计数 + 定时 + 播报（无 ASR 编排）

**作用**：快速测口播与定时，不经完整语音编排。

**流程**：`voice_pkg` 的 `situp_timer_tts` 与计数、定时器协同。可选**鼓励语**（`encouragement_*`），见 [voice_pkg/README.md](voice_pkg/README.md) 中 `counting_tts` 与 `situp_timer_tts`。

**操作**：

```bash
ros2 launch voice_pkg situp_timer_tts.launch.py
```

---

## 场景：仅 `exercise_engine_pkg`（自动找位 + 计数，不经过 bringup）

**作用**：单包拉起 `pose_detector` + `human_pose_bridge` + `auto_position` + 计数 + `web_dashboard`；真机需另有节点订阅 **`/cmd_vel_nav`** 与 **`/puppy_control/pose`**。

**流程**：默认 `use_backend_config:=false`；上云 `source .env` 且 `use_backend_config:=true`；无四足 `use_pose_scan:=false`；默认 `auto_position_autostart:=true`，编排驱动找位时改为 `false`（见 `puppyfit/doc/plan/plan.md`）。

**操作**：

```bash
ros2 launch exercise_engine_pkg situp_with_auto_position.launch.py
```

仅自动找位（需另有 `HumanPose`）：

```bash
ros2 launch exercise_engine_pkg auto_position.launch.py
```

详见 [exercise_engine_pkg/README.md](exercise_engine_pkg/README.md)。

---

## 场景：MQTT 遥测 / 云端监控 / 电池

**作用**：设备侧上云与实时监控推流。

**流程**：`telemetry_bridge`、`monitor_ws_bridge`、或与仰卧起坐栈组合 launch。

**操作**：

```bash
ros2 launch bridge_pkg mqtt_telemetry.launch.py
```

```bash
ros2 launch bridge_pkg situp_counter_monitor_cloud.launch.py
```

详见 [bridge_pkg/README.md](bridge_pkg/README.md)。

---

## 场景：四足 PuppyPi 单独启动

**作用**：只调试底盘与控制，不跑仰卧起坐栈。

**流程**：`puppy_motion_stack` 或仅 `puppy_control`；整机也可由上文 **「仰卧起坐 + 四足」** 或 **`situp_voice_full`**（`include_puppy_motion:=true`）一并拉起。

**操作**：

```bash
ros2 launch puppy_control puppy_motion_stack.launch.py
```

```bash
ros2 launch puppy_control puppy_control.launch.py
```

```bash
export PUPPYPI_CONTROL_PATH=/path/to/puppypi_control
```

更多见 `quadruped/puppy_control/README.md`（四足目录内文档，本文不修改）。

---

## 场景：其它可选 launch

**作用**：独立感知、手柄、动作组等。

**流程**：各包自带 launch。

**操作**：`perception_pkg`、`puppy_joy_teleop`、`quadruped/puppy_action_show` 等见对应 README。

---

## 工作空间内包索引

**作用**：快速跳转各包文档。

**流程**：各包职责以目录内 `README.md` 为准。

**操作**：

| 包名 | 定位 |
|------|------|
| [robot_msgs](robot_msgs/README.md) | 统一消息接口 |
| [task_manager_pkg](task_manager_pkg/README.md) | 任务总控（大脑） |
| [exercise_engine_pkg](exercise_engine_pkg/README.md) | 运动识别与计数引擎 |
| [perception_pkg](perception_pkg/README.md) | 感知层 |
| [voice_pkg](voice_pkg/README.md) | 语音层 |
| [bridge_pkg](bridge_pkg/README.md) | 外部桥接（MQTT 等） |
| [timer_interrupt](timer_interrupt/README.md) | 通用定时 → `*_control` `stop` |
| [bringup_pkg](bringup_pkg/README.md) | 启动管理 |
| [session_record_msgs](session_record_msgs/README.md) | 会话录像消息 |
| [video_record_pkg](video_record_pkg/README.md) | FFmpeg MP4 录像 |
| [video_upload_pkg](video_upload_pkg/README.md) | 录像落盘后 STS→COS→notify |
| [sdk](sdk/README.md)（可选） | Python SDK；四足节点不依赖 |
| [quadruped/](quadruped/README.md) | 四足栈目录归组（子包文档在 quadruped 内） |

### PuppyPi 基本运动控制（`src/quadruped/`）

| 包名 | 说明 |
|------|------|
| [puppypi_vendor](quadruped/puppypi_vendor/) | `puppypi_control` 运行时 |
| [ros_robot_controller](quadruped/ros_robot_controller/) | STM32 控制板 ROS 桥 |
| [ros_robot_controller_msgs](quadruped/ros_robot_controller_msgs/) | 控制板消息 |
| [puppy_control](quadruped/puppy_control/) | 速度/姿态 → `HiwonderPuppy` |
| [puppy_control_msgs](quadruped/puppy_control_msgs/) | 小狗控制消息 |

---

## 编译四足相关包（摘录）

**作用**：仅编四足子集时减少编译时间。

**流程**：移动目录后建议 `rm -rf build install log` 再编；勿混 root 编译导致权限问题。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select puppypi_vendor ros_robot_controller_msgs puppy_control_msgs ros_robot_controller puppy_control
source install/setup.bash
```

`Permission denied` 写 `build/`：用普通用户编译并 `chown`。`git pull` 报 `.git/FETCH_HEAD` 权限：`sudo chown -R "$USER:$USER" .git`。

---

## 对接与联调（实时监控 / 遥测）

**作用**：区分设备 WebSocket 与浏览器 Dashboard WebSocket。

**流程**：终端、MQTT、Nginx 分工见仓库文档。

**操作**：**[doc/monitor_telemetry_integration.md](../doc/monitor_telemetry_integration.md)**（含 `/api/monitor/ws` 与 `/ws/camera` 说明）。
