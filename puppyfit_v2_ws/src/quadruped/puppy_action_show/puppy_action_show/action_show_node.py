#!/usr/bin/env python3
'''
:brief 动作组表演节点
:desc 通过话题或服务触发 puppy_control 执行 ActionGroups 中的 .d6a / .d6ac；可选启动时发布可用动作目录。

:author ubuntu
:date 2026/03/29
:version 1.0.0
:history
    1.0.0 - 2026/03/29
        :brief 按 doc/注释.md 补充模块与类注释
'''

import time
from pathlib import Path

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from puppy_control_msgs.srv import SetRunActionName

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:
    get_package_share_directory = None


def _discover_action_files(share_pkg: str, subdir: str) -> list[str]:
    """从 puppypi_vendor 安装路径下列出动作组文件。"""
    if get_package_share_directory is None:
        return []
    try:
        base = Path(get_package_share_directory(share_pkg)) / subdir
    except Exception:
        return []
    if not base.is_dir():
        return []
    names: list[str] = []
    for pat in ("*.d6a", "*.d6ac"):
        names.extend(sorted(p.name for p in base.glob(pat)))
    return names


class ActionShowNode(Node):
    '''
    :brief 动作表演 ROS2 节点
    :desc 订阅 ~/play、提供 ~/run 服务，异步调用 puppy_control 的 runActionGroup。
    '''

    def __init__(self) -> None:
        super().__init__("puppy_action_show")
        self._cb = ReentrantCallbackGroup()

        self.declare_parameter("puppy_run_action_service", "/puppy_control/runActionGroup")
        self.declare_parameter("action_groups_share_pkg", "puppypi_vendor")
        self.declare_parameter("action_groups_subdir", "puppypi_control/ActionGroups")
        self.declare_parameter("publish_catalog_on_start", True)

        svc = self.get_parameter("puppy_run_action_service").get_parameter_value().string_value
        self._puppy_svc = svc or "/puppy_control/runActionGroup"
        share_pkg = self.get_parameter("action_groups_share_pkg").get_parameter_value().string_value
        subdir = self.get_parameter("action_groups_subdir").get_parameter_value().string_value

        self._client = self.create_client(
            SetRunActionName, self._puppy_svc, callback_group=self._cb
        )

        # 使用 ~/ 私有名，避免相对名 "play" 在根命名空间下变成 /play 导致与文档中的 /puppy_action_show/play 不一致
        self._pub_catalog = self.create_publisher(String, "~/catalog", 10)
        self.create_subscription(String, "~/play", self._on_play, 10, callback_group=self._cb)
        self.create_service(SetRunActionName, "~/run", self._on_run_service, callback_group=self._cb)

        self.get_logger().info(
            f"动作表演节点：订阅 ~/play (String 文件名)，服务 ~/run (SetRunActionName)，"
            f"转发至 {self._puppy_svc}"
        )

        if self.get_parameter("publish_catalog_on_start").value:
            files = _discover_action_files(share_pkg, subdir)
            if files:
                self.get_logger().info("可用动作组: " + ", ".join(files))
                msg = String()
                msg.data = "\n".join(files)
                self._pub_catalog.publish(msg)
            else:
                self.get_logger().warn(
                    f"未在 share/{share_pkg}/{subdir} 发现 .d6a/.d6ac（请先 colcon 安装 puppypi_vendor）"
                )

    def _wait_client_future(self, fut, timeout_sec: float) -> bool:
        """
        在回调内等待 service client 的 future，禁止用 spin_until_future_complete(本节点)，
        否则会占满执行器线程，后续 topic/service 与 client 响应都无法处理（表现为只能触发一次）。
        """
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and not fut.done() and time.monotonic() < deadline:
            time.sleep(0.002)
        return fut.done()

    def _call_puppy(self, name: str, wait: bool) -> tuple[bool, str]:
        name = (name or "").strip()
        if not name:
            return False, "empty name"
        if not self._client.wait_for_service(timeout_sec=2.0):
            return False, f"service not available: {self._puppy_svc}"
        req = SetRunActionName.Request()
        req.name = name
        req.wait = bool(wait)
        fut = self._client.call_async(req)
        if not self._wait_client_future(fut, 35.0):
            return False, "call timeout"
        res = fut.result()
        return bool(res.success), str(res.message)

    def _on_play(self, msg: String) -> None:
        data = (msg.data or "").strip()
        if not data:
            return
        self.get_logger().info(f"话题 play: 「{data}」")
        ok, m = self._call_puppy(data, False)
        if ok:
            self.get_logger().info(f"已请求执行: {m}")
        else:
            self.get_logger().error(f"执行失败: {m}")

    def _on_run_service(self, request: SetRunActionName.Request, response: SetRunActionName.Response):
        self.get_logger().info(f"服务 run: name={request.name}, wait={request.wait}")
        ok, m = self._call_puppy(request.name, request.wait)
        response.success = ok
        response.message = m
        return response


def main(args=None) -> None:
    '''
    :brief 节点入口：多线程 Executor spin
    :param args: 可选 rclpy 参数
    '''
    rclpy.init(args=args)
    node = ActionShowNode()
    exe = MultiThreadedExecutor(num_threads=4)
    exe.add_node(node)
    try:
        exe.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
