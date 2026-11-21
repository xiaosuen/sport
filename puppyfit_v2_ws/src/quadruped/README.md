# quadruped（目录归组）

本目录**仅用于整理路径**，不包含单独的 ROS 包：其下每个子目录仍是独立的 `ament` 包（各自有 `package.xml`）。  
`colcon` 会在 `src/` 下**递归**发现这些包，**包名不变**，`ros2 launch puppy_control ...` 与原先一致。

## 包含的包

| 子目录 | 说明 |
|--------|------|
| [puppypi_vendor](puppypi_vendor/) | `puppypi_control` 运行时（`.so`、动作组等） |
| [ros_robot_controller](ros_robot_controller/) | 控制板桥接节点 |
| [ros_robot_controller_msgs](ros_robot_controller_msgs/) | 控制板消息 |
| [puppy_control](puppy_control/) | 四足运动控制节点 |
| [puppy_control_msgs](puppy_control_msgs/) | 小狗控制消息 |
| [puppy_action_show](puppy_action_show/) | 动作组表演：话题/服务触发 ActionGroups（依赖 `puppy_control`） |

编译、启动方式见上级 [`../README.md`](../README.md)。
