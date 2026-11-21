#!/usr/bin/env python3
'''
:brief 仰卧起坐录屏视频测试
:desc 读取本地视频文件，用 MediaPipe + SitUpCounter 统计仰卧起坐个数（不依赖 ROS）。

:author slt&zxh
:date 2026/03
:version 1.0.1
:history
    1.0.0 - 2026/03
        :brief 初始脚本
    1.0.1 - 2026/03/29
        :brief 按 doc/注释.md 统一模块注释格式
'''

import argparse
import sys

import cv2
import mediapipe as mp

from exercise_engine_pkg.core.situp_counter import SitUpCounter


# 与 pose_detector_node 一致的关键点索引
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24


def landmark_to_dict(lm):
    """MediaPipe landmark -> 供 SitUpCounter 使用的 dict"""
    return {
        "x": lm.x,
        "y": lm.y,
        "z": lm.z,
        "visibility": getattr(lm, "visibility", 1.0),
    }


def main():
    parser = argparse.ArgumentParser(description="对录屏视频测试仰卧起坐计数")
    parser.add_argument(
        "video_path",
        type=str,
        help="视频文件路径，例如 /path/to/situp.mp4",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="播放视频并显示骨架与计数（按 q 退出）",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="MediaPipe 检测/跟踪置信度下限（默认 0.5）",
    )
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.video_path)
    if not cap.isOpened():
        print(f"错误：无法打开视频 {args.video_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"视频: {args.video_path}")
    print(f"帧率: {fps:.1f}, 总帧数: {total_frames}")

    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    pose = mp_pose.Pose(
        min_detection_confidence=args.min_confidence,
        min_tracking_confidence=args.min_confidence,
    )
    counter = SitUpCounter()

    frame_idx = 0
    last_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(frame_rgb)

        if results.pose_landmarks:
            lms = results.pose_landmarks.landmark
            if len(lms) < 33:
                continue
            left_shoulder = landmark_to_dict(lms[LEFT_SHOULDER])
            right_shoulder = landmark_to_dict(lms[RIGHT_SHOULDER])
            left_hip = landmark_to_dict(lms[LEFT_HIP])
            right_hip = landmark_to_dict(lms[RIGHT_HIP])

            def visible(*pts):
                return all(p["visibility"] >= 0.5 for p in pts)

            if not visible(left_shoulder, right_shoulder, left_hip, right_hip):
                continue

            if not counter.get_init_state():
                counter.process_init(
                    left_shoulder, right_shoulder, left_hip, right_hip
                )
            else:
                counter.process_frame(left_shoulder, right_shoulder)

            current = counter.get_count()
            if current != last_count:
                print(f"  帧 {frame_idx}: 计数 -> {current}")
                last_count = current

            if args.display:
                mp_drawing.draw_landmarks(
                    frame,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                )
                state_str = counter.get_state_string()
                cv2.putText(
                    frame,
                    f"Count: {current}  State: {state_str}",
                    (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.2,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow("Sit-up test", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("用户中断")
                    break

    cap.release()
    pose.close()
    if args.display:
        cv2.destroyAllWindows()

    print("--------")
    print(f"最终仰卧起坐个数: {counter.get_count()}")


if __name__ == "__main__":
    main()
