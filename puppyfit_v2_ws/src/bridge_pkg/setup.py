import os
from glob import glob

from setuptools import find_packages, setup

package_name = "bridge_pkg"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
    ],
    install_requires=["setuptools", "paho-mqtt>=1.6.0", "websocket-client>=1.0.0"],
    zip_safe=True,
    maintainer="ubuntu",
    maintainer_email="3490597208@qq.com",
    description="MQTT telemetry bridge (ROS2 → MQTT), migrated from puppyfit_ws mqtt_bridge",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "telemetry_bridge = bridge_pkg.telemetry.node:main",
            "monitor_ws_bridge = bridge_pkg.monitor.node:main",
            "training_session_bridge = bridge_pkg.session_control.node:main",
            "teleop_mqtt_bridge = bridge_pkg.teleop_mqtt_bridge.node:main",
            "homework_voice_bridge = bridge_pkg.homework_bridge.node:main",
        ],
    },
)
