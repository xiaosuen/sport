# robot_msgs

**本包整体作用**：提供跨节点、跨功能层复用的 **ROS 2 自定义消息**（姿态关键点、人体聚合态、仰卧起坐计数等），避免各包重复定义导致类型不一致。

下文对 **编译接入** 与 **消息契约** 分别给出 **作用**、**流程**、**操作**。

---

## 编译与接入

**作用**：生成消息接口，供 `exercise_engine_pkg`、`perception_pkg`、`voice_pkg` 等包在 `package.xml` 中依赖。

**流程**：先单独或随工作空间编译本包 → `source install/setup.bash` → 依赖包即可 `from robot_msgs.msg import ...` 或 C++ 等价包含。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select robot_msgs
source install/setup.bash
```

---

## 消息一览（契约摘要）

**作用**：统一感知、运动引擎与编排层之间的数据结构约定。

**流程**：发布方（如 `pose_detector`）与订阅方（如 `situp_counter`）共用下表类型；`Landmark` / `PoseLandmarks` / `SitUpCount` 与历史 **`pose_interface`** 字段对齐。

**操作**：设计新节点时优先复用下表类型，避免再建新 msg 包。

| 消息 | 说明 |
|------|------|
| `HumanPose` | 感知层聚合人体姿态（躯干角、bbox、ready 等） |
| `ExerciseState` | 运动/练习状态与计数摘要 |
| `TaskStatus` | 任务状态与目标次数 |
| `Landmark` | 单关键点：归一化 x/y/z + visibility（MediaPipe 风格） |
| `PoseLandmarks` | 带 `Header` 的关键点数组（通常 33 点） |
| `SitUpCount` | 仰卧起坐计数：count、state、direction、initialized |
