"""
:brief 串口唤醒 + 本地语音识别一体化系统
:desc 通过串口唤醒模块触发录音，调用 sherpa-onnx 完成本地语音识别，并支持自动休眠控制。
:author slt
:version 1.0.0
:history 2026/03/13 1.0.0 
        :desc 串口唤醒 + 本地语音识别一体化系统
"""
import serial
import sounddevice as sd
import numpy as np
import time
import subprocess
from pathlib import Path
import sherpa_onnx

def _try_open_serial(ports, baudrate=115200, data_bits=serial.EIGHTBITS,
                     parity=serial.PARITY_NONE, stop_bits=serial.STOPBITS_ONE,
                     timeout=0.02):
    '''
    :brief 从候选串口列表中依次尝试打开，返回第一个成功打开的 (Serial, 端口名)
    :param ports: 串口路径或路径列表，如 '/dev/ttyUSB1' 或 ['/dev/ttyUSB1', '/dev/ttyUSB0', '/dev/ttyUSB2']
    :return: (serial.Serial 实例, 成功打开的端口路径)
    :raises RuntimeError: 所有候选均无法打开时
    '''
    if isinstance(ports, str):
        ports = [ports]
    for port in ports:
        try:
            ser = serial.Serial(
                port=None,
                baudrate=baudrate,
                bytesize=data_bits,
                parity=parity,
                stopbits=stop_bits,
                timeout=timeout
            )
            ser.rts = False
            ser.dtr = False
            ser.setPort(port)
            ser.open()
            return ser, port
        except serial.SerialException:
            continue
    raise RuntimeError(f"[失败] 无法打开任一串口，已尝试：{ports}")


class SerialWakeupModule:
    '''
    :brief 通用串口唤醒模块
    :desc 负责与唤醒硬件通过串口通信，识别固定唤醒/休眠帧。
    '''
    def __init__(self, 
                 port, 
                 baudrate=115200,
                 wakeup_frame=b'\xaa\x55\x03\x00\xfb',
                 sleep_frame=b'\xaa\x55\x02\x00\xfb',
                 frame_length=5,
                 data_bits=serial.EIGHTBITS,
                 parity=serial.PARITY_NONE,
                 stop_bits=serial.STOPBITS_ONE,
                 timeout=0.02):
        '''
        :brief 初始化串口参数并尝试打开串口
        :param port: 串口设备路径或路径列表。为列表时按顺序尝试，直到某一端口可打开。
                    例如 '/dev/ttyUSB1' 或 ['/dev/ttyUSB1', '/dev/ttyUSB0', '/dev/ttyUSB2']
        :param baudrate: 串口波特率
        :param wakeup_frame: 唤醒帧的原始字节序列
        :param sleep_frame: 休眠帧的原始字节序列
        :param frame_length: 每帧期望读取的字节数
        :param data_bits: 数据位配置
        :param parity: 校验位配置
        :param stop_bits: 停止位配置
        :param timeout: 读串口的超时时间（秒）
        '''
        self.serial_handle, self._port_name = _try_open_serial(
            port, baudrate=baudrate, data_bits=data_bits,
            parity=parity, stop_bits=stop_bits, timeout=timeout
        )
        self.wakeup_frame = wakeup_frame
        self.sleep_frame = sleep_frame
        self.frame_length = frame_length
        self._serial_err_logged = False
        print(f"[成功] 串口 {self._port_name} 已打开")

    def clear_buffer(self):
        '''清空当前串口接收缓冲，避免历史数据干扰后续判断。'''
        if self.serial_handle.is_open and self.serial_handle.in_waiting > 0:
            self.serial_handle.read(self.serial_handle.in_waiting)

    def read_frame(self):
        '''
        :brief 从串口读取一帧数据
        :return: 成功时返回长度为 frame_length 的 bytes，失败或异常返回空 bytes
        '''
        if not self.serial_handle.is_open:
            return b''
        try:
            return self.serial_handle.read(self.frame_length)
        except serial.SerialException as e:
            if not self._serial_err_logged:
                print(f"[错误] 串口读取异常：{e}")
                self._serial_err_logged = True
            return b''

    def is_wakeup(self):
        '''
        :brief 判断当前读取的一帧是否为唤醒帧
        :return: 是唤醒帧返回 True，否则返回 False
        '''
        frame = self.read_frame()
        if frame == self.wakeup_frame:
            print("[事件] 检测到唤醒帧 ✅")
            return True
        return False

    def is_sleep(self):
        '''
        :brief 判断当前读取的一帧是否为休眠帧
        :return: 是休眠帧返回 True，否则返回 False
        '''
        frame = self.read_frame()
        if frame == self.sleep_frame:
            print("[事件] 检测到休眠帧 ⏸️")
            return True
        return False

    def close(self):
        '''关闭串口连接。'''
        if self.serial_handle.is_open:
            self.serial_handle.close()
            print("[提示] 串口已关闭")

    def __enter__(self):
        self.clear_buffer()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

