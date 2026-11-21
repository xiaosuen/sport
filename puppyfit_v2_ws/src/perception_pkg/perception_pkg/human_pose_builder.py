'''
:brief MediaPipe Pose 结果 -> robot_msgs/HumanPose 映射
:desc 按 perception_pkg 第一版接口契约填充字段；无有效检测时数值归零（bbox_center_x=0.5）。

:author ubuntu
:date 2026/03/28
:version 1.0.0
'''

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from robot_msgs.msg import HumanPose

# MediaPipe Pose 关键点索引
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24

SOURCE_DEFAULT = 'mediapipe_pose'


@dataclass
class HumanPoseMappingConfig:
    '''映射用阈值（与节点 ROS 参数对应）。'''

    keypoint_visibility_min: float = 0.5 
    ready_visibility_min: float = 0.6
    ready_min_bbox_area: float = 0.05
    dy_shoulder_max: float = 0.15
    source: str = SOURCE_DEFAULT


def _get_vis(lm_list: Any, idx: int) -> float:
    if lm_list is None:
        return 0.0
    return float(lm_list.landmark[idx].visibility)


def _is_detected(lm_list: Any, vis_min: float) -> bool:
    '''
    :brief 是否认为检测到人体
    :desc 鼻或任一侧肩 visibility >= vis_min。
    '''
    if lm_list is None:
        return False
    return (
        _get_vis(lm_list, NOSE) >= vis_min
        or _get_vis(lm_list, LEFT_SHOULDER) >= vis_min
        or _get_vis(lm_list, RIGHT_SHOULDER) >= vis_min
    )


def compute_bbox_center_and_area(lm_list: Any, vis_min: float) -> tuple[float, float]:
    '''
    :brief 对所有可见性足够的点做轴对齐包围盒
    :return (bbox_center_x, bbox_area)，归一化坐标下；无有效点时 (0.5, 0.0)
    '''
    if lm_list is None:
        return 0.5, 0.0
    xs: list[float] = []
    ys: list[float] = []
    for lm in lm_list.landmark:
        if float(lm.visibility) >= vis_min:
            xs.append(float(lm.x))
            ys.append(float(lm.y))
    if not xs:
        return 0.5, 0.0
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    w = max(0.0, xmax - xmin)
    h = max(0.0, ymax - ymin)
    cx = 0.5 * (xmin + xmax)
    area = w * h
    return cx, area


def compute_trunk_angle_radians(lm_list: Any) -> float:
    '''
    :brief 躯干角（肩中点相对髋中点）与图像竖直向上的夹角
    :desc 竖直向上为 (0,-1)（y 轴向下）；向量取肩中点 - 髋中点；结果弧度 [0, pi]。
    '''
    if lm_list is None:
        return 0.0
    vis_floor = 0.3
    for idx in (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP):
        if _get_vis(lm_list, idx) < vis_floor:
            return 0.0
    sx = 0.5 * (
        float(lm_list.landmark[LEFT_SHOULDER].x)
        + float(lm_list.landmark[RIGHT_SHOULDER].x)
    )
    sy = 0.5 * (
        float(lm_list.landmark[LEFT_SHOULDER].y)
        + float(lm_list.landmark[RIGHT_SHOULDER].y)
    )
    hx = 0.5 * (float(lm_list.landmark[LEFT_HIP].x) + float(lm_list.landmark[RIGHT_HIP].x))
    hy = 0.5 * (float(lm_list.landmark[LEFT_HIP].y) + float(lm_list.landmark[RIGHT_HIP].y))
    vx = sx - hx
    vy = sy - hy
    norm = math.hypot(vx, vy)
    if norm < 1e-6:
        return 0.0
    # 与 (0, -1) 的夹角
    dot = -vy
    cos_t = max(-1.0, min(1.0, dot / norm))
    return float(math.acos(cos_t))


def _is_ready_pose(lm_list: Any, cfg: HumanPoseMappingConfig, bbox_area: float) -> bool:
    if lm_list is None:
        return False
    for idx in (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP):
        if _get_vis(lm_list, idx) < cfg.ready_visibility_min:
            return False
    y_l = float(lm_list.landmark[LEFT_SHOULDER].y)
    y_r = float(lm_list.landmark[RIGHT_SHOULDER].y)
    if abs(y_l - y_r) >= cfg.dy_shoulder_max:
        return False
    if bbox_area < cfg.ready_min_bbox_area:
        return False
    return True


def build_human_pose(
    mp_landmarks: Optional[Any],
    stamp: Any,
    frame_id: str,
    cfg: HumanPoseMappingConfig,
) -> HumanPose:
    '''
    :brief 由 MediaPipe pose_landmarks 构造 HumanPose
    :param mp_landmarks: results.pose_landmarks，可为 None
    :param stamp: builtin_interfaces/Time 或兼容类型
    :param frame_id: header.frame_id
    :param cfg: 映射阈值
    :return 填充后的 HumanPose（每帧均发布）
    '''
    msg = HumanPose()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.source = cfg.source

    if mp_landmarks is None or not _is_detected(mp_landmarks, cfg.keypoint_visibility_min):
        msg.detected = False
        msg.ready_pose = False
        msg.trunk_angle = 0.0
        msg.bbox_area = 0.0
        msg.bbox_center_x = 0.5
        return msg

    cx, area = compute_bbox_center_and_area(mp_landmarks, cfg.keypoint_visibility_min)
    msg.detected = True
    msg.bbox_center_x = float(cx)
    msg.bbox_area = float(area)
    msg.trunk_angle = compute_trunk_angle_radians(mp_landmarks)
    msg.ready_pose = _is_ready_pose(mp_landmarks, cfg, area)
    return msg
