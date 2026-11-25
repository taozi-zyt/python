# -*- coding: utf-8 -*-
"""感知与几何层：截图、定位棋盘/参考图、把参考图切成 5×5、环序。

本模块只负责「画面里有什么、在哪」，不做任何落子决策。
对外接口：
    find_win()                     -> 窗口对象
    grab(win)                      -> BGR 截图（与鼠标同一套屏幕坐标）
    detect_board(img)              -> 棋盘矩形 (x, y, w, h)
    detect_ref(img, board)         -> 参考图矩形
    ref_cells(img, ref)            -> {(r,c): {img, mean, std, white}}
    resolve_geometry(win, img)     -> (board, ref)  检测失败时用 layout.json 兜底
    ring_order()                   -> 外圈 -> 内圈的格子顺序

关键事实（逆向自站点源码）：
    参考图与拼图碎片是同一张图，所以「模板匹配」可唯一确定「哪块放哪格」，
    不需要 YOLO 之类的分类模型。
"""
import os
import json
import ctypes
import ctypes.wintypes

import numpy as np
import cv2
import mss
import pygetwindow as gw

try:                       # 让截图坐标与鼠标坐标保持一致
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_PATH = os.path.join(HERE, "layout.json")

N = 5              # 每边格数（5×5）
BG = 45            # 画布背景灰度上限


# ---------------------------------------------------------------- 采集
BROWSERS = {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe"}


def _proc_name(hwnd):
    """取窗口所属进程名（小写）。用于区分「浏览器」与「编辑器/资源管理器」。"""
    if not hwnd:
        return ""
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(260)
    size = ctypes.wintypes.DWORD(260)
    try:
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return ""


def find_win():
    """定位游戏窗口。

    三级匹配（顺序很重要）：
      1. 标题含「拼图」且进程是浏览器 —— 页面标题就是「拼图视觉考核」，最可靠；
      2. 进程是浏览器、尺寸足够大 —— 处理「游戏不在当前标签页、标题被换掉」的情况；
      3. 放弃，返回 None（绝不返回编辑器/资源管理器，否则会对着错误窗口操作）。

    ⚠️ 不能用「标题含 puzzle」来匹配：代码目录名 puzzle_v3 会让编辑器窗口命中。
    """
    wins = []
    for w in gw.getAllWindows():
        t = (w.title or "").strip()
        if not t or w.width < 900 or w.height < 600:
            continue
        wins.append((w, _proc_name(getattr(w, "_hWnd", None))))

    for w, proc in wins:
        if "拼图" in w.title and proc in BROWSERS:
            return w
    for w, proc in wins:
        if proc in BROWSERS:
            return w
    return None


def grab(win):
    """按窗口矩形截图（不是整屏）。返回 BGR 数组，坐标即屏幕物理像素。"""
    with mss.MSS() as sct:
        r = {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
        return np.array(sct.grab(r))[:, :, :3]


# ---------------------------------------------------------------- 几何
def detect_board(img):
    """用棋盘底色 #0f172a 的连通域定位棋盘。

    碎片放上去后会盖住大部分棋盘，所以只要求外接矩形够大、且连通域本身
    有足够像素（填充率 > 0.12），不要求「接近实心」——否则残局必然失败。
    """
    target = np.array([42, 23, 15], dtype=np.int16)          # #0f172a (BGR)
    d = np.abs(img.astype(np.int16) - target).sum(axis=2)
    mask = (d < 18).astype(np.uint8)
    n, lab, st, ce = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if w > 400 and h > 300 and area > 0.12 * w * h:
            if best is None or area > best[4]:
                best = (x, y, w, h, area)
    return tuple(int(v) for v in best[:4]) if best else None


def detect_ref(img, board):
    """参考图 = 棋盘右侧最大的「接近实心」亮块（它不会被遮挡，所以填充率要求 0.9）。"""
    bx, by, bw, bh = board
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = np.zeros_like(g)
    x_start = bx + bw + 40
    m[by - 40:, x_start:] = (g[by - 40:, x_start:] > BG).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if w > 400 and h > 300 and area > w * h * 0.9:
            if best is None or area > best[4]:
                best = (x, y, w, h, area)
    return tuple(int(v) for v in best[:4]) if best else None


def load_layout(win):
    """同一窗口尺寸下验证过的几何缓存（棋盘被碎片盖住时检测会失败，用这个兜底）。"""
    try:
        data = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    except Exception:
        return None
    for rec in data.get("layouts", []):
        if abs(rec["w"] - win.width) <= 4 and abs(rec["h"] - win.height) <= 4:
            return rec
    return None


def save_layout(win, board, ref):
    """记录本次成功检测的几何（同窗口尺寸只保留最新一条）。"""
    data = {"layouts": []}
    if os.path.exists(LAYOUT_PATH):
        try:
            data = json.load(open(LAYOUT_PATH, encoding="utf-8"))
            if "layouts" not in data:
                data = {"layouts": []}
        except Exception:
            pass
    keep = [r for r in data["layouts"]
            if not (abs(r["w"] - win.width) <= 4 and abs(r["h"] - win.height) <= 4)]
    keep.append({"w": win.width, "h": win.height,
                 "board": list(board), "ref": list(ref)})
    data["layouts"] = keep
    with open(LAYOUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def resolve_geometry(win, img, verbose=True):
    """先检测，失败则用同尺寸窗口的布局缓存。返回 (board, ref)。"""
    board = detect_board(img)
    ref = detect_ref(img, board) if board else None
    if board and ref:
        save_layout(win, board, ref)
        return board, ref
    cached = load_layout(win)
    if cached:
        if verbose:
            print(f"检测失败，使用布局缓存 board={cached['board']} ref={cached['ref']}")
        return tuple(cached["board"]), tuple(cached["ref"])
    return board, ref


# ---------------------------------------------------------------- 参考图分格
def ref_cells(img, ref):
    """把参考图切成 5×5，逐格给出灰度小块与「是否纯白格」。

    白格判据（两条缺一不可）：
      * mean > 243：纯白格整格几乎全 255（实测 254.5~254.9），照片格 ≤ 221；
      * std  < 8  ：纯白格内部无明暗变化（实测 0.8~3.8，噪声来自 JPEG/缩放/抗锯齿），
                    照片格 ≥ 23。只看 mean 会把「白底照片」误判成白格。
    """
    rx, ry, rw, rh = ref
    out = {}
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for r in range(N):
        for c in range(N):
            x0 = int(rx + c * rw / N); x1 = int(rx + (c + 1) * rw / N)
            y0 = int(ry + r * rh / N); y1 = int(ry + (r + 1) * rh / N)
            cell = g[y0:y1, x0:x1]
            mean, std = float(cell.mean()), float(cell.std())
            out[(r, c)] = {"img": cell, "mean": mean, "std": std,
                           "white": mean > 243 and std < 8}
    return out


def ring_order():
    """外圈 -> 内圈。吸附要求「有锚点」，所以必须先放外圈（棋盘边框即锚点）。"""
    order = []
    for d in range((N + 1) // 2):
        for r in range(N):
            for c in range(N):
                if min(r, c, N - 1 - r, N - 1 - c) == d:
                    order.append((r, c))
    return order
