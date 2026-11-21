import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'exercise_engine_pkg'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools', 'websocket-client'],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='3490597208@qq.com',
    description='运动引擎：仰卧起坐计数与姿态检测',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'pose_detector = exercise_engine_pkg.pose_detector_node:main',
            'situp_counter = exercise_engine_pkg.situp_counter_node:main',
            'web_dashboard = exercise_engine_pkg.web_dashboard_node:main',
            'video_overlay = exercise_engine_pkg.video_overlay_node:main',
            'video_situp_test = exercise_engine_pkg.video_situp_test:main',
            'auto_position = exercise_engine_pkg.auto_position_node:main',
            'human_pose_bridge = exercise_engine_pkg.human_pose_bridge_node:main',
        ],
    },
)
