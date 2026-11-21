# exercise_engine_pkg

**本包整体作用**：**运动识别与计数引擎**——基于 **`robot_msgs/PoseLandmarks`** 做仰卧起坐判别与 **`robot_msgs/SitUpCount`**；可选 **HTTP 8090 看板**与后端 WebSocket；**`auto_position`** 订阅 **`HumanPose`**，向 **`/cmd_vel_nav`**、**`/puppy_control/pose`** 发指令完成四足对中。由原 `pose_counter` 迁入，消息在 **`robot_msgs`**。

下文对 **前置与编译**、各 **launch**、**运行后验证**、**参数**、**常见问题**、**节点表**、**找位控制约定**、**四足栈**、**依赖与关联** 给出 **作用**、**流程**、**操作**。

---

## 前置条件

**作用**：保证摄像头、Python 依赖与 `robot_msgs` 可用。

**流程**：ROS 2 Humble；`pose_detector` 默认 `camera_id:=0`；pip 缺啥补啥。

**操作**：

```bash
pip install --user opencv-python mediapipe numpy websocket-client
```

---

## 编译

**作用**：生成本包节点与接口依赖。

**流程**：先编 `robot_msgs`。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select robot_msgs exercise_engine_pkg
source install/setup.bash
```

---

## `situp_counter.launch.py`

**作用**：**只要仰卧起坐计数 + 浏览器看板**（`pose_detector` + `situp_counter` + `web_dashboard`）。

**流程**：默认 `use_backend_config:=true` 时 `web_dashboard` 需 `.env`；本地可 `use_backend_config:=false`。

**操作**：

```bash
ros2 launch exercise_engine_pkg situp_counter.launch.py
# 本地无后端密钥时：
ros2 launch exercise_engine_pkg situp_counter.launch.py use_backend_config:=false
```

---

## `situp_with_auto_position.launch.py`

**作用**：在计数链上增加 **`human_pose_bridge`** + **`auto_position`**，**单摄像头**完成计数与找位；默认 **`auto_position_autostart:=true`**（启动即找位）；默认 **`use_backend_config:=false`**。

**流程**：需四足栈消费 **`/cmd_vel_nav`**、**`/puppy_control/pose`**；上云传 `use_backend_config:=true` 并 `source .env`。

**操作**：

```bash
ros2 launch exercise_engine_pkg situp_with_auto_position.launch.py
```

无四足：`use_pose_scan:=false`；与编排配合找位时机：`auto_position_autostart:=false` 并由上层 `pub /auto_position/control start`。调节 **SEARCHING 转向快慢**：`search_angular_z`（**rad/s**）、`search_yaw_segment_sec`、**对中** `max_angular_z` 已由本 launch 透传至 `auto_position`，默认与节点内建值一致，详见 **常用 Launch 参数** 表。

带后端：

```bash
set -a && source .env && set +a
source install/setup.bash
ros2 launch exercise_engine_pkg situp_with_auto_position.launch.py use_backend_config:=true \
  backend_config_path:=/path/to/puppyfit_v2_ws/config/backend_config.json
```

---

## `auto_position.launch.py`

**作用**：**仅** `auto_position`；需另有节点发布 **`HumanPose`**。

**流程**：默认 **`autostart:=false`**，需 **`/auto_position/control`** `start` 或 **`autostart:=true`**。

**操作**：

```bash
ros2 launch exercise_engine_pkg auto_position.launch.py
# 找位慢转（示例，与 --show-args 中声明名一致）
ros2 launch exercise_engine_pkg auto_position.launch.py search_angular_z:=0.12
ros2 topic pub --once /auto_position/control std_msgs/msg/String "{data: 'start'}"
```

---

## 运行后验证

**作用**：确认图像、计数与找位状态。

**流程**：浏览器看板；`ros2 topic` 查看频率与内容。

**操作**：

- 浏览器：`http://<设备IP>:8090/`（`web_dashboard`）；部分环境有 `/stream` MJPEG。
- 话题：`/pose_image`、`pose_landmarks`、`/situp_count`、`/auto_position/status`（如 `searching`/`ready`/`failed`）。
- 计数受 **`situp_control`**（`start`/`stop`）与 **`start_stopped`** 影响，与 `bringup_pkg`、`voice_pkg` 一致。

---

## 常用 Launch 参数

**作用**：联调与生产差异化配置。

**流程**：`--show-args` 查看全部。

**操作**：

| 参数 | 适用 | 含义 |
|------|------|------|
| `use_backend_config` | `situp_counter`、`situp_with_auto_position` | 是否加载 `backend_config.json` |
| `backend_config_path` | 同上 | JSON 路径 |
| `start_stopped` | 同上 | `true` 时等 `situp_control` 再计 |
| `use_pose_scan` | `situp_with_auto_position`、`auto_position` | 是否发 `/puppy_control/pose` 做俯仰扫描 |
| `auto_position_autostart` | `situp_with_auto_position` | 是否启动立即找位 |
| `search_timeout_sec` | 找位相关 | SEARCHING 超时 → status 含 `failed`；**`<=0` 不判超时**（以节点实现为准） |
| `search_angular_z` | `situp_with_auto_position`、`auto_position` | **SEARCHING** 段 `/cmd_vel_nav` 的 **`angular.z`（rad/s）**；`auto_position` 节点默认 `0.28`，过大会易漏检。 |
| `search_yaw_segment_sec` | 同上 | 每段**同向旋转**持续秒数，默认 `2.0`；略增利于视觉连续帧。 |
| `max_angular_z` | 同上 | **对中**阶段角速度限幅（**rad/s**），默认 `0.35`；与搜索段独立。 |
| `autostart` | `auto_position` | 同找位是否自启 |
| `human_pose_topic` | `auto_position` | `HumanPose` 订阅名 |

