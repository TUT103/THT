import os
import math
import time

import numpy as np
import cv2
from tqdm import tqdm, trange
from scipy.optimize import linear_sum_assignment

"""
num | body_detecion | head_tracking | gt      | head_detection
1   | 20215         | 18060         |        |
2   | 145561        | 131117        |        |
3   | 278702        | 199111        |        |
4   | 280941        | 234177        |        |
5   | 561132        | 502819        |        |
6   | 137256        | 116304        |        |
7   | 32475         | 30371         |        |
8   | 100391        | 80303         |        |
"""


def print_f(item):
	for each in item:
		print(each)


def txt2list(txt_path, reserve=2):
	"""
	将txt格式的ground truth，改为list格式
	:param txt_path: 存放txt的文件名
	:param reserve: 四舍五入后保存数字的位数
	:return: 一个列表，其中的每一项为.txt的一行
			.txt中视频总的帧数
	"""
	# 读取txt中的信息
	gt_list = []
	with open(txt_path, "r") as f:
		for each_line in f:
			gt_list.append(
				[round(float(x), reserve) for x in each_line.strip("\n").strip("[").strip("]").strip(" ").split(",")])
	total_info = len(gt_list)

	# 获取总的帧数
	total_frame = 0
	for each in gt_list:
		if each[0] > total_frame:
			total_frame = each[0]

	# 将旧版本中的二维列表转换为新格式中的三维列表
	result = [[] for _ in range(int(total_frame))]
	for each in gt_list:
		result[int(each[0]) - 1].append(each)
	return result, int(total_frame), total_info


def ioc_xyxy_plus(body, head):
	"""
	IOC在匹配时使用一种类似金字塔的结构，
	越接近理想位置（中间靠上）的头部边界框，其权重指数会成倍增长
	:param body:
	:param head:
	:return:
	"""
	head_list = box_generator(head)
	weights = [1, 2, 3, 4, 5]
	result = 0
	for i, each in enumerate(head_list):
		result = result + intersection_xyxy(body, each) * weights[i]
	return result / sum(weights)


def intersection_xyxy(body, head):
	'''
	计算两个矩形框的交并比
	:param body: list,第一个矩形框的左上角和右下角坐标
	:param head: list,第二个矩形框的左上角和右下角坐标
	:return: 两个矩形框的交并比iou
	'''
	x1 = max(body[0], head[0])  # 交集左上角x
	x2 = min(body[2], head[2])  # 交集右下角x
	y1 = max(body[1], head[1])  # 交集左上角y
	y2 = min(body[3], head[3])  # 交集右下角y

	overlap = max(0., x2 - x1) * max(0., y2 - y1)
	return overlap / ((head[2] - head[0]) * (head[3] - head[1]))


def box_generator(head):
	"""
	输入格式为xyxy的边界框，生成里面的5个小框
	:param head:
	:return:
	"""
	head_width = head[2] - head[0]
	head_height = head[3] - head[1]
	head_list = []
	count = [0.0, 0.1, 0.2, 0.3, 0.4]
	for i in range(5):
		# print(head_width * count[i], head_height * count[i])
		head_list_single = []
		head_list_single.append(head[0] + head_width * count[i])
		head_list_single.append(head[1] + head_height * count[i])
		head_list_single.append(head[2] - head_width * count[i])
		head_list_single.append(head[3] - head_height * count[i])
		head_list.append(head_list_single)
	return head_list


def cut_bbox_xyxy(bbox_xyxy, reserve_body_top=50., reserve_body_mid=0.6):
	new_list = [0 for _ in range(4)]
	new_list[3] = bbox_xyxy[1] + reserve_body_top
	temp = bbox_xyxy[4 - 2] - bbox_xyxy[0]
	new_list[0] = bbox_xyxy[0] + temp * (1 - reserve_body_mid) / 2
	new_list[2] = bbox_xyxy[2] - temp * (1 - reserve_body_mid) / 2
	new_list[1] = bbox_xyxy[1]
	return new_list


def cut_bbox_xyxy_V2(bbox_xyxy, reserve_body_top=35., add_body_top=5, reserve_body_mid=0.6):
	"""
	在执行IOC之前，剪掉身体边界框靠下和左右的部分
	:param bbox_xyxy:
	:param reserve_body_top:
	:param add_body_top:
	:param reserve_body_mid:
	:return:
	"""
	new_list = [0 for _ in range(4)]
	new_list[3] = bbox_xyxy[1] + reserve_body_top
	temp = bbox_xyxy[4 - 2] - bbox_xyxy[0]
	new_list[0] = bbox_xyxy[0] + temp * (1 - reserve_body_mid) / 2
	new_list[2] = bbox_xyxy[2] - temp * (1 - reserve_body_mid) / 2
	new_list[1] = bbox_xyxy[1] - add_body_top
	return new_list


def new_delete(a, b):
	new = []
	deleted = []
	for each in a:
		if each not in b:
			new.append(each)
	for each in b:
		if each not in a:
			deleted.append(each)
	return new, deleted


