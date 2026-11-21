'''
:brief TTS 播报队列与后台工作者
:desc 单守护线程顺序播报；支持 Piper ONNX（piper-tts）或 espeak-ng / espeak；
     相邻两段间隔 _SPEAK_GAP_SEC，可选 on_done 回调。

:author ubuntu
:date 2026/03/28
:version 1.1.0
:history
    1.1.0 - 2026/03/28
        :brief 增加 Piper ONNX，configure_tts / configure_tts_from_node
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从旧 tts 包 _speak 逻辑抽出
'''

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

if TYPE_CHECKING:
    from rclpy.node import Node as RclpyNode

_OnDone = Optional[Callable[[], None]]
_SPEAK_QUEUE: queue.Queue[tuple[str, str, _OnDone]] = queue.Queue()
_SPEAK_WORKER_STARTED = False
_SPEAK_GAP_SEC = 0.1

_CONFIG_LOCK = threading.Lock()
# 有效 backend: "espeak" | "piper"
_BACKEND: str = "espeak"
_PIPER_MODEL: str = ""
_PIPER_CONFIG: str = ""

_piper_voice: Any = None
_piper_voice_key: Tuple[str, str] = ("", "")
# 最近一次 Piper 加载失败原因（供日志区分「未安装」与「模型损坏」等）
_PIPER_LAST_LOAD_ERROR: str = ""


def configure_tts(
    *,
    backend: str,
    piper_model_path: str = "",
    piper_config_path: str = "",
) -> None:
    '''
    :brief 在首次 speak() 之前配置 TTS 后端（每个进程内调用一次即可）
    :param backend: espeak 或 piper
    :param piper_model_path: Piper .onnx 绝对路径
    :param piper_config_path: 可选 .onnx.json；空则交给 Piper 自动解析
    '''
    global _BACKEND, _PIPER_MODEL, _PIPER_CONFIG, _piper_voice, _piper_voice_key
    b = (backend or "espeak").strip().lower()
    if b not in ("espeak", "piper"):
        b = "espeak"
    with _CONFIG_LOCK:
        _BACKEND = b
        _PIPER_MODEL = (piper_model_path or "").strip()
        _PIPER_CONFIG = (piper_config_path or "").strip()
        _piper_voice = None
        _piper_voice_key = ("", "")


def configure_tts_from_node(node: RclpyNode) -> str:
    '''
    :brief 从 ROS 参数声明并应用 TTS 配置
    :param node: 任意 rclpy Node（voice_tts / counting_tts）
    :return 实际选用的后端名（espeak 或 piper），便于日志
    '''
    from voice_pkg.utils.paths import default_piper_config_path, default_piper_model_onnx

    node.declare_parameter("tts_backend", "auto")
    node.declare_parameter("piper_model_path", "")
    node.declare_parameter("piper_config_path", "")

    raw_backend = node.get_parameter("tts_backend").get_parameter_value().string_value or "auto"
    backend = raw_backend.strip().lower()
    model = (node.get_parameter("piper_model_path").get_parameter_value().string_value or "").strip()
    cfg = (node.get_parameter("piper_config_path").get_parameter_value().string_value or "").strip()

    if not model:
        model = default_piper_model_onnx()
    if not cfg:
        cfg = default_piper_config_path(model)

    use_piper = False
    if backend == "piper":
        use_piper = True
    elif backend == "espeak":
        use_piper = False
    else:
        # auto
        use_piper = bool(model and os.path.isfile(model))

    if use_piper and not (model and os.path.isfile(model)):
        node.get_logger().warn(
            "tts_backend 要求 Piper 但未找到模型文件，回退 espeak；请下载 zh_CN-huayan-medium 或设置 piper_model_path"
        )
        use_piper = False

    chosen = "piper" if use_piper else "espeak"
    configure_tts(
        backend=chosen,
        piper_model_path=model if use_piper else "",
        piper_config_path=cfg if use_piper else "",
    )
    if use_piper:
        if _get_piper_voice() is None:
            hint = (_PIPER_LAST_LOAD_ERROR or "").strip()
            if hint:
                node.get_logger().error(
                    f"Piper 模型加载失败，已回退 espeak。原因: {hint}；模型路径: {model}"
                )
            else:
                node.get_logger().error(
                    "Piper 不可用：未安装 piper-tts/onnxruntime；已回退 espeak。"
                    " 请执行: pip3 install 'piper-tts[zh]>=1.3.0' 'onnxruntime>=1,<2'"
                )
            configure_tts(backend="espeak", piper_model_path="", piper_config_path="")
            return "espeak"
        node.get_logger().info(f"Piper TTS 已加载: {model}")
    return chosen