```bash
ros2 launch exercise_engine_pkg situp_with_auto_position.launch.py --show-args
# 不判 SEARCHING 超时（需节点支持 search_timeout_sec<=0）
ros2 launch bringup_pkg situp_with_motion_stack.launch.py search_timeout_sec:=0.0
```

---

## 常见问题

**作用**：快速排障。

**流程**：配置、运动栈、相机三类为主。

**操作**：

- `web_dashboard` 报缺 `PUPPY_DEVICE_USER`：`use_backend_config:=false` 或先 `source .env`。
- 找位狗不动：是否已起 **`puppy_motion_stack`**；`auto_position_autostart`；或手动 `pub` `auto_position/control` `start`。
- 找位转太快、人体/关节点总检不出：在对应 launch 中下调 **`search_angular_z`**（如 `0.10`～`0.16` **rad/s**），或略增 **`search_yaw_segment_sec`**；语音全流程见 [bringup_pkg README](../bringup_pkg/README.md) 的 **找位搜索阶段转速** 与 `search_angular_z` 参数表。亦可直接给 **`auto_position` 节点** 设参（`ros2 param set /auto_position search_angular_z 0.12`，名称以 `ros2 node list` 为准）。
- 无图像：摄像头占用、`camera_id`；`ros2 topic hz /pose_image`。

---

## 节点与可执行文件

**作用**：了解可执行名与职责。

**流程**：见下表；离线/测试工具在表末。

**操作**：

| 命令 | 说明 |
|------|------|
| `pose_detector` | MediaPipe → `pose_landmarks`、`pose_image` |
| `situp_counter` | 订阅 landmarks → `situp_count`、`situp_status` |
| `web_dashboard` | HTTP 8090 + 可选 MJPEG、WS |
| `human_pose_bridge` | landmarks → **`/perception/human_pose`**（`HumanPose`），不双开摄像头 |
| `auto_position` | `HumanPose` → `/cmd_vel_nav`、`/puppy_control/pose`；`auto_position/status` |
| `video_situp_test` | 离线视频测计数 |

---

## 自动找位控制约定（`plan.md`）

**作用**：生产编排由 MQTT/语音等在合适时机启动找位。

**流程**：`auto_position/control` = `start` 才进入 SEARCHING（除非 `autostart`/`auto_position_autostart` 为 true）。`task_manager_pkg` 可发 start。

**操作**：

- 组合 launch 默认 `auto_position_autostart:=true`（联调）。
- 与编排并存：`auto_position_autostart:=false`。
- 手动：`ros2 topic pub --once /auto_position/control std_msgs/msg/String "{data: 'start'}"`

话题名可在节点参数改：`control_topic`、`status_topic`。

---

## 自动找位与四足栈

**作用**：真机运动由 `puppy_control` 消费 `/cmd_vel_nav` 与 Pose。

**流程**：先 **`puppy_motion_stack`** 再本包；一条命令见 `bringup_pkg` `situp_with_motion_stack.launch.py`。

**操作**：无硬件时 `use_pose_scan:=false`，`/cmd_vel_nav` 可能无订阅属预期。

---

## 依赖

**作用**：声明 ROS 与 Python 依赖。

**流程**：`human_pose_bridge` 使用 `perception_pkg` 的 `human_pose_builder`。

**操作**：ROS：`rclpy`、`sensor_msgs`、`cv_bridge`、`robot_msgs`、`geometry_msgs`、`puppy_control_msgs`、`perception_pkg`；Python：`opencv-python`、`mediapipe`、`numpy`、`websocket-client`。

---

## 摄像头

**作用**：多相机/话题细节。

**流程**：见同目录 **`README_CAMERA.md`**。

**操作**：打开 [README_CAMERA.md](README_CAMERA.md)。

---

## 与 `perception_pkg` 的关系

**作用**：避免双相机或重复算法。

**流程**：`pose_detector` 发 **PoseLandmarks**；`human_pose_node` 发 **HumanPose**；计数用 landmarks；`situp_with_auto_position` 用 **`human_pose_bridge`** 从 landmarks 生成 `HumanPose` 给 `auto_position`，无需再跑独立 `human_pose_node` 占第二路相机。

**操作**：按场景选单一路径或 bridge。

---

## 后端配置与环境变量

**作用**：`use_backend_config:=true` 时 `web_dashboard` 等加载 `config_loader`。

**流程**：需 **`PUPPY_DEVICE_*`、`PUPPY_MQTT_*`** 等；本地可关后端加载。

**操作**：与 `bridge_pkg` 组合时注意默认策略一致，避免未配环境崩溃。

**补充（终端 COS 上传）**：`config/backend_config.json` 中 **`backend.api_paths`** 可配置 **`sts_token`**、**`video_notify`**（路径与后端一致）。**`BackendAdapter.post_json_to_api_path(path_key, payload)`** 按上述键拼 `http_base_url` 并 **POST JSON**，带 Bearer 与 **401 自动重登**，供 `video_upload_pkg` 等调用；详见仓库内《视频上传-对接文档》。
