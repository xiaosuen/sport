'''
:brief voice_pkg 共享路径工具
:desc 解析 Sherpa ONNX 模型默认目录：优先使用 ament 安装后的 share 路径，
     开发时回退到源码树中与本包 setup.py 同级的 models 目录。

:author ubuntu
:date 2026/03/28
:version 1.0.1
:history
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充结构化注释
    1.0.0 - 2026/03/28
        :brief 从 voice_asr_node 内联逻辑抽出
'''

from pathlib import Path

SHERPA_MODEL_DIR_NAME = "sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"

PIPER_VOICE_DIR_NAME = "zh_CN-huayan-medium"
PIPER_ONNX_BASENAME = "zh_CN-huayan-medium.onnx"


def _default_piper_models_dir() -> Path:
    '''
    :brief voice_pkg 下 models/piper 根目录（安装态 share 或源码树）
    '''
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("voice_pkg"))
        return share / "models" / "piper"
    except Exception:
        pkg_root = Path(__file__).resolve().parent.parent.parent
        return pkg_root / "models" / "piper"


def default_sherpa_model_dir() -> str:
    '''
    :brief 返回默认 Sherpa 模型目录绝对路径字符串
    :desc install：share/voice_pkg/models/<SHERPA_MODEL_DIR_NAME>；
         源码：voice_pkg/utils/paths.py 上溯三级至 ament 包根再拼 models。
    :return 模型目录路径
    '''
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("voice_pkg"))
        return str(share / "models" / SHERPA_MODEL_DIR_NAME)
    except Exception:
        pkg_root = Path(__file__).resolve().parent.parent.parent
        return str(pkg_root / "models" / SHERPA_MODEL_DIR_NAME)


def default_piper_voice_dir() -> str:
    '''
    :brief Piper 语音包目录（含 .onnx 与同目录下的 .onnx.json）
    :desc 支持两种布局：models/piper/<语音名>/xxx.onnx（上游语音包）或 models/piper/xxx.onnx（平铺）
    '''
    base = _default_piper_models_dir()
    nested = base / PIPER_VOICE_DIR_NAME / PIPER_ONNX_BASENAME
    if nested.is_file():
        return str(base / PIPER_VOICE_DIR_NAME)
    flat = base / PIPER_ONNX_BASENAME
    if flat.is_file():
        return str(base)
    return str(base / PIPER_VOICE_DIR_NAME)


def default_piper_model_onnx() -> str:
    '''
    :brief 默认 Piper 模型路径（zh_CN-huayan-medium.onnx）
    :desc 优先 models/piper/zh_CN-huayan-medium/，否则 models/piper/ 平铺
    '''
    base = _default_piper_models_dir()
    nested = base / PIPER_VOICE_DIR_NAME / PIPER_ONNX_BASENAME
    if nested.is_file():
        return str(nested)
    flat = base / PIPER_ONNX_BASENAME
    if flat.is_file():
        return str(flat)
    return str(nested)


def default_piper_config_path(onnx_path: str) -> str:
    '''
    :brief 根据 onnx 路径推断配置文件（若存在）
    '''
    p = Path(onnx_path)
    for candidate in (Path(str(p) + ".json"), p.with_suffix(".onnx.json")):
        if candidate.is_file():
            return str(candidate)
    return ""
