# puppy_action_show

专门用于 **PuppyPi 动作组表演** 的 ROS2 包：通过话题或服务把 `puppypi_vendor` 里 `puppypi_control/ActionGroups/` 下的 `.d6a` / `.d6ac` 交给 **`puppy_control`** 的 `runActionGroup` 服务执行。

## 依赖

- 已编译并 `source` 工作空间
- 运行表演前需先启动 **`puppy_control`**（否则服务不可用），例如：

  ```bash
  ros2 launch puppy_control puppy_motion_stack.launch.py
  ```

## 启动表演节点

```bash
ros2 launch puppy_action_show action_show.launch.py
```

## 用法

**注意**：必须先启动本包节点（`action_show.launch.py`），否则没有订阅者，`ros2 topic pub` 会一直显示 “Waiting for matching subscription(s)”。

### 1. 话题触发（异步，不阻塞）

```bash
ros2 topic pub --once /puppy_action_show/play std_msgs/msg/String "{data: 'arm_test.d6a'}"
```

若 CLI 仍长时间等待匹配订阅，可先确认：`ros2 topic info /puppy_action_show/play -v` 是否显示 **Subscription count: 1**。  
部分 ROS2 版本可加 `-w 0` 跳过等待（消息可能无人接收，仅作调试）：

```bash
ros2 topic pub -w 0 --once /puppy_action_show/play std_msgs/msg/String "{data: 'arm_test.d6a'}"
```

### 2. 服务调用（可 `wait: true` 等待动作组结束，最长约 30s 由底层决定）

```bash
ros2 service call /puppy_action_show/run puppy_control_msgs/srv/SetRunActionName \
  "{name: 'arm_test.d6a', wait: false}"
```

### 3. 列出已安装的动作组文件（无需 puppy_control）

```bash
ros2 run puppy_action_show list_action_groups
```

节点启动时也会在日志中打印可用文件，并发布一次 **`/puppy_action_show/catalog`**（`std_msgs/String`，每行一个文件名）。

## 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `puppy_run_action_service` | `/puppy_control/runActionGroup` | 底层执行服务 |
| `action_groups_share_pkg` | `puppypi_vendor` | 用于扫描目录的包名 |
| `action_groups_subdir` | `puppypi_control/ActionGroups` | 相对 share 的子路径 |
| `publish_catalog_on_start` | `true` | 启动时发布 catalog |

## 与 quadruped 目录的关系

动作组资源随 **`puppypi_vendor`** 安装到  
`share/puppypi_vendor/puppypi_control/ActionGroups/`。  
本包只负责 **编排与触发**，不复制动作文件。

## 故障排除：话题只能触发一次

若在订阅回调里对**本节点**调用 `spin_until_future_complete`，会占死执行器线程，后续 `play` 与 service client 响应都无法处理。本节点已改为**短睡眠轮询**等待 `call_async` 的 future，可连续多次 `ros2 topic pub`。若上一个动作组仍在执行，底层 `runningAction` 可能拒绝重叠执行，需等当前动作结束或调用 `stopActionGroup`（由 `puppy_control` 侧策略决定）。