def id_recorder(video_id):
	"""
	查看每一帧中新增和删除后的目标id
	:param video_id:
	:return:新增和删除
	"""
	head_tracking, total_frame_ht = txt2list(
		"/home/qzm/ProjectsPycharm/MOT20/MOT20_head_tracking/formated_MOT20_" + video_id + "_head_tracking.txt")
	id_list_new = []
	id_list_old = []
	for frame_id, info_each_frame in enumerate(head_tracking):
		id_list_old.clear()
		for each in id_list_new:
			id_list_old.append(int(each))
		id_list_new.clear()
		for item in info_each_frame:
			id_list_new.append(int(item[1]))
		new, deleted = new_delete(id_list_new, id_list_old)
		print("frame_id", frame_id)
		print("new:", new)
		print("deleted", deleted)


def main(video_id):
	# print("正在进行视频", video_id)
	head_tracking, total_frame_ht, total_head = txt2list(
		"./MOT20_head_tracking/MOT20_" + video_id + "_head_tracking.txt")
	body_detection, total_frame_bd, total_body = txt2list(
		"./MOT20_body_detection/MOT20-" + video_id + "_body_detection.txt")
	assert total_frame_ht == total_frame_bd, "head_tracking和body_detection帧数不一致"

	total_matched_index = 0
	results = []
	for frame_id in trange(total_frame_ht, desc="MOT20-" + video_id):  # 此处的frame_id从0开始计数
		cost_matrix = np.ones((len(body_detection[frame_id]), len(head_tracking[frame_id]))) * 0
		for i in range(len(body_detection[frame_id])):
			for j in range(len(head_tracking[frame_id])):
				cost_matrix[i][j] = intersection_xyxy(cut_bbox_xyxy_V2(body_detection[frame_id][i][2:6]),
				                                  head_tracking[frame_id][j][2:6])
		# M = np.where(cost_matrix != 0)
		# m = len(M[0])
		# n = len(M[1])

		no_indexs_body = []  # 记录下cost_matrix中没有head与之匹配的body
		no_indexs_head = []
		for index, each in enumerate(cost_matrix):
			if sum(each) == 0:
				no_indexs_body.append(index)
		for index, each in enumerate(cost_matrix.T):
			if sum(each) == 0:
				no_indexs_head.append(index)

		cost_matrix = 1.1 - cost_matrix
		c_row_index, c_column_index = linear_sum_assignment(cost_matrix)
		c_row_index = c_row_index.tolist()
		c_column_index = c_column_index.tolist()
		assert len(c_row_index) == len(c_column_index)
		# print(
		# 	"帧ID:", str(frame_id + 1).zfill(6),
		# "  body数量:", len(body_detection[frame_id]),
		# "  head数量:", len(head_tracking[frame_id]),
		# "  暂时认为匹配成功的body和head数量:", len(c_row_index), len(c_column_index),
		# "  缺失的body和head数量:", len(no_indexs_body), len(no_indexs_head)
		# )

		# print(c_row_index)
		# print(c_column_index)
		# print(body_detection[frame_id])
		# print(head_tracking[frame_id])

		total_matched_index += len(c_row_index)
		head_tracking_reg = []
		for each in head_tracking[frame_id]:
			head_tracking_reg.append(each)
		for row, column in zip(c_row_index, c_column_index):
			head_tracking_reg[column][2:6] = body_detection[frame_id][row][2:6]
		for each in head_tracking_reg:
			# print(each)
			results.append(each)
	# for each in head_tracking[frame_id]:
	# 	print(each)
	# 	results.append(each)

	print("检测到总的身体数"+total_body, "  检测到总的头部数"+total_head, "  成功匹配的对数"+total_matched_index)
	with open("./results/MOT20-" + video_id + ".txt", "w") as f:
		for each in results:
			each[0] = int(each[0])
			each[1] = int(each[1])
			each[4] = each[4] - each[2]
			each[5] = each[5] - each[3]
			each[6] = -1
			each[7] = -1
			each[8] = -1
			each[9] = -1
			f.write(
				str(each).replace("[", "").replace("]", "").replace(" ", "") + "\n"
			)


if __name__ == "__main__":
	start = time.time()
	seq = "all"
	seqs = ["tain", "test", "all", "single"]
	if seq == "train":
		for i in range(3):
			main(str(i + 1).zfill(2))
		main("05")
	if seq == "test":
		main("04")
		for i in range(5, 8):
			main(str(i + 1).zfill(2))
	if seq == "all":
		for i in range(8):
			main(str(i + 1).zfill(2))
	if seq == "single":
		main("01")
	print("运行总时长：%.2f" % (time.time() - start))
	"""	
	MOT20 - 01: 100 % |██████████ | 429 / 429[00:09 < 00: 00, 43.16it / s]
	MOT20 - 02: 100 % |██████████ | 2782 / 2782[01:24 < 00:00, 32.90it / s]
	MOT20 - 03: 100 % |██████████ | 2405 / 2405[04:35 < 00:00, 8.73it / s]
	MOT20 - 04: 100 % |██████████ | 2080 / 2080[06:02 < 00:00, 5.74it / s]
	MOT20 - 05: 100 % |██████████ | 3315 / 3315[16:14 < 00:00, 3.40it / s]
	MOT20 - 06: 100 % |██████████ | 1008 / 1008[03:00 < 00:00, 5.58it / s]
	MOT20 - 07: 100 % |██████████ | 585 / 585[00:20 < 00:00, 27.97it / s]
	MOT20 - 08: 100 % |██████████ | 806 / 806[01:54 < 00:00, 7.06it / s]
	"""
# id_recorder("01")
