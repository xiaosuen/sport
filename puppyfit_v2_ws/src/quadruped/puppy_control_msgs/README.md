# puppy_control_msgs

`puppy_control` 使用的自定义 **消息与服务** 定义包。

## 消息（msg）

| 消息 | 说明 |
|------|------|
| `Velocity` | 速度指令（x、y、yaw_rate 等） |
| `Gait` | 步态参数（overlap_time、swing_time 等） |
| `Pose` | 机体姿态与足式站位相关字段 |
| `SetServo` | 单舵机脉宽与时间 |

## 服务（srv）

| 服务 | 说明 |
|------|------|
| `SetRunActionName` | 运行动作组（名称、是否等待等） |
| `SetFloat64` / `SetFloat64List` / `SetInt64` | 通用数值设置 |

## 构建

```bash
colcon build --packages-select puppy_control_msgs
source install/setup.bash
```

## 依赖

- `std_msgs`；`ament_cmake` + `rosidl_default_generators`。
