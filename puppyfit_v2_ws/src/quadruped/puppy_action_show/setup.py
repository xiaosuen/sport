import os
from glob import glob
from setuptools import find_packages, setup

package_name = "puppy_action_show"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ubuntu",
    maintainer_email="ubuntu@todo.todo",
    description="PuppyPi 动作组表演：话题/服务触发 .d6a/.d6ac",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "action_show_node = puppy_action_show.action_show_node:main",
            "list_action_groups = puppy_action_show.list_action_groups:main",
        ],
    },
)
