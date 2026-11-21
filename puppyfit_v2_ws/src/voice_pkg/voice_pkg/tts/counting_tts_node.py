#!/usr/bin/env python3
'''
:brief 计数联动 TTS 节点（仰卧起坐等）
:desc 订阅 situp_count（robot_msgs/SitUpCount）与 tts/speak，按 initialized/state 播报开始/结束；
      与 voice_tts（/voice/speak）并存，用于语音助手与运动计数编排。

:author slt
:date 2026/03/29
:version 1.5.1
:history
    1.5.1 - 2026/04/23
        :brief launch 传入 BOOL/数字时兼容；dynamic_typing + _param_value_as_str，避免节点起不来导致无 TTS
    1.5.0 - 2026/04/23
        :brief 定周期口播 current 个数（periodic_announce_template 含 {count}）；可追加 random 鼓励短句
    1.3.2 - 2026/04/11
        :brief phrase_end 空字符串不再被 or「计时结束」覆盖，与 launch 默认空句一致
    1.4.0 - 2026/04/23
        :brief 可选鼓励语：encouragement_interval 个完成一次、随机选句；边沿跨里程碑，避免每帧重复入队
    1.3.1 - 2026/04/11
        :brief phrase_end 可为空：不播 phrase_end，直接执行录像停止与 phrase_end_notify（供一句播成绩）
    1.3.0 - 2026/04/10
        :brief 可选 phrase_end_notify_topic：phrase_end 音频播完后发 Empty，供 situp_result_tts 等衔接
    1.2.0 - 2026/03/31
        :brief 可选 session_record_*：订阅 SessionRecordStart 缓存 session_id；phrase_end 播完后发 SessionRecordStop
    1.1.0 - 2026/03/31
        :brief 可选参数 tts_done_topic：每段播报结束后发布 std_msgs/Empty，供 voice_asr 等弱耦合等待
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块与类注释
'''

import random
from typing import Optional

import rclpy
from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.node import Node
from robot_msgs.msg import SitUpCount
from session_record_msgs.msg import SessionRecordStart, SessionRecordStop
from std_msgs.msg import Empty, String as StringMsg

from voice_pkg.tts.tts_speak import configure_tts_from_node, speak


def _param_value_as_str(pv) -> str:
    ''':brief 将参数值统一成字符串，兼容 launch/YAML 把 true/数字解析为 BOOL、INTEGER 的情况'''
    t = int(pv.type)
    if t == ParameterType.PARAMETER_STRING:
        return (pv.string_value or "").strip()
    if t == ParameterType.PARAMETER_BOOL:
        return "true" if pv.bool_value else "false"
    if t == ParameterType.PARAMETER_INTEGER:
        return str(int(pv.integer_value))
    if t == ParameterType.PARAMETER_DOUBLE:
        s = f"{pv.double_value:.10g}"
        return s
    return ""


