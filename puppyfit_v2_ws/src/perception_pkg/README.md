# perception_pkg

**本包整体作用**：**感知层**——从本地摄像头或 **`sensor_msgs/Image` 话题** 取图，经 **MediaPipe Pose** 输出 **`robot_msgs/HumanPose`**（及可选调试图像）；与 `exercise_engine_pkg` 中 `pose_detector` + `human_pose_bridge` 链路可并行，按场景二选一或组合。

下文对 **契约**、**编译**、**运行方式**、**摄像头占用排查** 给出 **作用**、**流程**、**操作**。

---

## 话题与消息契约（第一版）

**作用**：固定主输出与可选调试话题，便于 `auto_position` 或其它消费者订阅。

**流程**：每帧发布 `HumanPose`；无检测时仍发布，`detected=false`、`ready_pose=false` 等见下。

**操作**：主输出与可执行名如下。

| 项目 | 值 |
|------|-----|
| 主输出 | `/perception/human_pose`（`robot_msgs/msg/HumanPose`） |
| 调试图像（可选） | `/perception/debug_image`（`sensor_msgs/Image`），默认关闭 |
| 可执行名 | `human_pose_node` |

无检测时（每帧仍发布）：`detected=false`，`ready_pose=false`，`trunk_angle=0.0`，`bbox_area=0.0`，`bbox_center_x=0.5`。

### ROS 参数（摘要）

| 参数 | 说明 | 默认 |
|------|------|------|
| `image_topic` | 非空：订阅该话题；空：本地摄像头 | `""` |
| `camera_id` | 本地摄像头索引 | `0` |
| `camera_frame_id` | 本地模式 frame_id | `camera_optical_frame` |
| `publish_rate` | 本地模式取帧频率 (Hz) | `30.0` |
| `publish_debug_image` | 是否发布 `/perception/debug_image` | `false` |
| `show_debug_window` | OpenCV 弹窗（需 `DISPLAY`） | `false` |
| `min_detection_confidence` / `min_tracking_confidence` | MediaPipe | `0.5` |
| `keypoint_visibility_min` | detected / bbox 统计 | `0.5` |
| `ready_visibility_min` | 双肩+双髋 ready | `0.6` |
| `ready_min_bbox_area` | 归一化 bbox 最小面积 | `0.05` |
| `dy_shoulder_max` | 双肩 y 差上限（归一化） | `0.15` |

### `HumanPose` 字段（MediaPipe 映射摘要）

- `detected`：鼻或任一侧肩 visibility ≥ `keypoint_visibility_min`
- `ready_pose`：在 detected 下，双肩+双髋 ≥ `ready_visibility_min`，且 |yL−yR| < `dy_shoulder_max`，且 bbox_area ≥ `ready_min_bbox_area`
- `trunk_angle`：肩中点相对髋中点的向量与竖直 `(0,-1)` 的夹角，弧度 `[0,π]`；无效时为 0
- `bbox_center_x` / `bbox_area`：对 visibility 足够的点做 AABB- `source`：`mediapipe_pose`

---

## 编译

**作用**：依赖 `robot_msgs` 生成 Python/C++ 接口。

**流程**：先编 `robot_msgs` 再编本包。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select robot_msgs perception_pkg
source install/setup.bash
```

---

## `human_pose_node` / `perception.launch.py`

**作用**：本地摄像头或订阅图像话题运行感知节点。

**流程**：OpenCV / V4L2 取帧 → MediaPipe → 发布 `HumanPose`；与 `v4l2_camera` 并存时应用 `image_topic` 避免独占 `/dev/video0`。

**操作**：

```bash
# 本地摄像头
ros2 run perception_pkg human_pose_node

# 订阅图像话题（例如 v4l2）
ros2 run perception_pkg human_pose_node --ros-args -p image_topic:=/image_raw

# 发布调试图像话题
ros2 run perception_pkg human_pose_node --ros-args -p publish_debug_image:=true

# Launch：默认本机摄像头
ros2 launch perception_pkg perception.launch.py

# Launch：调试 — debug 图 + OpenCV 窗口（需图形环境）
ros2 launch perception_pkg perception.launch.py publish_debug_image:=true show_debug_window:=true

# Launch：只订阅图像（避免与 v4l2_camera 抢设备）
ros2 launch perception_pkg perception.launch.py image_topic:=/image_raw
```

---

## 验证

**作用**：确认频率与字段合理。

**流程**：`echo` / `hz` 查看 `/perception/human_pose`。

**操作**：

```bash
ros2 topic echo /perception/human_pose
ros2 topic hz /perception/human_pose
```

---

## 依赖

**作用**：声明运行期依赖。

**流程**：ROS + pip 包装齐后运行。

**操作**：ROS 2：`rclpy`、`sensor_msgs`、`cv_bridge`、`robot_msgs`；Python：`mediapipe`、`opencv-python`、`numpy`。

---

## 故障：无法打开摄像头 / Device busy

**作用**：解释 Linux 下单进程常独占 `/dev/video0` 的现象并给出解决路径。

**流程**：若已有 `v4l2_camera` 等打开设备，再 `VideoCapture(0)` 会失败。

**操作**：

```bash
sudo lsof /dev/video0
sudo fuser -v /dev/video0
ros2 node list
```

**推荐**：感知节点只订阅 `image_topic:=/image_raw`（与相机节点一致）。**备选**：停占用进程后再独占摄像头。Linux 下节点优先 **V4L2** 打开摄像头以减少 GStreamer 告警。
