'''
:brief voice_pkg setuptools 安装脚本
:desc 注册 ament_python 包、console_scripts、launch 与 models 资源安装规则。

:author slt
:date 2026/03/28
:version 1.0.1
:history
    1.0.1 - 2026/03/28
        :brief 按 doc/注释.md 补充模块注释
    1.0.0 - 2026/03/28
        :brief 初始迁移版本
'''

import os
from glob import glob

from setuptools import find_packages, setup

package_name = "voice_pkg"

data_files = [
    ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
    ("share/" + package_name, ["package.xml"]),
    (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
]
for model_dir in ("models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23",):
    if os.path.isdir(model_dir):
        for root, _dirs, files in os.walk(model_dir):
            for f in files:
                src = os.path.join(root, f)
                dest_dir = os.path.join("share", package_name, root)
                data_files.append((dest_dir, [src]))

_piper_skip = {"build", "log", "install", "__pycache__"}
_piper_root = "models/piper"
if os.path.isdir(_piper_root):
    for root, dirs, files in os.walk(_piper_root):
        dirs[:] = [d for d in dirs if d not in _piper_skip]
        for f in files:
            src = os.path.join(root, f)
            dest_dir = os.path.join("share", package_name, root)
            data_files.append((dest_dir, [src]))

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=data_files,
    install_requires=[
        "setuptools",
        "numpy",
        "pyserial",
        "sherpa-onnx",
        "sounddevice",
    ],
    extras_require={
        "piper": ["piper-tts[zh]>=1.3.0", "onnxruntime>=1,<2"],
    },
    zip_safe=True,
    maintainer="ubuntu",
    maintainer_email="3490597208@qq.com",
    description="Voice: ASR (sherpa-onnx) and TTS (Piper ONNX / espeak), migrated from puppyfit_ws asr/tts",
    license="TODO: License declaration",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "voice_asr = voice_pkg.asr.voice_asr_node:main",
            "voice_tts = voice_pkg.tts.voice_tts_node:main",
            "counting_tts = voice_pkg.tts.counting_tts_node:main",
            "situp_result_tts = voice_pkg.tts.situp_result_tts_node:main",
        ],
    },
)
