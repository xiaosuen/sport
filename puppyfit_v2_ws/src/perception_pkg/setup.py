'''
:brief perception_pkg setuptools 安装脚本
:desc 注册 human_pose_node、安装 launch。
'''

import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'perception_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=[
        'setuptools',
        'numpy',
        'opencv-python',
        'mediapipe',
    ],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='3490597208@qq.com',
    description='Perception: HumanPose via MediaPipe',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'human_pose_node = perception_pkg.human_pose_node:main',
        ],
    },
)
