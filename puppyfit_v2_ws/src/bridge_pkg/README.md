# bridge_pkg

**本包整体作用**：**外部系统桥接**——MQTT 遥测、HTTP 设备心跳、训练会话 MQTT→本地训练闭环、实时监控 **WebSocket 推流**（设备侧）；与 `exercise_engine_pkg` 的本地8090 看板及浏览器 Dashboard 链路区分；MQTT 逻辑自旧工程 `mqtt_bridge` 迁入。

下文对 **代码布局**、各 **launch**、**监控 WebSocket**、**电池映射** 给出 **作用**、**流程**、**操作**。

---

## Python 包结构（`bridge_pkg/bridge_pkg/`）

**作用**：telemetry / monitor 分目录，launch 共用 `launch_common.py` 等。

**流程**：节点模块与配置默认路径集中，便于组合 launch Include。

**操作**：

- **`telemetry/`**：`telemetry_bridge`（`node.py`）、launch 共用 `launch_common.py`
- **`monitor/`**：`monitor_ws_bridge`、`config_min.py`、`ws_reporter.py`，launch 共用 `launch_common.py` 与 `launch_include.py`
- **`backend_config_default.py`**：`DEFAULT_BACKEND_CONFIG_PATH` 指向 `puppyfit_v2_ws/config/backend_config.json`（换机可用 launch 覆盖）

---

## 编译

**作用**：安装 `telemetry_bridge`、`monitor_ws_bridge`、`training_session_bridge` 等可执行文件。

**流程**：HTTP 心跳复用 `exercise_engine_pkg` 的 `BackendAdapter`；遥测真机电量常需 `ros_robot_controller`。

**操作**：

```bash
cd /path/to/puppyfit_v2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select bridge_pkg exercise_engine_pkg ros_robot_controller
source install/setup.bash
```

---

## `mqtt_telemetry.launch.py`

**作用**：仅起 **MQTT 遥测**（及可选 HTTP 心跳、Include 的 `monitor_ws`）；无控制板时电量多为**模拟**（约 50%）。

**流程**：`telemetry_bridge` 向 `puppy/data/{device_id}` 等主题发 JSON；可选周期 `POST` 设备状态；需环境变量与 `backend_config.json`。

**操作**：

```bash
cd /path/to/puppyfit_v2_ws
set -a && source .env && set +a
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch bridge_pkg mqtt_telemetry.launch.py
```

仅 MQTT、不要 HTTP：`enable_http_heartbeat:=false`。常用覆盖：`device_id`、`broker_host`、`broker_port`、`backend_config_path`、`http_heartbeat_interval_sec`。

**说明**：依赖 `paho-mqtt`；HTTP 默认开时需 `PUPPY_DEVICE_USER` / `PUPPY_DEVICE_PASS`；`load_backend_config` 仍会校验 `PUPPY_MQTT_*`。注册设备：`http_register_on_start:=true`。

---

## `mqtt_telemetry_with_controller.launch.py`

**作用**：**一条命令**起 `ros_robot_controller` + `telemetry_bridge`，后端收到**真实**电池毫伏（串口与板子正常时）。

**流程**：订阅 `/ros_robot_controller/battery`（`UInt16` 毫伏）→ 映射为百分比上报。

**操作**：

```bash
set -a && source .env && set +a
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch bridge_pkg mqtt_telemetry_with_controller.launch.py
```

仿真：`start_ros_robot_controller:=false`。

---

## `mqtt_telemetry_with_joy_teleop.launch.py`

**作用**：**避免双开控制板**——在需要手柄 + 运动栈 + 遥测时，用本 launch 代替同时跑 `puppy_joy_teleop`（自带栈）与 `mqtt_telemetry_with_controller`。

**流程**：板卡只起一份 + `joy` +遥测（及可选 monitor Include）。

**操作**：

```bash
ros2 launch bridge_pkg mqtt_telemetry_with_joy_teleop.launch.py joy_dev:=0
```

只要手柄、不要 `puppy_control`：`start_puppy_stack:=false`。需要监控推流：`enable_monitor_ws:=true`。

---

## `training_session_bridge.launch.py`

