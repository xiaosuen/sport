import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'timer_interrupt'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='slt',
    maintainer_email='slt@example.com',
    description='通用定时中断包 - 在指定时间后向配置的控制话题发送 stop，支持仰卧起坐/俯卧撑等多运动',
    license='MIT',
    entry_points={
        'console_scripts': [
            'timer = timer_interrupt.timer_node:main',
        ],
    },
)