class CountingTtsNode(Node):
    '''
    :brief 计数状态驱动 TTS 的 ROS2 节点
    :desc 根据 SitUpCount 与可选 speak 话题编排短语播报。
    '''

    def __init__(self):
        super().__init__("counting_tts")

        self.declare_parameter("count_topic", "situp_count")
        self.declare_parameter("exercise_name", "仰卧起坐")
        self.declare_parameter("phrase_start", "开始计数")
        self.declare_parameter("phrase_end", "计时结束")
        self.declare_parameter("speak_topic", "tts/speak")
        self.declare_parameter("start_spoken_notify_topic", "")
        self.declare_parameter("tts_done_topic", "")
        self.declare_parameter("session_record_start_topic", "")
        self.declare_parameter("session_record_stop_topic", "")
        self.declare_parameter("phrase_end_notify_topic", "")
        # 鼓励语 / 周期口播：launch 常把 true/15 写成 BOOL、DOUBLE，与历史「字符串参数」冲突；dynamic_typing 避免起不来
        _dyn = ParameterDescriptor(dynamic_typing=True)
        self.declare_parameter("encouragement_enabled", "false", descriptor=_dyn)
        self.declare_parameter("encouragement_interval", "5", descriptor=_dyn)
        self.declare_parameter("encouragement_phrases", "", descriptor=_dyn)
        self.declare_parameter("periodic_announce_sec", "0", descriptor=_dyn)
        self.declare_parameter("periodic_announce_template", "你已经做了{count}个了", descriptor=_dyn)
        self.declare_parameter("periodic_announce_add_encouragement", "false", descriptor=_dyn)

        self.count_topic = self.get_parameter("count_topic").get_parameter_value().string_value or "situp_count"
        self.speak_topic = self.get_parameter("speak_topic").get_parameter_value().string_value or "tts/speak"
        self.exercise_name = self.get_parameter("exercise_name").get_parameter_value().string_value or "运动"
        self.phrase_start = self.get_parameter("phrase_start").get_parameter_value().string_value or "开始计数"
        # 空字符串合法（与 situp_voice_full phrase_end:= 合并为一句成绩口播）；勿用 or 默认以免覆盖空值
        self.phrase_end = self.get_parameter("phrase_end").get_parameter_value().string_value
        self._start_spoken_notify_topic = (
            self.get_parameter("start_spoken_notify_topic").get_parameter_value().string_value or ""
        )
        _done_topic = (self.get_parameter("tts_done_topic").get_parameter_value().string_value or "").strip()
        self._tts_done_pub = None
        if _done_topic:
            self._tts_done_pub = self.create_publisher(Empty, _done_topic, 10)

        _sr_start = (self.get_parameter("session_record_start_topic").get_parameter_value().string_value or "").strip()
        _sr_stop = (self.get_parameter("session_record_stop_topic").get_parameter_value().string_value or "").strip()
        self._cached_session_id = ""
        self._record_stop_pub = None
        if _sr_stop:
            self._record_stop_pub = self.create_publisher(SessionRecordStop, _sr_stop, 10)

        _pen = (self.get_parameter("phrase_end_notify_topic").get_parameter_value().string_value or "").strip()
        self._phrase_end_notify_pub = None
        if _pen:
            self._phrase_end_notify_pub = self.create_publisher(Empty, _pen, 10)

        _e_raw = (_param_value_as_str(self.get_parameter("encouragement_enabled").get_parameter_value()) or "false").lower()
        self._encouragement_enabled = _e_raw in ("true", "1", "yes")
        try:
            _s_iv = _param_value_as_str(self.get_parameter("encouragement_interval").get_parameter_value())
            _iv = int(_s_iv.strip() if _s_iv.strip() else "5")
        except (TypeError, ValueError):
            _iv = 5
        self._encouragement_interval = max(1, _iv)
        self._enc_phrases = self._parse_encouragement_phrases(
            (_param_value_as_str(self.get_parameter("encouragement_phrases").get_parameter_value()) or "").strip()
        )
        if self._encouragement_enabled and not self._enc_phrases:
            self.get_logger().warn("encouragement_enabled 为真但 encouragement_phrases 为空，将不播鼓励语")

        try:
            _s_p = _param_value_as_str(self.get_parameter("periodic_announce_sec").get_parameter_value())
            _psec = float(_s_p.strip() if _s_p.strip() else "0")
        except (TypeError, ValueError):
            _psec = 0.0
        self._periodic_announce_enabled = _psec > 0.0
        self._periodic_announce_sec = max(0.1, _psec) if _psec > 0.0 else 0.0
        self._periodic_template = (
            (_param_value_as_str(self.get_parameter("periodic_announce_template").get_parameter_value()) or "")
            .strip()
            or "你已经做了{count}个了"
        )
        _pae = (
            (_param_value_as_str(self.get_parameter("periodic_announce_add_encouragement").get_parameter_value()) or "false")
            .strip()
            .lower()
        )
        self._periodic_add_enc = _pae in ("true", "1", "yes")
        if self._periodic_announce_enabled and self._periodic_add_enc and not self._enc_phrases:
            self.get_logger().warn("periodic_announce_add_encouragement 为真但 encouragement_phrases 为空，周期口播将只播模板句")

        tts_kind = configure_tts_from_node(self)

        self._last_initialized = False
        self._last_state = ""
        self._phrase_start_spoken_this_round = False
        # 连续两帧 STOPPED 才认定计时结束，避免多节点/乱序消息在 STOPPED 与 UP/DOWN 间抖动时误触发播报
        self._stop_end_pending = False
        # 计时结束播报后，直到观察到 initialized==False（新一轮 situp_control start 重置）才允许再次播报「开始」
        self._suppress_start_until_init_false = False
        # 鼓励语边沿：与 situp 每帧发布一致，仅当 count 增加且跨过 interval 的倍数时入队；未初始化或 count 回退时对齐
        self._enc_last_count = -1
        self._cached_situp: Optional[SitUpCount] = None
        self._periodic_timer = None
        self._periodic_was_counting = False

        self.create_subscription(SitUpCount, self.count_topic, self._on_count_msg, 10)
        self.create_subscription(StringMsg, self.speak_topic, self._on_speak_msg, 10)
        if _sr_start:
            self.create_subscription(SessionRecordStart, _sr_start, self._on_session_record_start, 10)
        self._start_spoken_pub = None
        if self._start_spoken_notify_topic.strip():
            self._start_spoken_pub = self.create_publisher(StringMsg, self._start_spoken_notify_topic.strip(), 10)
        extra_done = f"，tts/done→{_done_topic}" if _done_topic else ""
        extra_sr = f"，session_record start→{_sr_start} stop→{_sr_stop}" if (_sr_start or _sr_stop) else ""
        extra_pen = f"，phrase_end_notify→{_pen}" if _pen else ""
        _enc_info = ""
        if self._encouragement_enabled and self._enc_phrases:
            _enc_info = f"，鼓励语 每{self._encouragement_interval} 个/共{len(self._enc_phrases)} 句"
        _p_info = ""
        if self._periodic_announce_enabled:
            _penc = "，口播后随机鼓励" if (self._periodic_add_enc and self._enc_phrases) else ""
            _p_info = f"，周期口播 每{self._periodic_announce_sec:.1f} 秒/模板{{count}}{_penc}"
        self.get_logger().info(
            f"计数 TTS 已启动（{self.exercise_name}），后端={tts_kind}，订阅: {self.count_topic}、{self.speak_topic}"
            f"{extra_done}{extra_sr}{extra_pen}{_enc_info}{_p_info}"
        )

    @staticmethod
    def _parse_encouragement_phrases(raw: str) -> list[str]:
        if not raw:
            return []
        return [p.strip() for p in raw.replace("\n", "|").split("|") if p.strip()]

    def _update_encouragement(self, msg: SitUpCount) -> None:
        if not self._encouragement_enabled or not self._enc_phrases:
            return
        try:
            c = int(msg.count)
        except (TypeError, ValueError):
            return
        initialized = bool(msg.initialized)
        if not initialized:
            self._enc_last_count = c
            return
        n = self._encouragement_interval
        if c < self._enc_last_count:
            self._enc_last_count = c
            return
        prev = self._enc_last_count
        if c <= prev:
            return
        for m in range(((prev // n) + 1) * n, c + 1, n):
            if m <= 0:
                continue
            line = random.choice(self._enc_phrases)
            self.get_logger().info(f"鼓励语（{self.exercise_name}，{m} 个）: {line}")
            # 不发布 tts/done，避免打断 voice_asr 对「一句一动」的等待
            speak(line, lang="zh")
        self._enc_last_count = c

    def _sync_periodic_timer(self, msg: SitUpCount) -> None:
        if not self._periodic_announce_enabled:
            return
        state = str(msg.state) if msg.state else ""
        active = bool(msg.initialized) and state in ("UP", "DOWN")
        if active and not self._periodic_was_counting:
            if self._periodic_timer is not None:
                self._periodic_timer.cancel()
                self._periodic_timer = None
            self._periodic_timer = self.create_timer(
                self._periodic_announce_sec, self._on_periodic_announce
            )
        elif not active and self._periodic_was_counting:
            if self._periodic_timer is not None:
                self._periodic_timer.cancel()
                self._periodic_timer = None
        self._periodic_was_counting = active

    def _on_periodic_announce(self) -> None:
        if self._cached_situp is None:
            return
        msg = self._cached_situp
        state = str(msg.state) if msg.state else ""
        if not msg.initialized or state not in ("UP", "DOWN"):
            return
        try:
            c = int(msg.count)
        except (TypeError, ValueError):
            return
        try:
            text = self._periodic_template.format(count=c)
        except Exception as e:
            self.get_logger().error(f"periodic_announce_template 格式化失败: {e}")
            return
        if self._periodic_add_enc and self._enc_phrases:
            text += "，" + random.choice(self._enc_phrases)
        self.get_logger().info(
            f"周期口播（{self._periodic_announce_sec:.1f}s，{self.exercise_name}）: {text}"
        )
        speak(text, lang="zh")

    def _speak_with_done(self, text: str, lang: str = "zh", on_done=None) -> None:
        '''
        :brief 调用全局 speak 队列，并在本段播报结束后可选链式回调 + 发布 tts/done
        '''

        def _wrapped_done() -> None:
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    pass
            if self._tts_done_pub is not None:
                self._tts_done_pub.publish(Empty())

        speak(text, lang=lang, on_done=_wrapped_done)

    def _on_speak_msg(self, msg: StringMsg) -> None:
        text = (msg.data or "").strip()
        if text:
            self.get_logger().info(f"播报（speak）: {text}")
            self._speak_with_done(text)

    def _on_session_record_start(self, msg: SessionRecordStart) -> None:
        sid = (msg.session_id or "").strip()
        if sid:
            self._cached_session_id = sid

    def _publish_session_record_stop(self) -> None:
        if self._record_stop_pub is None or not self._cached_session_id:
            return
        out = SessionRecordStop()
        out.session_id = self._cached_session_id
        out.stamp = self.get_clock().now().to_msg()
        out.tag = ""
        self._record_stop_pub.publish(out)

    def _notify_start_spoken(self) -> None:
        if self._start_spoken_pub is None:
            return
        out = StringMsg()
        out.data = f"{self.exercise_name}:phrase_start_spoken"
        self._start_spoken_pub.publish(out)

    def _on_count_msg(self, msg: SitUpCount) -> None:
        initialized = bool(msg.initialized)
        state = str(msg.state) if msg.state else ""

        if not initialized:
            self._suppress_start_until_init_false = False

        if state == "STOPPED":
            if self._last_state in ("UP", "DOWN"):
                self._stop_end_pending = True
            elif self._stop_end_pending and self._last_state == "STOPPED":
                def _on_phrase_end_audio_done() -> None:
                    self._publish_session_record_stop()
                    if self._phrase_end_notify_pub is not None:
                        self._phrase_end_notify_pub.publish(Empty())

                end_text = (self.phrase_end or "").strip()
                if end_text:
                    self.get_logger().info(f"计时结束（{self.exercise_name}），播报：{end_text}")
                    _end_cb = None
                    if self._record_stop_pub or self._phrase_end_notify_pub is not None:
                        _end_cb = _on_phrase_end_audio_done
                    self._speak_with_done(end_text, on_done=_end_cb)
                else:
                    self.get_logger().info(
                        f"计时结束（{self.exercise_name}），phrase_end 为空，跳过本句仅衔接后续口播"
                    )
                    _on_phrase_end_audio_done()
                self._stop_end_pending = False
                self._phrase_start_spoken_this_round = False
                self._suppress_start_until_init_false = True
        else:
            self._stop_end_pending = False

        if not self._phrase_start_spoken_this_round:
            allow_start = not self._suppress_start_until_init_false or not self._last_initialized
            if allow_start and initialized and not self._last_initialized:
                self.get_logger().info(f"初始化完成（{self.exercise_name}），播报：{self.phrase_start}")
                self._speak_with_done(self.phrase_start, on_done=self._notify_start_spoken)
                self._phrase_start_spoken_this_round = True
            elif (
                allow_start
                and initialized
                and state in ("UP", "DOWN")
                and self._last_state == "STOPPED"
            ):
                self.get_logger().info(f"本轮开始计数（{self.exercise_name}），播报：{self.phrase_start}")
                self._speak_with_done(self.phrase_start, on_done=self._notify_start_spoken)
                self._phrase_start_spoken_this_round = True

        self._update_encouragement(msg)

        self._cached_situp = msg
        self._sync_periodic_timer(msg)

        self._last_initialized = initialized
        self._last_state = state


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = CountingTtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
