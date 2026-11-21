# sdk

**本包整体作用**：提供可 **`import` 的 Python 模块集合**（板卡串口协议、相机封装、逆运动学辅助等），供工作空间内其它包或离线脚本复用；**不是**带 `ros2 run` 入口的 ROS 节点包（`setup.py` 未注册 `console_scripts`）。

下文对 **代码内容**、**使用方式**、**依赖** 给出 **作用**、**流程**、**操作**。

---

## 模块内容

**作用**：把与硬件/算法相关的可复用逻辑从 ROS 节点中剥离，便于单元测试与多包共享。

**流程**：按功能分文件实现；与 `ros_robot_controller` 包内 SDK 可能并存，请按实际硬件选用对应实现。

**操作**：主要入口示例：

- `sdk/ros_robot_controller_sdk.py`：STM32 串口协议与 `Board` 类。
- `sdk/common.py`、`Camera.py`、`InverseKinematics.py`、`ArmMoveIK.py` 等：通用算法与外设封装。

---

## 使用方式

**作用**：在已编译工作空间中让 Python 能找到 `sdk` 包。

**流程**：依赖本包的节点由 `ament_python` 安装路径解析；独立脚本可设 `PYTHONPATH` 或 `pip install -e`。

**操作**：

```python
from sdk.ros_robot_controller_sdk import Board
```

---

## 依赖

**作用**：声明运行本包各子模块所需的第三方库。

**流程**：按实际 `import` 安装（如 `pyserial`、`cv2`、`numpy`、`yaml`）。

**操作**：缺包时按报错补装；与四足/机械臂联调前确认串口权限与设备路径。