class SherpaOnnxASR:
    '''
    :brief sherpa-onnx 流式语音识别模块（streaming zipformer）
    :desc 使用官方 OnlineRecognizer.from_transducer 接口，对单次录音进行一次性流式解码。
    '''
    def __init__(self, model_dir):
        '''
        :brief 初始化 sherpa-onnx 流式识别器
        :param model_dir: sherpa-onnx 模型目录路径，需包含 encoder/decoder/joiner 和 tokens.txt
        '''
        self.model_dir = Path(model_dir)
        if not self.model_dir.exists():
            raise FileNotFoundError(f"模型目录不存在：{self.model_dir}")

        # 使用当前版本推荐的工厂方法创建识别器（流式 transducer）
        self.sample_rate = 16000
        # 根据模型配置，使用 80 维特征（与官方示例保持一致）
        self.feature_dim = 80

        # 使用 OnlineRecognizer + streaming zipformer，与官方 online-decode-files 示例保持一致
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
        print(f"[成功] 加载 sherpa-onnx 模型：{self.model_dir}")

    def recognize(self, audio_data):
        '''
        :brief 对一段离线录音数据执行一次流式识别
        :param audio_data: 16kHz 单声道 float32 一维数组
        :return: 解码后的文本结果字符串
        '''
        # 构建流式识别流（一次性喂入整段录音）
        stream = self.recognizer.create_stream()
        samples = np.asarray(audio_data, dtype=np.float32)
        stream.accept_waveform(self.sample_rate, samples)

        # 按官方示例补一段 tail padding，帮助流式模型“收尾”
        tail_paddings = np.zeros(int(0.66 * self.sample_rate), dtype=np.float32)
        stream.accept_waveform(self.sample_rate, tail_paddings)
        stream.input_finished()

        # 解码直到该流不再 ready
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)

        result = self.recognizer.get_result(stream)
        return getattr(result, "text", result)

