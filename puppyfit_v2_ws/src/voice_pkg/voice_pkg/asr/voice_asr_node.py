#!/usr/bin/env python3
'''
:brief ASR 语音节点
:desc 基于 sherpa-onnx 本地识别：串口唤醒或订阅 /asr/trigger（Empty）触发录音，
     识别结果发布为 std_msgs/String 至 /asr/text（话题名可通过参数覆盖）。
     串口打开失败时自动退化为仅话题触发模式。

:author ubuntu
:date 2026/03/28
:version 1.3.0
:history
    1.3.0 - 2026/04/11
        :brief repeat_record_on_keyword_miss 默认 false：未命中只播一次提示，不再次录音，等下次唤醒
    1.2.0 - 2026/04/11
        :brief 可选 require_command_keywords：未命中关键词则播 keyword_mismatch_phrase 再录音，直至命中或达 max_rounds
    1.1.0 - 2026/03/31
        :brief 唤醒/触发后可经 tts/speak 发问候语，可选等待 tts/done 或延时兜底后再录音（不直接依赖 TTS 实现类）
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从旧 asr 迁入并接入 voice_pkg 目录结构
'''

import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty, String

from voice_pkg.asr.sherpa_asr import SherpaOnnxASR
from voice_pkg.utils.paths import default_sherpa_model_dir
from voice_pkg.wakeup.serial_wakeup import SerialWakeupModule


def _parse_command_keywords_param(raw):
    '''
    :brief 将参数解析为关键词列表（与 situp_voice_orchestrator 的 TRIGGER_KEYWORDS 应对齐）
    '''
    if raw is None:
        return ["开始", "计数", "仰卧起坐"]
    if isinstance(raw, str):
        parts = [x.strip() for x in raw.split(",") if x.strip()]
        return parts if parts else ["开始", "计数", "仰卧起坐"]
    if isinstance(raw, (list, tuple)):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out if out else ["开始", "计数", "仰卧起坐"]
    return ["开始", "计数", "仰卧起坐"]


def _record_audio(sample_rate, channels, dtype, duration_sec, logger):
    '''
    :brief 从默认声卡采集一段音频
    :desc 依赖 sounddevice；失败时记录错误并返回 None。
    :param sample_rate: 采样率（Hz），须与 ASR 模型一致
    :param channels: 声道数（通常为 1）
    :param dtype: 采样格式（如 float32）
    :param duration_sec: 录音时长（秒）
    :param logger: rclpy 日志记录器
    :return 一维 float32 数组，或 None
    '''
    try:
        import sounddevice as sd
    except ImportError as e:
        logger.error(f"缺少依赖: {e}，请安装 sounddevice 与 numpy")
        return None
    logger.info(f"开始录音 {duration_sec} 秒...")
    audio_data = sd.rec(
        int(duration_sec * sample_rate),
        samplerate=sample_rate,
        channels=channels,
        dtype=dtype,
    )
    sd.wait()
    logger.info("录音完成")
    return audio_data.flatten()


