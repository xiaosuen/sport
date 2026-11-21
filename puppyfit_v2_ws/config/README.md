# 终端后端配置（`backend_config.json`）

本目录存放 PuppyFit **终端侧**连接后端 HTTP / MQTT 的 JSON 配置。敏感字段（账号密码）**不写入文件**，通过环境变量注入，由 `pose_counter.core.config_loader` 在加载时校验并合并。

## 环境变量（必填）

| 变量名 | 对应配置项 | 说明 |
|--------|------------|------|
| `PUPPY_DEVICE_USER` | `auth.username_env` | 后端 HTTP 登录用户名（如教师账号） |
| `PUPPY_DEVICE_PASS` | `auth.password_env` | 后端 HTTP 登录密码 |
| `PUPPY_MQTT_USER` | `mqtt.username_env` | MQTT 用户名 |
| `PUPPY_MQTT_PASS` | `mqtt.password_env` | MQTT 密码 |

可选：通过 `PUPPY_BACKEND_CONFIG` 指定其它路径的配置文件（绝对路径或相对路径）。

## MQTT：`broker_port` 与 `use_tls`

仓库内默认与**当前现网 Broker**（`122.51.12.83`）一致：

- **`broker_port`: `1883`**，**`use_tls`: `false`**（明文 TCP）。

现场排查：

```bash
nc -zv 122.51.12.83 1883   # 应 succeed
nc -zv 122.51.12.83 8883   # 若 Connection refused，说明该主机未监听 TLS 端口，勿配 8883
```

若以后服务端开放 **TLS**（常见 **8883**），再在 `backend_config.json` 中改为对应端口并设 **`use_tls`: `true`**，并确保证书链可用。`mqtt_bridge` 等组件可通过 launch 参数覆盖 `broker_port` / `use_tls`，需与这里保持一致。

## 联调冒烟

在设置好上述环境变量后，于 `puppyfit_ws` 目录执行：

```bash
python3 scripts/smoke_test_backend.py --config puppyfit_ws/config/backend_config.json --mqtt-listen-sec 10
```

（若当前工作目录已是 `puppyfit_ws`，则 `--config` 可写 `config/backend_config.json`。）

## 与浏览器「实时监控」F12 报错的关系（勿混两条 WebSocket）

| 角色 | 典型 URL | 说明 |
|------|-----------|------|
| **终端（本配置）** | `ws://122.51.12.83:8000/ws/camera/puppy_001` | `backend.ws_camera_base_url` + `device_id`，由 `monitor_ws_bridge` 等**推流/心跳**到后端。树莓派日志里「监控 WebSocket 已连接」指这条。 |
| **浏览器（Dashboard）** | `ws://122.51.12.83/api/monitor/ws/<用户名>?token=...` | **无 `:8000`**，走站点根路径（常见 80/443 + 反代）。F12 若报这条失败，是**用户侧拉流**未建立，与终端是否连上 `:8000/ws/camera` **不是同一连接**。 |

因此：**终端连上 `8000/ws/camera` 仍可能出现页面黄条「实时监控连接失败」**——需在服务器上检查 Nginx（或同类）是否对 `/api/monitor/ws` 做了 WebSocket 升级转发（`Upgrade`、`Connection`）到实际 API 进程，以及 HTTPS 页面是否误用 `ws://`（混合内容被拦）。**勿**把 `ws_camera_base_url` 改成 `/api/monitor/ws/...`，除非后端明确约定设备也走该路径。