class WakeupASRSystem:
    '''
    :brief 串口唤醒 + 本地语音识别一体化系统
    :desc 通过串口唤醒模块触发录音，调用 sherpa-onnx 完成本地语音识别，并支持自动休眠控制。
    '''
    def __init__(self, wakeup_port, asr_model_dir, sleep_duration: float = 5.0):
        '''
        :brief 初始化唤醒模块与 ASR 模块
        :param wakeup_port: 唤醒模块串口设备路径
        :param asr_model_dir: sherpa-onnx 模型目录
        :param sleep_duration: 每轮识别结束后以及收到休眠帧后自动休眠的时长（秒）
        '''
        # 初始化唤醒模块
        self.wakeup_module = SerialWakeupModule(port=wakeup_port)
        # 初始化 ASR 模块
        self.asr_module = SherpaOnnxASR(model_dir=asr_model_dir)
        # 录音配置（16kHz 单声道，与模型匹配）
        self.sample_rate = 16000
        self.channels = 1
        self.dtype = 'float32'
        # 状态标记
        self.is_recording = False
        self.audio_buffer = []
        # 休眠配置
        self.sleep_duration = float(sleep_duration)
        self._sleep_until = 0.0

    def record_audio(self, duration=5):
        '''
        :brief 从默认声卡采集一段音频
        :param duration: 录音时长（秒），默认 5 秒
        :return: 录音数据（float32 单声道一维数组）
        '''
        print(f"[提示] 开始录音 {duration} 秒...")
        self.is_recording = True
        # 开始录音
        audio_data = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype
        )
        # 等待录音完成
        sd.wait()
        self.is_recording = False
        # 转换为一维数组（单声道）
        audio_data = audio_data.flatten()
        print("[提示] 录音完成 🎤")
        return audio_data

    def run(self):
        '''
        :brief 主运行循环
        :desc 持续监听唤醒帧，触发录音与识别；在每轮结束或接收到休眠帧后进入一段时间的休眠期。
        '''
        print("\n=== 唤醒语音识别系统启动（按 Ctrl+C 退出）===")
        self.wakeup_module.clear_buffer()
        
        try:
            while True:
                # 若处于休眠窗口，则忽略唤醒帧
                if self._sleep_until > 0 and time.time() < self._sleep_until:
                    time.sleep(0.05)
                    continue

                # 检测唤醒帧
                if self.wakeup_module.is_wakeup() and not self.is_recording:
                    # 1. 录音
                    audio_data = self.record_audio(duration=5)
                    # 2. 语音识别
                    print("[提示] 开始语音识别...")
                    asr_result = self.asr_module.recognize(audio_data)
                    # 3. 输出结果
                    print(f"\n=== 识别结果 ===")
                    print(f"文本：{asr_result if asr_result else '未识别到有效语音'}\n")
                    # 4. 本轮识别完成后，自动进入休眠窗口，等待下一次唤醒
                    self._sleep_until = time.time() + self.sleep_duration
                    print(f"[提示] 本轮结束，自动休眠 {self.sleep_duration:.1f} 秒，期间忽略唤醒帧")
                
                # 检测休眠帧（停止录音/识别，并进入一段时间的休眠期）
                if self.wakeup_module.is_sleep():
                    if self.is_recording:
                        self.is_recording = False
                        print("[提示] 休眠帧触发，停止录音")
                    # 设置自定义休眠时长，在此期间忽略新的唤醒帧
                    self._sleep_until = time.time() + self.sleep_duration
                    print(f"[提示] 进入休眠 {self.sleep_duration:.1f} 秒，在此期间忽略唤醒帧")
                
                time.sleep(0.01)  # 降低CPU占用
        
        except KeyboardInterrupt:
            print("\n[提示] 用户终止程序")
        except Exception as e:
            print(f"[错误] 程序异常：{e}")
        finally:
            # 清理资源
            self.wakeup_module.close()
            print("[提示] 系统已退出")

# ===================== 测试示例 =====================
if __name__ == "__main__":
    # 配置参数（根据你的实际环境修改）
    # 串口候选列表：按顺序尝试，找到第一个能打开的即使用（避免 USB 序号变化导致失败）
    WAKEUP_PORTS = ["/dev/ttyUSB1", "/dev/ttyUSB0", "/dev/ttyUSB2"]
    ASR_MODEL_DIR = "./puppyfit_ws/src/asr/models/sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16"  # 模型目录
    SLEEP_DURATION = 5.0  # 自定义休眠时长（秒）
    
    # 初始化并运行系统
    try:
        system = WakeupASRSystem(
            wakeup_port=WAKEUP_PORTS,
            asr_model_dir=Path(ASR_MODEL_DIR).expanduser(),  # 解析 ~ 为用户目录
            sleep_duration=SLEEP_DURATION,
        )
        system.run()
    except Exception as e:
        print(f"[失败] 系统初始化失败：{e}")