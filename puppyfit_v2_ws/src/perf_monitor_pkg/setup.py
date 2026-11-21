from setuptools import find_packages, setup

package_name = 'perf_monitor_pkg'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch',
            ['launch/perf_monitor.launch.py',
             'launch/perf_monitor_with_system.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@example.com',
    description='ROS2 system performance monitoring package',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'system_profiler = perf_monitor_pkg.system_profiler_node:main',
            'position_timer = perf_monitor_pkg.position_timer_node:main',
            'inference_recorder = perf_monitor_pkg.inference_recorder_node:main',
        ],
    },
)
