'''
:brief 串口唤醒硬件通信模块
:desc 按固定帧长从串口读字节，与唤醒/休眠魔数帧比对；支持多候选端口依次尝试打开。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从旧 asr 包迁入
'''

import serial


def _try_open_serial(
    ports,
    baudrate=115200,
    data_bits=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stop_bits=serial.STOPBITS_ONE,
    timeout=0.02,
):
    '''
    :brief 从候选端口列表中打开第一个可用的串口
    :param ports: 单路径字符串或路径列表
    :param baudrate: 波特率
    :param data_bits: 数据位
    :param parity: 校验
    :param stop_bits: 停止位
    :param timeout: 读超时（秒）
    :return (Serial 实例, 成功打开的设备路径)
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
                timeout=timeout,
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
    :brief 串口唤醒/休眠帧解析
    :desc 默认帧长 5 字节，唤醒与休眠魔数可与硬件协议一致时通过构造参数覆盖。
    '''

    def __init__(
        self,
        port,
        baudrate=115200,
        wakeup_frame=b"\xaa\x55\x03\x00\xfb",
        sleep_frame=b"\xaa\x55\x02\x00\xfb",
        frame_length=5,
        data_bits=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stop_bits=serial.STOPBITS_ONE,
        timeout=0.02,
    ):
        '''
        :brief 打开串口并保存帧配置
        :param port: 设备路径或路径列表
        :param baudrate: 波特率
        :param wakeup_frame: 唤醒帧字节序列
        :param sleep_frame: 休眠帧字节序列
        :param frame_length: 每次 read 期望字节数
        '''
        self.serial_handle, self._port_name = _try_open_serial(
            port,
            baudrate=baudrate,
            data_bits=data_bits,
            parity=parity,
            stop_bits=stop_bits,
            timeout=timeout,
        )
        self.wakeup_frame = wakeup_frame
        self.sleep_frame = sleep_frame
        self.frame_length = frame_length
        self._serial_err_logged = False

    def clear_buffer(self):
        '''
        :brief 丢弃串口接收缓冲区中已有数据
        '''
        if self.serial_handle.is_open and self.serial_handle.in_waiting > 0:
            self.serial_handle.read(self.serial_handle.in_waiting)

    def read_frame(self):
        '''
        :brief 读取一帧原始字节
        :return 长度为 frame_length 的 bytes，失败或异常时可能为短于期望的空/部分数据
        '''
        if not self.serial_handle.is_open:
            return b""
        try:
            return self.serial_handle.read(self.frame_length)
        except serial.SerialException:
            if not self._serial_err_logged:
                self._serial_err_logged = True
            return b""

    def is_wakeup(self):
        '''
        :brief 读取一帧并判断是否等于唤醒魔数
        :return 是否唤醒帧
        '''
        frame = self.read_frame()
        return frame == self.wakeup_frame

    def is_sleep(self):
        '''
        :brief 读取一帧并判断是否等于休眠魔数
        :return 是否休眠帧
        '''
        frame = self.read_frame()
        return frame == self.sleep_frame

    def close(self):
        '''
        :brief 关闭串口
        '''
        if self.serial_handle.is_open:
            self.serial_handle.close()

    def __enter__(self):
        self.clear_buffer()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