def _invalidate_piper_voice_unlocked() -> None:
    global _piper_voice, _piper_voice_key
    _piper_voice = None
    _piper_voice_key = ("", "")


def _get_piper_voice() -> Any:
    global _piper_voice, _piper_voice_key, _PIPER_LAST_LOAD_ERROR
    try:
        from piper import PiperVoice
    except ImportError as e:
        _PIPER_LAST_LOAD_ERROR = f"ImportError: {e}"
        return None
    key = (_PIPER_MODEL, _PIPER_CONFIG)
    if _piper_voice is not None and _piper_voice_key == key:
        return _piper_voice
    try:
        if _PIPER_CONFIG and os.path.isfile(_PIPER_CONFIG):
            _piper_voice = PiperVoice.load(_PIPER_MODEL, config_path=_PIPER_CONFIG, use_cuda=False)
        else:
            _piper_voice = PiperVoice.load(_PIPER_MODEL, use_cuda=False)
        _piper_voice_key = key
        _PIPER_LAST_LOAD_ERROR = ""
        return _piper_voice
    except Exception as e:
        _PIPER_LAST_LOAD_ERROR = f"{type(e).__name__}: {e}"
        _invalidate_piper_voice_unlocked()
        return None


def _play_wav_file(path: str) -> None:
    if shutil.which("aplay"):
        try:
            subprocess.run(["aplay", "-q", path], capture_output=True, timeout=120)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
    if shutil.which("paplay"):
        try:
            subprocess.run(["paplay", path], capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _speak_espeak(text: str, lang: str) -> None:
    for cmd_name in ("espeak-ng", "espeak"):
        exe = shutil.which(cmd_name)
        if exe:
            try:
                subprocess.run([exe, "-v", lang, text], capture_output=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError):
                pass
            break


def _speak_piper(text: str) -> bool:
    voice = _get_piper_voice()
    if voice is None:
        return False
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(wav_path, "wb") as wf:
            voice.synthesize_wav(text, wf)
        _play_wav_file(wav_path)
        return True
    except Exception:
        return False
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _ensure_speak_worker_started() -> None:
    '''
    :brief 懒启动播报工作线程
    :desc 全局仅启动一次 daemon 线程，从队列取 (text, lang, on_done) 执行。
    '''
    global _SPEAK_WORKER_STARTED
    if _SPEAK_WORKER_STARTED:
        return

    def _worker() -> None:
        while True:
            text, lang, on_done = _SPEAK_QUEUE.get()
            try:
                with _CONFIG_LOCK:
                    backend = _BACKEND
                if backend == "piper":
                    if not _speak_piper(text):
                        _speak_espeak(text, lang)
                else:
                    _speak_espeak(text, lang)
                if on_done is not None:
                    try:
                        on_done()
                    except Exception:
                        pass
            finally:
                time.sleep(_SPEAK_GAP_SEC)
                _SPEAK_QUEUE.task_done()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    _SPEAK_WORKER_STARTED = True


def speak(text: str, lang: str = "zh", on_done: _OnDone = None) -> None:
    '''
    :brief 将一段文本加入播报队列
    :param text: 待朗读内容
    :param lang: espeak 语音名（如 zh）；Piper 忽略语种参数
    :param on_done: 本段播报结束后调用的可选回调
    '''
    _ensure_speak_worker_started()
    _SPEAK_QUEUE.put((text, lang, on_done))
