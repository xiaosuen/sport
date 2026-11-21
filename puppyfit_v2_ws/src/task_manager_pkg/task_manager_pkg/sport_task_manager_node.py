'''
:brief 运动任务管理节点
:desc 订阅 /asr/text 驱动任务上下文与状态机，周期性发布 robot_msgs/TaskStatus 与
      std_msgs/String 至 /voice/speak；与运动计数、语音播报协同。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块与类注释
'''

import rclpy
from rclpy.node import Node

from std_msgs.msg import String
from robot_msgs.msg import TaskStatus

from task_manager_pkg.core.task_context import TaskContext
from task_manager_pkg.core.task_state import TaskState


class SportTaskManagerNode(Node):
    '''
    :brief 运动任务管理 ROS2 节点
    :desc 维护 TaskContext、定时发布状态与语音文案。
    '''

    def __init__(self):
        super().__init__("sport_task_manager")

        # 勿用 context：Node 基类已有只读属性 context（rclpy 上下文）
        self.task_context = TaskContext()

        # 发布任务状态
        self.status_pub = self.create_publisher(TaskStatus, "/task/status", 10)

        # 发布语音播报文本
        self.voice_pub = self.create_publisher(String, "/voice/speak", 10)

        # 订阅 ASR 文本输入
        self.asr_sub = self.create_subscription(
            String,
            "/asr/text",
            self.on_asr_text,
            10
        )

        # 周期性发布状态
        self.timer = self.create_timer(1.0, self.on_timer)

        self.get_logger().info("SportTaskManagerNode started.")

    def on_asr_text(self, msg: String):
        text = msg.data.strip()
        self.get_logger().info(f"Received ASR text: {text}")

        if self.is_start_situp_command(text):
            self.handle_start_situp()
        elif self.is_stop_command(text):
            self.handle_stop_task()
        else:
            self.get_logger().info("Unrecognized ASR command, ignored.")

    def is_start_situp_command(self, text: str) -> bool:
        candidates = [
            "开始做仰卧起坐",
            "开始仰卧起坐",
            "开始situp",
            "开始做situp",
        ]
        return text in candidates

    def is_stop_command(self, text: str) -> bool:
        candidates = [
            "停止",
            "结束",
            "停止任务",
            "结束任务",
        ]
        return text in candidates

    def handle_start_situp(self):
        if self.task_context.state != TaskState.IDLE:
            self.get_logger().warn(
                f"Task already active, current state: {self.task_context.state.value}"
            )
            self.publish_voice("当前任务尚未结束")
            return

        self.task_context.task_name = "situp"
        self.task_context.current_count = 0
        self.task_context.target_count = 20
        self.task_context.state = TaskState.WAITING_USER
        self.task_context.message = "start command received, waiting user ready"

        self.get_logger().info("Start situp task triggered.")
        self.publish_voice("开始仰卧起坐，请到指定位置准备")

    def handle_stop_task(self):
        if self.task_context.state == TaskState.IDLE:
            self.get_logger().info("No active task to stop.")
            self.publish_voice("当前没有正在进行的任务")
            return

        self.task_context.state = TaskState.FINISHED
        self.task_context.message = "task stopped by user"

        self.get_logger().info("Task stopped by user.")
        self.publish_voice("任务已结束")

    def publish_voice(self, text: str):
        msg = String()
        msg.data = text
        self.voice_pub.publish(msg)
        self.get_logger().info(f"Publish voice text: {text}")

    def on_timer(self):
        '''
        :brief 定时器回调：周期性发布任务状态
        :desc WAITING_USER 保持；FINISHED 发布一拍后 reset 回到 IDLE。
        '''

        if self.task_context.state == TaskState.FINISHED:
            # 给外部留一个周期看到 FINISHED 状态，然后回到 IDLE
            self.publish_status()
            self.task_context.reset()
            return

        self.publish_status()

    def publish_status(self):
        msg = TaskStatus()
        msg.task_name = self.task_context.task_name
        msg.state = self.task_context.state.value
        msg.current_count = self.task_context.current_count
        msg.target_count = self.task_context.target_count
        msg.message = self.task_context.message

        self.status_pub.publish(msg)

        self.get_logger().info(
            f"Publish TaskStatus: "
            f"task={msg.task_name}, state={msg.state}, "
            f"count={msg.current_count}/{msg.target_count}, "
            f"message={msg.message}"
        )


def main(args=None):
    '''
    :brief 节点入口：初始化、spin、清理
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = SportTaskManagerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()