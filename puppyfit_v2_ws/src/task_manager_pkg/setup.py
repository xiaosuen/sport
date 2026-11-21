from setuptools import find_packages, setup

package_name = 'task_manager_pkg'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ubuntu',
    maintainer_email='3490597208@qq.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'sport_task_manager = task_manager_pkg.sport_task_manager_node:main',
            'exercise_assistant = task_manager_pkg.exercise_assistant_node:main',
            'situp_voice_orchestrator = task_manager_pkg.situp_voice_orchestrator_node:main',
        ],
    },
)
