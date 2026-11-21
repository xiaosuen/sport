'''
:brief Sherpa-ONNX 流式语音识别封装
:desc 使用 OnlineRecognizer.from_transducer 对单次离线录音做流式解码；
     模型目录需包含 tokens.txt 与 encoder/decoder/joiner 的 ONNX 文件。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从旧 asr 包迁入
'''

from pathlib import Path

import numpy as np
import sherpa_onnx


class SherpaOnnxASR:
    '''
    :brief sherpa-onnx Streaming Zipformer 识别器封装
    :desc 固定 16kHz、80 维特征；解码方式为 greedy_search。
    '''

    def __init__(self, model_dir):
        '''
        :brief 加载模型并构建 OnlineRecognizer
        :param model_dir: 模型根目录路径（字符串或 Path 可接受对象）
        '''
        self.model_dir = Path(model_dir)
        if not self.model_dir.exists():
            raise FileNotFoundError(f"模型目录不存在：{self.model_dir}")

        self.sample_rate = 16000
        self.feature_dim = 80

        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(self.model_dir / "tokens.txt"),
            encoder=str(self.model_dir / "encoder-epoch-99-avg-1.onnx"),
            decoder=str(self.model_dir / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(self.model_dir / "joiner-epoch-99-avg-1.onnx"),
            num_threads=1,
            provider="cpu",
            sample_rate=self.sample_rate,
            feature_dim=self.feature_dim,
            decoding_method="greedy_search",
            max_active_paths=4,
        )

    def recognize(self, audio_data):
        '''
        :brief 对一段音频执行识别
        :desc 末尾追加约 0.66s 静音尾填充以促使流式解码结束。
        :param audio_data: 一维 float32 采样序列（16kHz 单声道）
        :return 识别文本字符串
        '''
        stream = self.recognizer.create_stream()
        samples = np.asarray(audio_data, dtype=np.float32)
        stream.accept_waveform(self.sample_rate, samples)

        tail_paddings = np.zeros(int(0.66 * self.sample_rate), dtype=np.float32)
        stream.accept_waveform(self.sample_rate, tail_paddings)
        stream.input_finished()

        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)

        result = self.recognizer.get_result(stream)
        return getattr(result, "text", result)
