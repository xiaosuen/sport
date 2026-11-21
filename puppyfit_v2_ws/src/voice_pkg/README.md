# voice_pkg

**本包整体作用**：**语音层**——串口/触发唤醒、**Sherpa-ONNX 本地 ASR**、**Piper ONNX / espeak TTS**、仰卧起坐 **计数联动播报**与 **成绩口播**；从旧工程 `puppyfit_ws` 的 `asr`、`tts` 迁入并与 `bringup_pkg`、`exercise_engine_pkg` 话题对接。

下文对 **目录结构**、**典型 launch**、**节点与话题**、**Piper 模型准备**、**代理安装**、**依赖** 给出 **作用**、**流程**、**操作**。

---

## 目录结构

**作用**：快速定位源码与模型。

**流程**：ASR/TTS/唤醒分目录；launch 在 `launch/`；模型在 `models/`。

**操作**：

```
voice_pkg/
├── voice_pkg/
│   ├── asr/           # Sherpa ASR + voice_asr 节点
│   ├── tts/           # Piper ONNX / espeak 队列 + voice_tts、counting_tts
│   ├── wakeup/        # 串口唤醒
│   └── utils/         # 共享路径（如默认模型目录）
├── launch/voice.launch.py
├── launch/situp_timer_tts.launch.py
└── models/...
```

---

## `voice.launch.py`

**作用**：一键拉起语音栈（具体包含节点以 launch 为准），用于联调 ASR/TTS/唤醒。

**流程**：各节点按默认话题互联；整机仰卧起坐更多用 `bringup_pkg`。

**操作**：

```bash
source /opt/ros/humble/setup.bash
source /path/to/puppyfit_v2_ws/install/setup.bash
ros2 launch voice_pkg voice.launch.py
```

---

## `situp_timer_tts.launch.py`

**作用**：**仅计数 + 定时 + 播报**（无完整 ASR 编排），便于无唤醒硬件时测试口播链。

**流程**：订阅 `situp_count` 等与 `exercise_engine_pkg`、`timer_interrupt` 协同。

**操作**：

```bash
ros2 launch voice_pkg situp_timer_tts.launch.py
```

**鼓励语**（与 `counting_tts` 同参数）：本 launch 默认 `encouragement_enabled:=false`、**`encouragement_phrases` 为空**，行为与加功能前一致。需要与 `situp_voice_full` 类似效果时可例如：

```bash
ros2 launch voice_pkg situp_timer_tts.launch.py \
  encouragement_enabled:=true \
  encouragement_interval:=5 \
  encouragement_phrases:="句A|句B|句C"
```

---

## 节点与话题

**作用**：对接编排与其它功能包时查阅订阅/发布约定。

**流程**：`voice_asr` 出 `/asr/text`；`voice_tts` 订阅 `/voice/speak`；`counting_tts` 联动计数与 `tts/speak`；`situp_result_tts` 在 phrase_end 后播成绩（与 `situp_voice_full` 配套）。

**操作**：参数可调 `output_topic`、`speak_topic`、`trigger_topic`、`tts_backend`、`piper_model_path` 等，默认与下表一致。

| 可执行名 | 说明 | 话题 |
|----------|------|------|
| `voice_asr` | sherpa-onnx 本地识别 | 发布 **`/asr/text`**；可选 **`/asr/trigger`**；可选关键词与 **`keyword_mismatch_phrase`**；`repeat_record_on_keyword_miss` 控制多轮录音 |
| `voice_tts` | Piper（优先）或 espeak | 订阅 **`/voice/speak`** |
| `counting_tts` | 计数与编排文案播报 | 订阅 **`situp_count`**、**`tts/speak`**；可选 **`situp/ws_start`**、**`phrase_end_notify_topic`**、**按个数鼓励**与**定周期口播**（见下表） |
| `situp_result_tts` | 成绩口播 | 订阅 **`situp_count`**、**`phrase_end_done_topic`**（默认 **`situp/voice/phrase_end_done`**）；延迟 **`result_delay_sec`** 后播报 |

### `counting_tts`：鼓励语参数

**作用**：每完成 **`encouragement_interval`** 个（如 5、10、15…）随机播报一条文案；与「开始/结束」共用 **`tts_speak` 进程内队列**（`speak()`），**不**经 **`tts/done`**，避免打断 `voice_asr` 对播报完成的等待。

**实现要点**：`situp_count` 由计数节点**每帧发布**，若只在回调里用 `count % N == 0` 会重复入队；节点内用 **count 上升且跨过 N 的倍数** 的边沿判断，未初始化或 count 回退时对齐内部状态。

**操作**：字符串参数由 launch 或 `ros2 param` 设置；`encouragement_phrases` 用 **竖线 `|`** 分句（也支持用换行写多句，节点会归一为 `|` 再分句）。

