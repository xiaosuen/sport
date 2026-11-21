#!/usr/bin/env python3
# coding=utf8

import sys
import math
import rclpy
from rclpy.node import Node
from std_srvs.srv import SetBool
from puppy_control_msgs.msg import Velocity, Pose, Gait

ROS_NODE_NAME = 'puppy_demo'

PuppyMove = {'x': 5.0, 'y': 0.0, 'yaw_rate': 0.0}
# x:straightforward control, with the forward direction as the positive direction, measured in cm/s(直行控制，  前进方向为正方向，单位cm/s)
# y:lateral movement control, with the left direction as the positive direction, measured in cm/s. currently, this feature is bot available(侧移控制，左侧方向为正方向，单位cm/s，目前无此功能)
# yaw_rate：turning control, with counterclockwise direction as the positive direction, measured in rad/s(转弯控制，逆时针方向为正方向，单位rad/s)
PuppyPose = {'roll': math.radians(0), 'pitch': math.radians(0), 'yaw': 0.000, 'height': -10.0, 'x_shift': 0.5, 'stance_x': 0.0, 'stance_y': 0.0}
# PuppyPose = {'roll':math.radians(0), 'pitch':math.radians(0), 'yaw':0.000, 'height':-10, 'x_shift':-0.5, 'stance_x':0, 'stance_y':0}
# stance_x：the distance extra apart for each of the four legs on the X-axis, measured in centimeters(4条腿在x轴上额外分开的距离，单位cm)
# stance_y：the distance extra apart for each of the four legs on the Y-axis, measured in centimeters(4条腿在y轴上额外分开的距离，单位cm)
# x_shift: the distance traveled by the four legs along the x-axis determines the degree of forward or backward tilt during walking: smaller distances lead to more forward tilt, while larger distances result in more backward tilt. Adjusting the x_shift parameter can help maintain balance during the dog's movement, measured in centimeters(4条腿在x轴上同向移动的距离，越小，走路越前倾，越大越后仰,通过调节x_shift可以调节小狗走路的平衡，单位cm)
# height： the height of the dog, measured from the toe to the axis  of rotation of the thigh, is in centimeters(狗的高度，脚尖到大腿转动轴的垂直距离，单位cm)
# pitch： the pitch angle of the dog's body, measured in radians(狗身体的俯仰角，单位弧度)

gait = 'Trot'
# overlap_time:the time when all four legs touch the ground, measured in seconds(4脚全部着地的时间，单位秒)
# swing_time：the time duration when a single leg is off the ground, measured in second(单脚离地时间，单位秒)
# clearance_time：the time interval between the phases when the front and rear legs cross each other, measured in seconds(前后交叉脚相位间隔时间，单位秒)
# z_clearance：the distance the paw needs to be raised during walking, measured in centimeters(走路时，脚尖要抬高的距离，单位cm)
if gait == 'Trot':
    GaitConfig = {'overlap_time': 0.2, 'swing_time': 0.3, 'clearance_time': 0.0, 'z_clearance': 5.0}
    PuppyPose['x_shift'] = -0.6
    # Trot gait clearance_time = 0(Trot步态 clearance_time = 0)
elif gait == 'Amble':
    GaitConfig = {'overlap_time': 0.1, 'swing_time': 0.2, 'clearance_time': 0.1, 'z_clearance': 5.0}
    PuppyPose['x_shift'] = -0.9
     # Amble gait 0 ＜ clearance_time ＜ swing_time( Amble步态 0 ＜ clearance_time ＜ swing_time)
elif gait == 'Walk':
    GaitConfig = {'overlap_time': 0.1, 'swing_time': 0.2, 'clearance_time': 0.3, 'z_clearance': 5.0}
    PuppyPose['x_shift'] = -0.65
     # Amble步态 0 ＜ clearance_time ＜ swing_time(Walk步态   swing_time ≤ clearance_time)

class PuppyDemoNode(Node):
    def __init__(self):
        super().__init__(ROS_NODE_NAME)
        self.PuppyPosePub = self.create_publisher(Pose, '/puppy_control/pose', 10)
        self.PuppyGaitConfigPub = self.create_publisher(Gait, '/puppy_control/gait', 10)
        self.PuppyVelocityPub = self.create_publisher(Velocity, '/puppy_control/velocity', 10)
        self.set_mark_time_client = self.create_client(SetBool, '/puppy_control/set_mark_time')
        self.timer = self.create_timer(0.05, self.timer_callback)
        self.publish_initial_commands()
        # stepping in place service(原地踏步服务)

    def publish_initial_commands(self):
        self.PuppyPosePub.publish(Pose(stance_x=PuppyPose['stance_x'], stance_y=PuppyPose['stance_y'], x_shift=PuppyPose['x_shift'],
                                       height=PuppyPose['height'], roll=PuppyPose['roll'], pitch=PuppyPose['pitch'], yaw=PuppyPose['yaw'], run_time=500))
        self.PuppyGaitConfigPub.publish(Gait(overlap_time=GaitConfig['overlap_time'], swing_time=GaitConfig['swing_time'],
                                             clearance_time=GaitConfig['clearance_time'], z_clearance=GaitConfig['z_clearance']))
        self.PuppyVelocityPub.publish(Velocity(x=PuppyMove['x'], y=PuppyMove['y'], yaw_rate=PuppyMove['yaw_rate']))
        ## if the dog continues to move slowly forward on backward while stepping in place, it is necessary to readjust the dog's center of gravity. simply fine-tune 'x_shift' in PuppyPose(如果原地踏步期间，小狗仍然在缓慢的向前或向后，那就需要重新调整小狗重心，微调PuppyPose['x_shift']即可)

        while not self.set_mark_time_client.wait_for_service(timeout_sec=0.0):
            self.get_logger().info('service not available, waiting again...')

        future = self.set_mark_time_client.call_async(SetBool.Request(data=False))
        rclpy.spin_until_future_complete(self, future)
        if future.result() is not None:
            self.get_logger().info('Service call succeeded')
        else:
            self.get_logger().info('Service call failed')

    def timer_callback(self):
        if rclpy.ok():
            pass  
        else:
            sys.exit(0)


def main(args=None):
    rclpy.init(args=args)
    puppy_demo_node = PuppyDemoNode()
    
    try:
        rclpy.spin(puppy_demo_node)
    except KeyboardInterrupt:
        pass
    finally:
        puppy_demo_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

