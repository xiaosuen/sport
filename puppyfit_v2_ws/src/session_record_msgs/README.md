# session_record_msgs

**本包整体作用**：定义仰卧起坐 **会话录像** 链路的 **开/停/落盘完成消息**（`SessionRecordStart` / `SessionRecordStop` / `SessionRecordDone`），使 `task_manager_pkg`、`voice_pkg`、`video_record_pkg`、`video_upload_pkg` 仅通过话题与消息弱耦合协作。

下文对 **编译**、**话题约定**、**消息语义** 给出 **作用**、**流程**、**操作**。

---

## 编译

**作用**：生成 `session_record_msgs` 接口供录像节点与编排节点引用。

**流程**：本包无运行期节点，仅需被依赖包编译前通过 `colcon` 构建。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select session_record_msgs
source install/setup.bash
```

---

## 消息与字段

**作用**：保证「开始录」与「结束录」使用同一 `session_id`，避免错停或漏停。

**流程**：编排侧在适当时机发 `SessionRecordStart`；`counting_tts` 在「计时结束」播报完成后再发 `SessionRecordStop`（同 `session_id`）；`session_video_record` 仅在 Start–Stop 区间内写 MP4。

**操作**：对接时阅读下表；字段 `tag` 预留扩展，可为空。

| 消息 | 用途 |
|------|------|
| `SessionRecordStart` | 编排节点在 `situp_control=start` **之前**发布，携带 `session_id` |
| `SessionRecordStop` | `counting_tts` 在 **「计时结束」播报完成**（`on_done`）后发布，携带**相同** `session_id` |
| `SessionRecordDone` | **`session_video_record`** 在 MP4 **落盘成功**（ffmpeg 退出码 0、文件非空）后发布；携带 `session_id`、`file_path`、`file_size`、`duration_sec`（未知时常为 `-1.0`），供 COS 上传等订阅 |

---

## 默认话题名

**作用**：与 `bringup_pkg`、`video_record_pkg` 默认参数一致，减少配置。

**流程**：各节点通过 ROS 参数覆盖话题名；空字符串可表示关闭该侧 pub/sub。

**操作**：默认常为 `session/record_start`、`session/record_stop`；**`SessionRecordDone`** 默认发布话题为 **`session/record_done`**（由 `video_record_pkg` 参数 `record_done_topic` 配置，空则不发）。整机录像与上传见 [bringup_pkg/README.md](../bringup_pkg/README.md)、[video_record_pkg/README.md](../video_record_pkg/README.md)、[video_upload_pkg/README.md](../video_upload_pkg/README.md)。