**作用**：订阅 MQTT `puppy/control/{device_id}`（`training_session_pending` / `start_training` / `stop_training`），驱动本地 **`situp_control`**，并把计数上报与 HTTP **confirm/complete/error** 闭环。

**流程**：`count_report_interval_sec` 等可调；launch 参数带 `ts_` 前缀避免与遥测 launch 同名冲突。

**操作**：

```bash
ros2 launch bridge_pkg training_session_bridge.launch.py
```

默认参数示例：`count_report_interval_sec:=1.0`、`complete_on_target:=true`。接口：`POST /api/device/training-sessions/{session_id}/confirm|complete|error`。

---

## `monitor_ws.launch.py`

**作用**：**设备侧** WebSocket 客户端连 `{ws_camera_base_url}/{device_id}`，周期 JSON：`type: "frame"`（可选 JPEG base64）、`count`；`type: "heartbeat"`。

**流程**：默认 `enable_monitor_ws:=false` 时不创建节点；需 `websocket-client`；图像要 `cv_bridge`+OpenCV。

**操作**：

```bash
ros2 launch bridge_pkg monitor_ws.launch.py enable_monitor_ws:=true
```

订阅默认：`image_topic=/pose_image`，`count_topic=/situp_count`。配置读 `backend.ws_camera_base_url` 与 `device.device_id`（或 launch 覆盖）；**不**走 `exercise_engine_pkg.load_backend_config` 全量校验。

**勿混两条链路**：终端设备连 `:8000/ws/camera/...`；浏览器 Dashboard 常连 **`/api/monitor/ws`**（经反代）。F12 仅后者失败时查 Nginx/后端，非改 `ws_camera_base_url` 为 `/api/monitor/ws`。

---

## `situp_counter_monitor_cloud.launch.py`

**作用**：**一键**：仰卧起坐计数栈 + **云端推流** + MQTT/HTTP 遥测（与 `mqtt_telemetry_with_controller` 同源组合思路）；默认开监控相关 Include。

**流程**：`ros_robot_controller` + `telemetry_bridge` + `situp` 栈 + `monitor_ws`；已跑 `situp_voice_full` 时不要叠用（避免双开计数），改用 `bringup_pkg/situp_voice_full_with_cloud_monitor.launch.py`。

**操作**：

```bash
cd /path/to/puppyfit_v2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch bridge_pkg situp_counter_monitor_cloud.launch.py
```

`use_backend_config:=false` 常为减轻 `web_dashboard` 未配 `.env` 崩溃；本地看板也要后端时传 `use_backend_config:=true`（可能与 `monitor_ws_bridge` 各占一条设备 WS，视后端策略）。

---

## 与遥测同启时打开监控

**作用**：在已有 `mqtt_telemetry*.launch.py` Include 的前提下打开推流。

**流程**：传 `enable_monitor_ws:=true`。

**操作**：

```bash
ros2 launch bridge_pkg mqtt_telemetry_with_joy_teleop.launch.py enable_monitor_ws:=true
```

`backend_config_path` 默认指向本机 `puppyfit_v2_ws/config/backend_config.json`。覆盖监控侧设备 ID 用 **`monitor_override_device_id`**，勿与 MQTT 的 **`device_id`** 混淆。

---

## 电池（PuppyPi / 控制板）

**作用**：将 `/ros_robot_controller/battery` 毫伏映射为 0–100% 上报。

**流程**：默认 **6.4V→0%**、**8.3V→100%** 线性；无数据约 25s 打 WARN；长期约 **50%** 多为模拟电压中点（未收到真实电池）。

**操作**：调映射：`battery_v_min` / `battery_v_max`。若用 Float32 `/voltage`：`voltage_topic:=/voltage`，`battery_mv_topic:=''`，并设合适 `battery_v_min`/`max`（如 3S 10.5–12.6）。排查：`ros2 topic echo /ros_robot_controller/battery`、`ros2 topic hz ...`。

---

## 规划（以后）

**作用**：记录迭代方向。

**流程**：按需把更多 `monitor_ws` 参数从组合 launch 转发。

**操作**：（暂无强制步骤）
