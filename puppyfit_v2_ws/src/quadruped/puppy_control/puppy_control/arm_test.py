#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
机械臂动作组测试节点。

功能：
- 作为 ROS2 节点启动后，调用服务 `/puppy_control/runActionGroup`
- 请求执行指定动作组文件（此处为 `arm_test.d6a`）
- 等待响应后打印结果，并主动关闭 rclpy

适用场景：
- 验证动作组服务是否可用
- 验证动作组文件是否能正常执行（blocking 模式）
"""

import rclpy
from rclpy.node import Node
from puppy_control_msgs.srv import SetRunActionName

class PuppyArmController(Node):
    def __init__(self):
        super().__init__('puppy_arm_controller')
        # 创建到动作组服务的客户端
        self.client = self.create_client(SetRunActionName, '/puppy_control/runActionGroup')
        
        # 等待服务上线（通常依赖 puppy_control 主节点/驱动启动完成）
        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('Service not available, waiting...')
        
        self.send_request()

    def send_request(self):
        request = SetRunActionName.Request()
        # 动作组文件名（通常位于动作组资源目录，由底层节点解释/执行）
        request.name = 'arm_test.d6a'
        
        # 兼容不同版本 srv：部分版本提供 blocking 字段，表示服务端执行完才返回
        if hasattr(request, 'blocking'):
            request.blocking = True  
        
        self.get_logger().info(f'Sending request: {request}')
        future = self.client.call_async(request)
        # 异步调用：通过回调获取结果
        future.add_done_callback(self.response_callback)

    def response_callback(self, future):
        try:
            response = future.result()
            self.get_logger().info(
                f'Service call succeeded. Success: {response.success}'
                f', Message: {response.message if hasattr(response, "message") else "None"}'
            )
        except Exception as e:
            self.get_logger().error(f'Service call failed: {str(e)}')
        finally:
            # 本脚本执行一次请求即退出
            rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    controller = PuppyArmController()
    rclpy.spin(controller)
    controller.destroy_node()

if __name__ == "__main__":
    main()
