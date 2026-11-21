# puppy_joy_teleop

**本包整体作用**：将 Linux **`sensor_msgs/Joy`**（`joy_node`）映射为 **PuppyPi 四足** 可消费的 **`puppy_control_msgs/Velocity`**（默认 **`/puppy_control/velocity_move`**，不经35 cm/s 门槛）或 **`geometry_msgs/Twist`**（**`/cmd_vel_nav`**）；可选经 **`/puppy_control/pose`** 用摇杆/肩键调节 **height** 与 **pitch**。

下文对 **一键 launch**、**依赖**、**编译**、**参数**、**映射与校准**、**排查** 给出 **作用**、**流程**、**操作**。

---

## `puppy_joy_teleop.launch.py`

**作用**：默认启动 **`puppy_motion_stack`**（`ros_robot_controller` + `puppy_control`）+ `joy_node` + `joy_teleop_node`，一条命令手柄遥控。

**流程**：`joy_node` 发布 `/joy` → 本节点按频率映射为速度/姿态指令 → `puppy_control` 执行。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
source install/setup.bash
ros2 launch puppy_joy_teleop puppy_joy_teleop.launch.py
```

已自启四足栈、只要手柄映射时：

```bash
ros2 launch puppy_joy_teleop puppy_joy_teleop.launch.py start_puppy_stack:=false
```

示例：`joy_dev:=1`。

**说明**：默认 `output_mode=velocity_move` 发 **`/puppy_control/velocity_move`**；`twist_nav` 发往 `/cmd_vel_nav`。右摇杆垂直可调 **height**；**L1/L2** 调 **pitch**（与 `puppy_control` 中 `stance_config` 一致）。详见下文参数表。

---

## 依赖：`ros-humble-joy`

**作用**：系统提供 `joy` 包供 `joy_node` 使用。

**流程**：`apt install`；部分镜像对 `ros-humble-joy` 返回 403 时可换官方源。

**操作**：

```bash
sudo apt update
sudo apt install ros-humble-joy
```

### 安装时清华源 403

**作用**：改用 `packages.ros.org` 等可用源安装 ROS deb。

**流程**：编辑 `/etc/apt/sources.list.d/ros2-latest.list`，将镜像改为官方（`jammy main`）；`apt-get update` 后重装。

**操作**（`arm64` 示例，其它架构按需改 `arch`）：

```text
deb [arch=arm64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu jammy main
```

```bash
sudo apt-get update
sudo apt install ros-humble-joy
```

---

## 编译

**作用**：安装 `joy_teleop_node` 与 launch。

**流程**：依赖已编译的 `puppy_control_msgs`。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select puppy_control_msgs puppy_joy_teleop --symlink-install
source install/setup.bash
```

---

## Launch 参数（摘要）

**作用**：匹配手柄设备号、输出模式与话题名。

**流程**：launch 将参数传给 `joy_node` 与 `joy_teleop_node`。

**操作**：

| 参数 | 默认 | 说明 |
|------|------|------|
| `start_puppy_stack` | `true` | `true` 时含板卡 + `puppy_control` |
| `joy_dev` | `0` | `joy_node` 的 `device_id` |
| `output_mode` | `velocity_move` | `velocity_move` 或 `twist_nav` |
| `velocity_move_topic` | `/puppy_control/velocity_move` | `Velocity` 输出 |
| `cmd_vel_topic` | `/cmd_vel_nav` | 仅 `twist_nav` 时 |
| `joy_topic` | `/joy` | 订阅 `Joy` |
| `pose_topic` | `/puppy_control/pose` | height/pitch 用的 `Pose` |
| `enable_height_control` | `true` | 右摇杆垂直调 height |
| `axis_height` | `3` | 常见 RY 为 3 |
| `height_axis_scale` | `-1.0` | 方向反了改为 `1.0` |
| `height_only_when_linear_idle` | `true` | 左摇杆前后在死区内才调高度 |
| `enable_pitch_control` | `true` | L1 抬头 / L2 低头 |
| `button_pitch_up` | `6` | L1 |
| `axis_pitch_down` | `5` | L2 扳机轴 |
| `pitch_only_when_linear_idle` | `true` | 与高度类似 |

---

## `joy_teleop_node` 参数（可 `--ros-args` 或 yaml）

**作用**：细调轴号、死区、限速与姿态积分。

**流程**：定时发布保证摇杆静止时仍有指令；`stale_timeout_sec` 默认 **0**（避免 joy 不发包时一直发零）。

**操作**（常用项，完整默认见源码）：

| 参数 | 默认 | 说明 |
|------|------|------|
| `output_mode` | `velocity_move` | 见上 |
| `axis_linear` | `1` | 前后 |
| `axis_angular` | `0` | 左右转向 |
| `invert_linear` / `invert_angular` | `false` | 方向反了改 `true` |
| `velocity_move_max_cm_s` | `28.0` | 满杆 \|x\|（cm/s），内部再限 ±35 |
| `scale_angular` | `0.85` | 角速度系数（rad/s） |
| `deadzone` | `0.12` | 轴死区 |
| `publish_rate` | `30.0` | Hz |
| `stale_timeout_sec` | `0.0` | 正数时无新 Joy 超时发停；摇杆保持可能无包，慎用 |
| `debug_log_throttle_sec` | `0.0` | 设 `1.0` 可节流打日志 |
| `require_enable_button` | `false` | 使能键 |
| `enable_button` | `4` | 按钮索引 |
| `height_rate_cm_per_s` | `5.0` | 高度变化速率 |
| `height_min` / `height_max` | `-15` / `-5` | 与 `PoseFun` 一致 |
| `height_initial` | `-10.0` | 高度积分初值 |
| `pose_roll` / `pose_pitch` / `pose_yaw` | `0` / `0` / `0` | 发 Pose 时 yaw 固定 0 |
| `pitch_rate_rad_per_s` 等 | 见默认 | L1/L2 俯仰速率 |

单独运行映射节点（已另有 `joy_node`）：

```bash
ros2 run puppy_joy_teleop joy_teleop_node --ros-args \
  -p output_mode:=twist_nav -p axis_angular:=3
```

---

## 按键与轴映射（本机已 `echo /joy` 核对）

**作用**：类 PlayStation 布局 USB 手柄；换设备务必重新 `echo /joy`。

**流程**：`axes`/`buttons` 下标从 0 开始；连续量优先用 L2 轴而非 `buttons`。

**操作**：本机观测摘要如下（详见原设备）。

### 本机观测到的原始布局

| 字段 | 下标 | 静止/典型值 | 说明 |
|------|------|-------------|------|
| `axes` | 0–3 | 约 `0.004` | 摇杆轴 |
| `axes` | 4 | `1.0` | 肩位/扳机通道等 |
| `axes` | 5 | `1.0` → `-1.0` | **L2** 拉满 |
| `axes` | 6–7 | `0.0` | 保留 |

| 物理键 | ROS 字段 | 下标 | 行为 |
|--------|----------|------|------|
| **L1** | `buttons` | **6** | 按下 1 |
| **L2** | `axes` | **5** | 模拟量优先 |

### `joy_teleop_node` 默认用途

| 物理键 | 默认行为（`enable_*` 为 `true`） |
|--------|----------------------------------|
| **L1** | **抬头**：`Pose.pitch` 增大（限 ±31°） |
| **L2** | **低头**：拉量越大 pitch 减小越快 |

> L1/L2 与右摇杆高度共用 **`/puppy_control/pose`**；`height_only_when_linear_idle` / `pitch_only_when_linear_idle` 可减少与平移耦合；方向反了可改速率符号。

---

## 轴号校准

**作用**：不同手柄 Linux下下标不同。

**流程**：推动摇杆、按键，观察哪一路变化。

**操作**：

```bash
ros2 topic echo /joy --no-arr
```

将 `axis_linear`、`axis_angular`、`axis_height` 等设为对应下标。

---

## 与 `puppy_control` 的衔接

**作用**：保证单位与话题与 `puppy_control` 一致。

**流程**：`velocity_move` 中 `Velocity.x` 为 **cm/s**，`yaw_rate` 为 **rad/s**；`PoseFun` 要求 |roll|、|pitch| ≤ 31°、`yaw==0`、`height ∈ [-15,-5]` 等。

**操作**：`twist_nav` 时 `VelocityFun` 仅在 |x|≤35 cm/s 且 |yaw_rate|≤51° 时 `move()`；本节点在 `twist_nav` 下已做硬限幅。

---

## 手柄无反应排查

**作用**：快速定位订阅/轴号/超时问题。

**流程**：确认 `puppy_control` 在跑、话题有 Subscriber、`stale_timeout_sec` 勿误开、轴号与 `invert_*` 正确。

**操作**：

1. `ros2 node list | grep puppy_control`
2. `ros2 topic info /puppy_control/velocity_move` 应有 **Subscriber: puppy_control**
3. `stale_timeout_sec` 默认 **0**
4. `ros2 topic echo /joy` 核对轴号
5. `-p debug_log_throttle_sec:=1.0`
6. 检查串口/舵机就绪

---

## 权限

**作用**：`joy_node` 需读 `/dev/input/js*`。

**流程**：用户加入 `input` 组或 udev 规则；临时可用 `sudo` 调试。

**操作**：按发行版文档配置；不推荐长期 root 跑节点。

---

## 许可证

Apache-2.0
