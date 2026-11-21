# task_manager_pkg

**本包整体作用**：**任务编排与总控（大脑）**，按业务流程串联语音意图、自动找位、计数启停、定时与口播，向 `exercise_engine_pkg`、`voice_pkg`、`bridge_pkg` 等发出标准话题指令。

下文对 **典型整机入口**、**节点能力** 给出 **作用**、**流程**、**操作**。

---

## 整机：仰卧起坐 + 语音（无自动找位）

**作用**：使用 `exercise_assistant`：ASR 关键词 → 确认 TTS → 等待「开始计数」类播报后触发 `timer/start` 等；姿态与计数链为 `situp_counter.launch`（**非** `situp_with_auto_position`）。

**流程**：由 `bringup_pkg` 拉起语音节点与本编排节点，再拉起 `exercise_engine_pkg` 的计数 launch；详见 [bringup_pkg/README.md](../bringup_pkg/README.md) 中 `situp_voice.launch.py`。

**操作**：

```bash
source /opt/ros/humble/setup.bash
source /path/to/puppyfit_v2_ws/install/setup.bash
ros2 launch bringup_pkg situp_voice.launch.py
```

---

## 整机：仰卧起坐 + 语音 + 自动找位 + 成绩口播

**作用**：使用 `situp_voice_orchestrator`：ASR → 确认 TTS → `auto_position` 找位（失败可播「没有找到合适的位置」）→ 就绪后 `situp_control` 与 `situp/ws_start` / `timer/start` 链；与 `situp_result_tts` 等配合播成绩。

**流程**：由 `bringup_pkg` 的 `situp_voice_full.launch.py` 组合 `exercise_engine_pkg`（含 `situp_with_auto_position`）与 `voice_pkg`。

**操作**：

```bash
ros2 launch bringup_pkg situp_voice_full.launch.py
```

参数：`ros2 launch bringup_pkg situp_voice_full.launch.py --show-args`。

---

## 节点一览

**作用**：了解各可执行文件职责，便于二次开发或替换编排。

**流程**：`sport_task_manager` 为示例；`exercise_assistant` / `situp_voice_orchestrator` 为当前仰卧起坐主路径。

**操作**：查阅下表。

| 可执行名 | 说明 |
|----------|------|
| `sport_task_manager` | 示例：订阅 `/asr/text`，发布 `/task/status` 与 `/voice/speak` |
| `exercise_assistant` | ASR 关键词 → `tts/speak` 确认语 → 等「开始计数」播报后发 `timer/start`（与 `situp_voice` 配套） |
| `situp_voice_orchestrator` | ASR → 确认 TTS → `auto_position` → ready 后 `situp_control` 与 `situp/ws_start` / `timer/start`（与 `situp_voice_full` 配套） |

---

## 规划（以后）

**作用**：记录后续演进方向。

**流程**：能力合并与运动类型扩展在迭代中完成。

**操作**：待办包括：与 `sport_task_manager` 合并或统一任务状态机；更多运动类型的编排参数化。
