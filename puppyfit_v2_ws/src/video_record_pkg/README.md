# video_record_pkg

**本包整体作用**：在 **`SessionRecordStart` → `SessionRecordStop`** 时间窗内，订阅 **`sensor_msgs/Image`**（默认与看板同源 **`/pose_image`**），经 **FFmpeg** 编码写入 **H.264 MP4**；与编排、语音包仅通过 `session_record_msgs` 解耦。

下文对 **依赖**、**运行节点**、**与 bringup 集成** 给出 **作用**、**流程**、**操作**。

---

## 依赖与环境

**作用**：保证录像进程可调用编码器且图像能解码。

**流程**：依赖 `session_record_msgs`、`cv_bridge`、`sensor_msgs`；系统需安装 **`ffmpeg`**；树莓派可选用 `h264_v4l2m2m` 减轻 CPU。

**操作**：安装 `ffmpeg` 并确认用户在 `video` 组（若使用 V4L2 编码节点）；OpenCV 由 `cv_bridge` 间接依赖。

---

## 节点 `session_video_record`

**作用**：按开停消息与 `session_id` 写文件 `{prefix}_{session_id}_{unix}.mp4`；图像 QoS depth=1 丢旧帧防积压。

**流程**：收到 Start → 首帧后启动 FFmpeg 子进程 stdin 写 BGR rawvideo；收到匹配 Stop → 关 stdin 并等待 FFmpeg 退出；**若 ffmpeg 成功且文件非空**，则发布 **`SessionRecordDone`**（见 `session_record_msgs`）。

**操作**（单独调试）：

```bash
source /opt/ros/humble/setup.bash
source /path/to/puppyfit_v2_ws/install/setup.bash
ros2 run video_record_pkg session_video_record --ros-args \
  -p output_dir:=/tmp/rec_test \
  -p record_start_topic:=session/record_start \
  -p record_stop_topic:=session/record_stop
```

另开终端发布 `SessionRecordStart` / `Stop` 或先起 `pose_detector` 提供 `/pose_image`。

| 参数 | 默认 | 说明 |
|------|------|------|
| `record_start_topic` | `session/record_start` | 与编排、`counting_tts` 一致 |
| `record_stop_topic` | `session/record_stop` | 停录须 **session_id 与本轮 start 一致** |
| `image_topic` | `/pose_image` | 与 Web 看板同源，避免抢摄像头 |
| `output_dir` | （必填） | 绝对路径；`bringup_pkg` launch 常设为 `<ws>/record_video` |
| `fps` | `20.0` | 写入容器的标称帧率 |
| `file_prefix` | `situp` | 文件名前缀 |
| `ffmpeg_path` | `ffmpeg` | 可执行路径 |
| `video_encoder` | `libx264` | `libx264` 或硬件 `h264_v4l2m2m` |
| `record_done_topic` | `session/record_done` | 发布 **`SessionRecordDone`** 的话题名；**空字符串** 表示不发布（仅本地录像） |

---

## 与 COS 上传衔接

**作用**：落盘完成后由 `video_upload_pkg` 订阅 **`SessionRecordDone`**，执行 STS → 直传 COS → notify，与编排/语音无直接依赖。

**流程**：默认 `record_done_topic` 与上传节点一致；需后端实现 STS/notify 接口，并安装 `cos-python-sdk-v5`。

**操作**：见 [video_upload_pkg/README.md](../video_upload_pkg/README.md)。

---

## 与 `situp_voice.launch.py` 集成

**作用**：整机一键开启会话录像，输出目录由 launch 传入。

**流程**：`bringup_pkg` 在 `enable_session_record:=true` 时拉起本节点并配置话题与 `output_dir`。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice.launch.py enable_session_record:=true
```

硬件 H.264（设备可用时）：

```bash
ros2 launch bringup_pkg situp_voice.launch.py enable_session_record:=true session_video_encoder:=h264_v4l2m2m
```

可选：`record_output_dir:=/path/to/dir`。
