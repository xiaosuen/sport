# video_upload_pkg

**本包整体作用**：在会话 **MP4 落盘** 后，按对接文档完成 **STS 临时密钥 → 直传腾讯云 COS → POST `/api/video/notify`**；与 `video_record_pkg` 仅通过 **`SessionRecordDone`** 话题解耦，HTTP 登录与 401 重登复用 **`exercise_engine_pkg.BackendAdapter`**。

下文对 **依赖**、**节点**、**配置**、**与 bringup 集成**、**单独测试** 给出 **作用**、**流程**、**操作**。

---

## 依赖与环境

**作用**：保证能调后端 STS/notify，并能向 COS 写入对象。

**流程**：依赖 `rclpy`、`session_record_msgs`、`std_msgs`、`exercise_engine_pkg`；需 **`backend_config.json`** 中设备与 **`PUPPY_DEVICE_*`**（或其它与 `config_loader` 一致的登录环境）；Python 需安装 **`cos-python-sdk-v5`**。

**操作**：

```bash
pip install --user cos-python-sdk-v5
```

未安装时节点会记录错误日志并无法完成 COS 步骤。

---

## 节点 `video_cos_upload`

**作用**：订阅 **`SessionRecordDone`**（默认话题 **`session/record_done`**），在后台线程中执行 STS → 上传 → notify；可选向 **`upload_status_topic`** 发布 JSON 状态字符串。

**流程**：收到消息后**在回调内拷贝** `session_id` / `file_path` / `duration_sec` 再进后台线程；校验本地文件 → `post_json_to_api_path("sts_token", …)` → COS `put_object` 或分片 **`upload_file`**（与 STS、notify 共用 **`max_retries`** / **`retry_delay_sec`** 退避）→ `post_json_to_api_path("video_notify", …)`。

**操作**（单独调试，需已 `source install/setup.bash`）：

```bash
ros2 run video_upload_pkg video_cos_upload --ros-args \
  -p backend_config_path:=/path/to/puppyfit_v2_ws/config/backend_config.json
```

另开终端可 **`ros2 topic pub`** 一条 **`SessionRecordDone`**（`file_path` 指向已有 MP4）做联调，无需跑完整录像链。

| 参数 | 默认 | 说明 |
|------|------|------|
| `backend_config_path` | （必填） | `backend_config.json` 绝对路径 |
| `record_done_topic` | `session/record_done` | 与 `session_video_record` 的 `record_done_topic` 一致 |
| `upload_status_topic` | `""` | 非空则发布 `std_msgs/String`，内容为 JSON：`session_id` / `status` / `detail` |
| `default_user_id` | `""` | notify 载荷中的 `user_id` |
| `default_task_id` | `""` | 非空时写入 notify |
| `max_retries` | `3` | STS、**COS 上传**、notify 的重试次数 |
| `retry_delay_sec` | `2.0` | 重试间隔基数（可乘以尝试序号） |
| `delete_local_after_upload` | `false` | 成功后是否删除本地 MP4 |
| `cos_multipart_threshold_bytes` | `20971520` | 超过该字节数走分片上传 |

---

## 配置 `backend_config.json`

**作用**：与全终端共用 **`http_base_url`**、**`device.device_id`**、**`auth`** 登录；并声明 STS/notify 路径。

**流程**：在 **`backend.api_paths`** 中增加（若与后端一致可保持默认）：

- **`sts_token`**：如 `/api/sts/token`
- **`video_notify`**：如 `/api/video/notify`

**操作**：编辑仓库内 `config/backend_config.json`；launch 通过 **`backend_config_path`** 传入同一文件。

---

## 与 `situp_voice_full.launch.py` 集成

**作用**：整机一条命令同时开启 **`session_video_record`** 与 **`video_cos_upload`**。

**流程**：**`enable_session_record:=true`** 且 **`enable_result_upload:=true`** 时，`bringup_pkg` 会 Include 上传节点并传入 **`backend_config_path`**；上传订阅的 **`record_done_topic`** 与录像节点默认一致（`session/record_done`）。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py \
  enable_session_record:=true \
  enable_result_upload:=true \
  backend_config_path:=/path/to/puppyfit_v2_ws/config/backend_config.json
```

---

## 编译

**作用**：生成可执行 **`video_cos_upload`**。

**流程**：先编 **`session_record_msgs`**，再编本包。

**操作**：

```bash
source /opt/ros/humble/setup.bash
cd /path/to/puppyfit_v2_ws
colcon build --packages-select session_record_msgs video_upload_pkg
source install/setup.bash
```

本包含 **`setup.cfg`**，将入口脚本安装到 **`install/video_upload_pkg/lib/video_upload_pkg/`**（与同工作空间的 `video_record_pkg`、`bridge_pkg` 一致），**`ros2 run`** 与 **`ros2 pkg executables`** 才能识别。若你曾用无 `setup.cfg` 的旧树编译过，可删掉 `build/video_upload_pkg` 与 `install/video_upload_pkg` 后再编，避免残留 `bin/` 旧路径。

