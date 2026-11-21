# ros_robot_controller_msgs

**ros_robot_controller** 节点使用的自定义 **消息与服务**：描述板载 LED、蜂鸣器、电机、总线舵机、PWM 舵机、RGB、OLED、按键、SBUS 等状态与设置指令。

## 消息（msg）节选

- 状态/设置：`LedState`、`BuzzerState`、`MotorState`/`MotorsState`、`ButtonState`、`RGBState`/`RGBsState`、`OLEDState`、`Sbus`
- 舵机：`BusServoState`、`SetBusServoState`、`ServosPosition`、`PWMServoState`、`SetPWMServoState`、`GetBusServoCmd`、`GetPWMServoCmd`、`ServoPosition`

## 服务（srv）

- `GetBusServoState`：查询总线舵机状态
- `GetPWMServoState`：查询 PWM 舵机状态

## 构建

```bash
colcon build --packages-select ros_robot_controller_msgs
source install/setup.bash
```

## 依赖

- `std_msgs`；`ament_cmake` + `rosidl_default_generators`。
