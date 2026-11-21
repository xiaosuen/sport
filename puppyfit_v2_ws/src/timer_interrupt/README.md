# timer_interrupt

**本包整体作用**：提供 **通用定时器**：倒计时结束后向可配置的 **`std_msgs/String` 控制话题** 发布一次 **`"stop"`**，使对应运动计数节点停止计数（进程不退出）；通过 `control_topic`、`exercise_name` 与具体项目解耦，可扩展到俯卧撑等。

下文对 **编译**、**典型 launch**、**通用 launch**、**命令行节点**、**参数与扩展** 给出 **作用**、**流程**、**操作**。

---

## 编译

**作用**：安装 `timer` 可执行文件与 launch 文件。

**流程**：工作空间内 `colcon build` 后 source；计数侧需已有订阅 `*_control` 的节点（如 `exercise_engine_pkg` 的 `situp_counter`）。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select timer_interrupt
source install/setup.bash
```

---

## `situp_with_timer_launch.py`（仰卧起坐 + 定时）

**作用**：同时起仰卧起坐相关栈与定时器，到时向 `situp_control` 发 `stop`（具体包含节点以 launch 为准）。

**流程**：定时器节点按 `duration_sec` 倒计时 → 发布 `"stop"` → `situp_counter` 停止计数。

**操作**：

```bash
ros2 launch timer_interrupt situp_with_timer_launch.py
ros2 launch timer_interrupt situp_with_timer_launch.py duration_sec:=30
```

---

## `pushup_with_timer_launch.py`（扩展示例）

**作用**：当存在订阅 `pushup_control` 的俯卧撑计数节点时，复用同一定时逻辑。

**流程**：与仰卧起坐相同，仅控制话题名不同。

**操作**：

```bash
ros2 launch timer_interrupt pushup_with_timer_launch.py
ros2 launch timer_interrupt pushup_with_timer_launch.py duration_sec:=60
```

---

## `timer_launch.py`（任意运动）

**作用**：只启动定时器，通过参数指定控制话题与显示用运动名。

**流程**：到时向 `control_topic` 发 `"stop"`。

**操作**：

```bash
# 仰卧起坐（默认）
ros2 launch timer_interrupt timer_launch.py

# 俯卧撑
ros2 launch timer_interrupt timer_launch.py control_topic:=pushup_control exercise_name:=俯卧撑

# 自定义时长
ros2 launch timer_interrupt timer_launch.py duration_sec:=90 control_topic:=pushup_control exercise_name:=俯卧撑
```

---

## 仅启动 `timer` 节点

**作用**：不通过 launch，直接调参运行。

**流程**：与 launch 等价，便于脚本化。

**操作**：

```bash
ros2 run timer_interrupt timer --ros-args -p duration_sec:=60 -p control_topic:=situp_control -p exercise_name:=仰卧起坐
# 俯卧撑示例
ros2 run timer_interrupt timer --ros-args -p duration_sec:=60 -p control_topic:=pushup_control -p exercise_name:=俯卧撑
```

---

## 参数与话题约定

**作用**：统一 `start` / `stop` 字符串协议，便于多运动复用。

**流程**：定时器**发布** `control_topic`（默认 `situp_control`），类型 `std_msgs/String`；计数节点订阅后：`"stop"` 停止计数，`"start"` 可恢复。

**操作**：参数表如下；扩展新运动时只需新计数节点订阅新话题名，**无需改**本包代码。

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `duration_sec` | double | 60.0 | 定时时长（秒） |
| `control_topic` | string | `situp_control` | 控制话题名 |
| `exercise_name` | string | `仰卧起坐` | 日志展示用 |

---

## 停止后恢复计数

**作用**：定时器只发一次 `"stop"`；若需再计，需显式 `"start"`。

**流程**：向同一控制话题发布 `start`。

**操作**：

```bash
ros2 topic pub --once /situp_control std_msgs/msg/String "{data: 'start'}"
ros2 topic pub --once /pushup_control std_msgs/msg/String "{data: 'start'}"
```

---

## 扩展其它运动

**作用**：保持 `timer_interrupt` 通用，仅扩展计数节点与 launch 参数。

**流程**：实现新计数节点并订阅 `xxx_control`，协议与仰卧起坐一致；启动定时器时传 `control_topic:=xxx_control`。

**操作**：参考 `timer_launch.py` 与 `pushup_with_timer_launch.py`。
