# puppy_control

**四足专用**运动控制 ROS2 包（已去掉机械臂 IK 与专用 PWM 初始化）：订阅速度、姿态、步态、`cmd_vel` 等，经 `servo_controller` 与 **`puppypi_vendor` / `PUPPYPI_CONTROL_PATH`** 驱动 `HiwonderPuppy`；提供服务如回零、自稳开关、动作组执行等。

## 节点

| 可执行名 | 说明 |
|----------|------|
| `puppy_control` | 主控制节点（`puppy_control.puppy:main`） |

## 参数

大量 `PuppyPose_*`、`GaitConfig*` 及 `joint_state_pub_topic` 等由节点声明，默认值与说明见 `puppy_control/puppy.py` 与 `config/puppy_params.yaml`（若使用）。

## Launch

```bash
source install/setup.bash
# 控制板 + 小狗节点（推荐）
ros2 launch puppy_control puppy_motion_stack.launch.py
# 仅小狗节点（需已运行 ros_robot_controller）
ros2 launch puppy_control puppy_control.launch.py
```

## 依赖

- `rclpy`、`puppy_control_msgs`、`ros_robot_controller_msgs`、`puppypi_vendor`（`puppy_kinematics.so` 等）。**不再依赖**工作空间内的 `sdk` 包。