| 参数 | 说明 |
|------|------|
| `encouragement_enabled` | 字符串 **`true`/`false`/`1`/`yes`** 之一为开；**默认 `false`**（未配置 launch 时与旧行为一致）。 |
| `encouragement_interval` | 正整数，**默认 5**；每完成该个数触发一次**随机**语料。 |
| `encouragement_phrases` | 分句；**空** 且开启时**不播**鼓励语，并打一条 warn。 |

整机默认开启语料时见 **`bringup_pkg` 的 `situp_voice_full.launch.py`**（`--show-args`）。

### `counting_tts`：定周期口播（报当前个数，可选句末鼓励）

**作用**：在**一轮计数进行中**（`situp_count` 为已初始化且 `state` 为 `UP`/`DOWN`）按**固定时间间隔**播报当前 `count`；可仅在模板中写清数字，或再在句末**追加一条**从 `encouragement_phrases` 中**随机**选出的短句。与 `speak()` 鼓励语一样**不**走 **`tts/done`**，避免打断 `voice_asr`。

**行为要点**：

- **`periodic_announce_sec` > 0** 时启用；进入 `UP`/`DOWN` 后**第一次**口播在约 **一个周期之后**（不是立即播）。
- 结束本轮计数（离开 `UP`/`DOWN`）时取消定时；下一轮从再次进入 `UP`/`DOWN` 起重新计时。

**操作**：参数由 **`bringup_pkg` 的 `situp_voice_full.launch.py`** 透传（见该包 README），也可直接对 `counting_tts` 用 `ros2 run` 或参数文件配置。

| 参数 | 说明 |
|------|------|
| `periodic_announce_sec` | 定周期，单位秒；**`≤0` 或 `0`** 为关闭。节点侧未配置时默认 **`0`**（关闭）。 |
| `periodic_announce_template` | 口播模板，**必须**含占位符 **`{count}`**（会替换为当前整数个数）。 |
| `periodic_announce_add_encouragement` | 字符串 **`true`/`1`/`yes`** 为开：在模板句后加 **「，」+ 随机一条** `encouragement_phrases`；语料为空则只播模板。 |

**示例（与整机语音 launch 同参）**：

```bash
# 仅开定周期 15 秒、只报数，不追随机鼓励短句
ros2 launch bringup_pkg situp_voice_full.launch.py \
  periodic_announce_sec:=15 \
  periodic_announce_add_encouragement:=false

# 关闭定周期，仅保留「每 N 个一条」鼓励（见 encouragement_*）
ros2 launch bringup_pkg situp_voice_full.launch.py \
  periodic_announce_sec:=0
```

`ros2 launch bringup_pkg situp_voice_full_with_cloud_monitor.launch.py` **继承**上述参数，用法相同。

---

## Piper：pip 与模型

**作用**：中文 TTS 优先走 Piper ONNX，音质优于 espeak。

**流程**：安装 `piper-tts[zh]` 与 `onnxruntime` → 下载语音模型放入包内 `models/piper/...` → 重新 `colcon build` 使模型安装到 `install/share`。

**操作**：

1. `pip install 'piper-tts[zh]' 'onnxruntime>=1,<2'`
2. `python3 -m piper.download_voices zh_CN-huayan-medium`，将 **`zh_CN-huayan-medium.onnx`** 与 **`.json`** 放到 `voice_pkg/models/piper/zh_CN-huayan-medium/`
3. `colcon build --packages-select voice_pkg`（或 `pip install -e src/voice_pkg`）
4. 系统有 **`aplay` 或 `paplay`**；`tts_backend:=auto` 时自动选 Piper 或 espeak
5. 日志会打印 **`后端=piper`** 或 **`后端=espeak`**

---

## 通过 HTTP 代理安装依赖（例：Windows Clash 7890）

**作用**：在树莓派等 Linux 上经局域网代理访问 pip。

**流程**：代理在 Windows 时用 **Windows 局域网 IP**，不可用 `127.0.0.1:7890`；代理需允许 LAN；防火墙放行端口。

**操作**：

```bash
export http_proxy="http://WINDOWS_LAN_IP:7890"
export https_proxy="http://WINDOWS_LAN_IP:7890"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"

pip install --upgrade pip
pip install 'piper-tts[zh]' 'onnxruntime>=1,<2'
cd /path/to/puppyfit_v2_ws && pip install -e src/voice_pkg
```

长期使用可写入 `~/.bashrc` 或 `pip config set global.proxy http://WINDOWS_LAN_IP:7890`。

---

## 运行依赖（Python）

**作用**：安装缺失依赖避免运行期 ImportError。

**流程**：ASR 用 `sherpa-onnx`、`sounddevice`、`pyserial`；TTS 用 espeak 系或 Piper；ASR 模型在 `share/voice_pkg/models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/` 需含 encoder/decoder/joiner 与 `tokens.txt`。

**操作**：见 `setup.py`；模型不全时从旧环境或官方包补全。

**说明**：`counting_tts` 与 `bringup_pkg` 的 `situp_voice.launch.py` 等配套使用；整机流程见 [bringup_pkg/README.md](../bringup_pkg/README.md)。
