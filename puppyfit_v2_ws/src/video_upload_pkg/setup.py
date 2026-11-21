from setuptools import find_packages, setup

package_name = "video_upload_pkg"

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
    description="COS upload + notify after SessionRecordDone",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "video_cos_upload = video_upload_pkg.video_cos_upload_node:main",
        ],
    },
)
