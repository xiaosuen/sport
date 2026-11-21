# ros_robot_controller

**STM32 控制板** ROS2 通信节点：通过串口 SDK 与板卡交互，将 IMU、手柄、SBUS、按键、电池等发布为话题，并将 LED、蜂鸣器、电机、总线/PWM 舵机、OLED、RGB 等订阅指令下发到硬件。

## 节点

- **ros_robot_controller**：主节点（`ros_robot_controller.ros_robot_controller_node:main`），话题名多为相对节点命名空间（如 `~/imu_raw`）。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `imu_frame` | string | imu_link | IMU 消息 `frame_id` |
| `init_finish` | bool | false | 预留/兼容用参数 |

## Launch

```bash
source install/setup.bash
ros2 launch ros_robot_controller ros_robot_controller.launch.py
```

## 依赖

以下路径均以工作空间根目录下的 `ros2_ws` 为前缀（本机示例：`/home/ubuntu/ros2_ws/...`）。若你的 workspace 不在 `ros2_ws`，把前缀换成实际根路径即可。

### 本包内：节点 → SDK（代码依赖）

本包**只提供一个可执行节点** `ros_robot_controller`，入口在节点脚本里；硬件串口协议封装在 SDK 模块中，由节点直接 `import` 使用。

| 依赖方 | 被依赖方 | 关系说明 |
|--------|----------|----------|
| 节点主程序 | 板卡 SDK 模块 | 节点内 `from ros_robot_controller.ros_robot_controller_sdk import Board`，创建 `Board()` 完成串口收发与协议解析；所有 `set_*` / `get_*` 最终都经 SDK 与 STM32 通讯。 |

- **节点脚本（依赖方）**  
  `ros2_ws/src/driver/ros_robot_controller/ros_robot_controller/ros_robot_controller_node.py`  
  类 `RosRobotController`：订阅/发布 ROS 话题与服务，并把消息字段映射为对 `Board` 的调用。

- **SDK 模块（被依赖方）**  
  `ros2_ws/src/driver/ros_robot_controller/ros_robot_controller/ros_robot_controller_sdk.py`  
  类 `Board`：串口帧组包/解析、后台 `recv_task`、各功能队列与 `set_led`、`get_imu` 等 API；**不依赖** `rclpy`，可被非 ROS 脚本单独导入测试。

- **Launch（启动节点，不依赖 SDK 源码）**  
  `ros2_ws/src/driver/ros_robot_controller/launch/ros_robot_controller.launch.py`  
  仅通过 `launch_ros` 启动上述可执行节点；运行期仍会加载节点脚本，因此间接需要节点 + SDK 已安装到当前环境。

依赖关系可概括为：

```text
ros_robot_controller.launch.py
        └── 启动 ──► ros_robot_controller（可执行入口）
                          └── import ──► ros_robot_controller_sdk.Board
```

### 本包依赖的其它 ROS 包（接口定义）

节点话题与服务使用的 `.msg` / `.srv` 来自**同工作空间下的独立功能包**，编译/运行前需一并克隆并 `colcon build`。

| ROS 包名 | 作用 | 源码路径（相对 `ros2_ws`） |
|----------|------|----------------------------|
| `ros_robot_controller_msgs` | `LedState`、`MotorsState`、`Sbus`、`GetBusServoState` 等消息与服务定义 | `src/driver/ros_robot_controller_msgs/` |

节点中的引用示例：`ros_robot_controller_msgs.msg`、`ros_robot_controller_msgs.srv`。

### ROS 2 与标准消息（运行依赖）

由节点与 launch 直接使用（通常随桌面版 ROS 2 或 `ros-base` 等元包安装）：

| 依赖 | 用途 |
|------|------|
| `rclpy` | 节点、`Node`、`spin` |
| `sensor_msgs` | `Imu`、`Joy` |
| `std_msgs` | `Bool`、`UInt16` |
| `std_srvs` | `Trigger`（`~/init_finish`） |
| `launch`、`launch_ros` | `ros_robot_controller.launch.py` |

### Python 第三方（SDK 使用）

| 依赖 | 用途 | 说明 |
|------|------|------|
| `pyserial` | 串口 `Serial` | 由 `ros_robot_controller_sdk.py` 使用；若运行节点报找不到 `serial`，需 `pip install pyserial` 或通过系统包安装。 |

### 系统与设备

- 默认串口设备见 SDK 中 `Board.__init__`（如 `/dev/rrc`）；**udev 规则**等脚本若存在，见本包 `scripts/`（与具体产品配套一致）。

> **说明**：当前仓库里的 `package.xml` 若未列出全部 `<exec_depend>`，仍以实际上下文为准；部署时建议在 `package.xml` 中补全 `rclpy`、`sensor_msgs`、`std_msgs`、`std_srvs`、`ros_robot_controller_msgs`、`launch_ros` 等，以便 `rosdep` 与依赖解析一致。