class VoiceAsrNode(Node):
    '''
    :brief ASR ROS2 节点
    :desc 管理模型加载、发布者/订阅者、可选串口唤醒后台线程与节点销毁时的资源清理。
    '''

    def __init__(self):
        super().__init__("voice_asr")

        self.declare_parameter("model_dir", "")
        self.declare_parameter("use_serial_wakeup", True)
        self.declare_parameter("wakeup_ports", ["/dev/ttyUSB1", "/dev/ttyUSB0", "/dev/ttyUSB2"])
        self.declare_parameter("record_duration_sec", 5.0)
        self.declare_parameter("sleep_duration_sec", 5.0)
        self.declare_parameter("output_topic", "/asr/text")
        self.declare_parameter("trigger_topic", "/asr/trigger")
        self.declare_parameter("wakeup_greeting", "")
        self.declare_parameter("greeting_speak_topic", "tts/speak")
        self.declare_parameter("wait_for_tts_done", True)
        self.declare_parameter("tts_done_topic", "tts/done")
        self.declare_parameter("tts_done_timeout_sec", 10.0)
        self.declare_parameter("greeting_fallback_delay_sec", 2.0)
        self.declare_parameter("require_command_keywords", False)
        self.declare_parameter("command_keywords", ["开始", "计数", "仰卧起坐"])
        self.declare_parameter("keyword_mismatch_phrase", "抱歉我没有听清")
        self.declare_parameter("keyword_match_max_rounds", 0)
        self.declare_parameter("repeat_record_on_keyword_miss", False)

        model_dir = (self.get_parameter("model_dir").value or "").strip()
        if not model_dir:
            model_dir = default_sherpa_model_dir()

        self._model_dir = model_dir
        use_serial = self.get_parameter("use_serial_wakeup").value
        self._use_serial_wakeup = use_serial in (True, "true", "True", "1")
        self._wakeup_ports = self.get_parameter("wakeup_ports").value
        if isinstance(self._wakeup_ports, str):
            self._wakeup_ports = [self._wakeup_ports]
        self._record_duration = self.get_parameter("record_duration_sec").value
        self._sleep_duration = self.get_parameter("sleep_duration_sec").value
        output_topic = self.get_parameter("output_topic").value or "/asr/text"
        self._trigger_topic = self.get_parameter("trigger_topic").value or "/asr/trigger"
        self._wakeup_greeting = (self.get_parameter("wakeup_greeting").value or "").strip()
        self._greeting_speak_topic = (
            self.get_parameter("greeting_speak_topic").value or "tts/speak"
        ).strip() or "tts/speak"
        wfd = self.get_parameter("wait_for_tts_done").value
        self._wait_for_tts_done = wfd in (True, "true", "True", "1")
        self._tts_done_topic = (self.get_parameter("tts_done_topic").value or "tts/done").strip() or "tts/done"
        try:
            self._tts_done_timeout_sec = float(self.get_parameter("tts_done_timeout_sec").value)
        except (TypeError, ValueError):
            self._tts_done_timeout_sec = 10.0
        if self._tts_done_timeout_sec <= 0:
            self._tts_done_timeout_sec = 10.0
        try:
            self._greeting_fallback_delay_sec = float(self.get_parameter("greeting_fallback_delay_sec").value)
        except (TypeError, ValueError):
            self._greeting_fallback_delay_sec = 2.0
        if self._greeting_fallback_delay_sec < 0:
            self._greeting_fallback_delay_sec = 0.0

        rck = self.get_parameter("require_command_keywords").value
        self._require_command_keywords = rck in (True, "true", "True", "1", 1)
        self._command_keywords = _parse_command_keywords_param(
            self.get_parameter("command_keywords").value
        )
        _mismatch = self.get_parameter("keyword_mismatch_phrase").get_parameter_value().string_value
        self._keyword_mismatch_phrase = (_mismatch or "抱歉我没有听清").strip() or "抱歉我没有听清"
        try:
            self._keyword_match_max_rounds = int(self.get_parameter("keyword_match_max_rounds").value)
        except (TypeError, ValueError):
            self._keyword_match_max_rounds = 0
        if self._keyword_match_max_rounds < 0:
            self._keyword_match_max_rounds = 0
        rr = self.get_parameter("repeat_record_on_keyword_miss").value
        self._repeat_record_on_keyword_miss = rr in (True, "true", "True", "1", 1)

        self._text_pub = self.create_publisher(String, output_topic, 10)
        self._speak_pub = self.create_publisher(String, self._greeting_speak_topic, 10)
        self._tts_done_event = threading.Event()
        _need_tts_done_sub = self._wait_for_tts_done and (
            bool(self._wakeup_greeting) or self._require_command_keywords
        )
        if _need_tts_done_sub:
            self.create_subscription(Empty, self._tts_done_topic, self._on_tts_done, 10)
        if self._wakeup_greeting:
            if self._wait_for_tts_done:
                self.get_logger().info(
                    f"唤醒问候已启用：将发布至 [{self._greeting_speak_topic}]，"
                    f"等待完成话题 [{self._tts_done_topic}]（超时 {self._tts_done_timeout_sec}s）"
                )
            else:
                self.get_logger().info(
                    f"唤醒问候已启用：将发布至 [{self._greeting_speak_topic}]，"
                    f"随后固定等待 {self._greeting_fallback_delay_sec}s 再录音"
                )
        if self._require_command_keywords:
            retry = (
                "可多次重录直至命中或达上限"
                if self._repeat_record_on_keyword_miss
                else "仅播提示一次，不发布 asr/text，等下次唤醒"
            )
            self.get_logger().info(
                f"命令关键词门控已启用：关键词={self._command_keywords}，"
                f"未命中将播「{self._keyword_mismatch_phrase}」；{retry}；"
                f"max_rounds={self._keyword_match_max_rounds or '无上限（内部最多100轮）'}"
            )
        self._asr_module = SherpaOnnxASR(model_dir=self._model_dir)
        self.get_logger().info(f"已加载 sherpa-onnx 模型: {self._model_dir}")

        self._sample_rate = self._asr_module.sample_rate
        self._channels = 1
        self._dtype = "float32"
        self._is_recording = False
        self._sleep_until = 0.0
        self._run_thread = None
        self._stop_requested = False

        if self._use_serial_wakeup:
            try:
                self._wakeup_module = SerialWakeupModule(port=self._wakeup_ports)
                self._wakeup_module.clear_buffer()
                self.get_logger().info(f"串口唤醒已启用: {self._wakeup_module._port_name}")
            except RuntimeError as e:
                self.get_logger().error(str(e))
                self._wakeup_module = None
                self._use_serial_wakeup = False
        else:
            self._wakeup_module = None

        if not self._use_serial_wakeup or self._wakeup_module is None:
            self.create_subscription(Empty, self._trigger_topic, self._on_trigger, 10)
            self.get_logger().info(f"话题触发模式：订阅 {self._trigger_topic}")

        self.get_logger().info(f"识别结果发布到: {output_topic}")

        if self._use_serial_wakeup and self._wakeup_module is not None:
            self._run_thread = threading.Thread(target=self._run_wakeup_loop, daemon=True)
            self._run_thread.start()

    def _on_tts_done(self, _msg: Empty) -> None:
        '''
        :brief 播放端在一段 TTS 结束后发布 Empty，此处唤醒录音线程
        '''
        self._tts_done_event.set()

    def _run_post_wakeup_greeting(self) -> None:
        '''
        :brief 唤醒或触发后：可选向 tts/speak 发问候，再等待 tts/done 或固定延时
        '''
        if not self._wakeup_greeting:
            return
        msg = String()
        msg.data = self._wakeup_greeting
        self._tts_done_event.clear()
        self.get_logger().info(f"发布唤醒问候至 [{self._greeting_speak_topic}]")
        self._speak_pub.publish(msg)
        if self._wait_for_tts_done:
            ok = self._tts_done_event.wait(timeout=self._tts_done_timeout_sec)
            if not ok:
                self.get_logger().warn(
                    f"未在 {self._tts_done_timeout_sec}s 内收到 [{self._tts_done_topic}]，继续录音"
                )
        else:
            time.sleep(self._greeting_fallback_delay_sec)

    @staticmethod
    def _text_matches_command(text: str, keywords: list) -> bool:
        t = (text or "").strip()
        if not t or t == "未识别到有效语音":
            return False
        return any(kw in t for kw in keywords)

    def _speak_mismatch_and_wait(self) -> None:
        '''
        :brief 未命中关键词时播报提示语，再等 TTS 播完或兜底延时（调用方决定是否继续录音）
        '''
        self._tts_done_event.clear()
        msg = String()
        msg.data = self._keyword_mismatch_phrase
        self.get_logger().info(
            f"发布至 [{self._greeting_speak_topic}]: {self._keyword_mismatch_phrase}"
        )
        self._speak_pub.publish(msg)
        if self._wait_for_tts_done:
            ok = self._tts_done_event.wait(timeout=self._tts_done_timeout_sec)
            if not ok:
                self.get_logger().warn(
                    f"未在 {self._tts_done_timeout_sec}s 内收到 [{self._tts_done_topic}]，继续流程"
                )
        else:
            time.sleep(self._greeting_fallback_delay_sec)

    def _record_and_publish(self) -> None:
        '''
        :brief 采集音频、识别并发布识别串；可选直至命中 command_keywords 才发布
        '''
        _INTERNAL_MAX_ROUNDS = 100
        round_idx = 0
        while True:
            audio = _record_audio(
                self._sample_rate,
                self._channels,
                self._dtype,
                self._record_duration,
                self.get_logger(),
            )
            if audio is None:
                return
            text = self._asr_module.recognize(audio)
            text = (text or "").strip() or "未识别到有效语音"
            self.get_logger().info(f"识别结果: {text}")
            round_idx += 1

            if not self._require_command_keywords or self._text_matches_command(
                text, self._command_keywords
            ):
                out = String()
                out.data = text
                self._text_pub.publish(out)
                return

            if not self._repeat_record_on_keyword_miss:
                self.get_logger().info("未命中关键词，播报一次后结束本轮（不发布 asr/text，请再次唤醒）")
                self._speak_mismatch_and_wait()
                return

            limit = self._keyword_match_max_rounds
            if limit > 0 and round_idx >= limit:
                self.get_logger().warn(
                    f"已达 keyword_match_max_rounds={limit}，仍发布本次识别"
                )
                out = String()
                out.data = text
                self._text_pub.publish(out)
                return
            if limit <= 0 and round_idx >= _INTERNAL_MAX_ROUNDS:
                self.get_logger().warn(
                    f"关键词门控已达内部上限 {_INTERNAL_MAX_ROUNDS} 轮，仍发布本次识别"
                )
                out = String()
                out.data = text
                self._text_pub.publish(out)
                return

            self.get_logger().info(f"未命中关键词，播报后重新录音（第 {round_idx} 轮）")
            self._speak_mismatch_and_wait()

    def _on_trigger(self, _msg):
        '''
        :brief 话题触发一次识别流程
        :param _msg: std_msgs/Empty，内容未使用
        '''
        if self._is_recording:
            return
        self._is_recording = True
        try:
            self._run_post_wakeup_greeting()
            self._record_and_publish()
        finally:
            self._is_recording = False

    def _run_wakeup_loop(self):
        '''
        :brief 串口唤醒主循环
        :desc 在守护线程中运行；检测到唤醒帧后录音识别，休眠帧或冷却期内降低触发频率。
        '''
        while not self._stop_requested and rclpy.ok():
            if self._sleep_until > 0 and time.time() < self._sleep_until:
                time.sleep(0.05)
                continue
            if self._wakeup_module is None:
                break
            if self._wakeup_module.is_wakeup() and not self._is_recording:
                self._is_recording = True
                try:
                    self._run_post_wakeup_greeting()
                    self._record_and_publish()
                finally:
                    self._is_recording = False
                self._sleep_until = time.time() + self._sleep_duration
            if self._wakeup_module.is_sleep():
                if self._is_recording:
                    self._is_recording = False
                self._sleep_until = time.time() + self._sleep_duration
            time.sleep(0.01)
        if self._wakeup_module is not None:
            self._wakeup_module.close()

    def destroy_node(self):
        '''
        :brief 停止后台线程并关闭串口
        :desc 先于 Node 基类销毁执行，避免线程持有已关闭资源。
        '''
        self._stop_requested = True
        if self._run_thread is not None and self._run_thread.is_alive():
            self._run_thread.join(timeout=1.0)
        if self._wakeup_module is not None:
            try:
                self._wakeup_module.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选，传递给 rclpy.init
    '''
    rclpy.init(args=args)
    node = VoiceAsrNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
