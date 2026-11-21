from setuptools import find_packages, setup

package_name = "video_record_pkg"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="slt",
    maintainer_email="3490597208@qq.com",
    description="Session-scoped video recording from ROS image topic",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "session_video_record = video_record_pkg.session_video_record_node:main",
        ],
    },
)
