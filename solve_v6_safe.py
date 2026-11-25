# -*- coding: utf-8 -*-
"""判据与执行层：区域截图、就绪闸门、快速指派、真实鼠标拖拽、吸附判定。

核心设计：**「是否吸附」不看形状、不看位置，只看进度计数器有没有变。**
吸附必然使 `进度 N/25` +1 → 文本像素必变；不吸附则像素逐点相同。
这把一个 OCR 问题降维成二元判据，实测 100% 可靠，且只需 6ms。

拖拽时序是本层最脆弱的常量，都是踩坑换来的，见各常量的注释。
"""
import time
import ctypes

import numpy as np
import cv2
import mss
import pyautogui

import solve_v3 as V3
from solve_v3 import find_win, grab, ref_cells, N

pyautogui.PAUSE = 0.0          # 关掉 pyautogui 自带的每次调用延迟，自己控制节奏
pyautogui.FAILSAFE = False     # 关掉"光标到屏幕角落就抛异常"的保护

# 进度计数器（窗口内相对坐标）。只在 3098×1850 最大化窗口下成立。
PROG = (2540, 505, 250, 80)

# 步数预算：站点规则 moveTarget = ceil(pieces × 1.3)，25 格 → 33
MOVE_BUDGET = 33

# 拖拽时序（毫秒级，不能压缩）
MOVE_TO_PAUSE = 0.05
DOWN_PAUSE = 0.05        # 设 0 → 浏览器来不及记录拾取点，碎片位移恒为 0（实测 56 步落 1 块）
DRAG_DUR = 0.28          # 0.22 实测会导致大面积未吸附
UP_PAUSE = 0.06
SETTLE = 0.30            # 0.20 太短：进度计数器还没重绘就判定，会误判未吸附（34 步落 2 块）


# ------------------------------------------------------------------ 截图
def grab_prog(win):
    """只截进度计数器那 250×80（6ms，整窗要 60ms）。"""
    with mss.MSS() as sct:
        r = {"left": win.left + PROG[0], "top": win.top + PROG[1],
             "width": PROG[2], "height": PROG[3]}
        return np.array(sct.grab(r))[:, :, :3].copy()


def changed(a, b):
    """两帧的进度计数器是否"变了"——本系统唯一的吸附判据。

    int16 是必须的：uint8 相减会下溢（5 - 200 得到 61）。
    >30 过滤抗锯齿噪声；>50 个像素是分离点：数字变化约 100~300 像素，纯噪声 <20。
    """
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.int16)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.int16)
    return int((np.abs(ga - gb) > 30).sum()) > 50


# ------------------------------------------------------------------ 窗口
def force_foreground(win):
    """把窗口抢到前台：把输入队列临时挂到前台线程，绕过 Windows 前台锁。"""
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    h = u.FindWindowW(None, win.title)
    if not h:
        return
    fg = u.GetForegroundWindow()
    if fg == h:
        return
    tid_fg = u.GetWindowThreadProcessId(fg, None)
    tid_me = k.GetCurrentThreadId()
    try:
        u.AttachThreadInput(tid_me, tid_fg, True)
    except Exception:
        pass
    try:
        u.ShowWindow(h, 3)             # 3 = SW_MAXIMIZE，顺带锁住窗口尺寸
        u.BringWindowToTop(h)
        u.SetForegroundWindow(h)
    except Exception:
        pass
    try:
        u.AttachThreadInput(tid_me, tid_fg, False)
    except Exception:
        pass


def gray_and_filled(img, board):
    """逐格判断「有没有内容」：格内内缩 8px 求均值，≥60 视为有内容。

    ⚠️ 有内容 ≠ 已吸附（碎片可能只是躺在格子上），吸附判定见 changed()。
    """
    bx, by, bw, bh = board
    pw, ph = bw / N, bh / N
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    filled = []
    for r in range(N):
        for c in range(N):
            x0, y0 = int(bx + c * pw), int(by + r * ph)
            patch = g[y0 + 8:y0 + int(ph) - 8, x0 + 8:x0 + int(pw) - 8]
            if float(patch.mean()) >= 60:
                filled.append((r, c))
    return g, filled


# ------------------------------------------------------------------ 托盘格点
def tray_lattice(pw, ph, board, img_h):
    """算出托盘所有槽位的 x / y 坐标（复刻站点 traySlots 的布局）。

    槽位间距 = 碎片盒 × 1.16：凸扣伸出盒外约 27px，槽位必须留出空隙，
    否则相邻碎片会互相压住（源码：Tabs stick out of the piece box）。
    左边 4 列从画布原点 54 起；右边 4 列从「画布原点 + 棋盘右边界」起。
    行数**动态**计算：曾写死 8 行，而实际有 9 行，第 9 行的白碎片整块漏掉。
    """
    bx, by, bw, bh = board
    step_x, step_y = 1.16 * pw, 1.16 * ph
    cols = []
    for k in range(4):
        cols.append(54.0 + k * step_x + (step_x - pw) / 2)
        cols.append(54.0 + (bx - 54.0) + bw + k * step_x + (step_x - pw) / 2)
    rows, k = [], 0
    while 616.0 + k * step_y + (step_y - ph) / 2 + ph <= img_h:
        rows.append(616.0 + k * step_y + (step_y - ph) / 2)
        k += 1
    return cols, rows


def tray_pieces(img, board, ref, lat=None):
    """找托盘碎片：按格点表点名，判断每个槽位有没有东西、是不是纯白块。

    为什么不用连通域：碎片间距 18px、凸扣凸出 27px，相邻碎片会黏成一片
    （实测 30 块只数出 17 块）。
    """
    bx, by, bw, bh = board
    pw, ph = bw / N, bh / N
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cols, rows = lat if lat else tray_lattice(pw, ph, board, gray.shape[0])

    out = []
    for x in cols:
        for y in rows:
            x0, y0 = int(round(x)), int(round(y))
            if y0 + ph > gray.shape[0] or x0 + pw > gray.shape[1]:
                continue
            box = gray[y0:y0 + int(ph), x0:x0 + int(pw)]
            if box.size == 0 or float(box.mean()) < 40:
                continue                              # 空槽位（全黑）
            core = box[int(ph * 0.3):int(ph * 0.7), int(pw * 0.3):int(pw * 0.7)]
            if core.size == 0 or float(core.mean()) < 40:
                continue                              # 只有邻块凸扣伸进来一点点
            wf = float((box > 238).mean())            # 白占比
            df = float((box < 45).mean())             # 黑占比（缺口露出的画布底色）
            # 白碎片 = 白本体 + 缺口黑底，两者相加 ≈ 1（实测 0.95~0.98）；
            # 白底照片的中间有对象（非白非黑），白+黑只有 0.53~0.73。
            white = (wf > 0.68) and (wf + df >= 0.93)
            out.append({"x": x0, "y": y0, "white": white, "wf": wf})
    return out


def blob_mask(img, board, ref):
    """托盘区域的「有东西」掩码：亮 或 有颜色（深色照片也算）。"""
    bx, by, bw, bh = board
    rx, ry, rw, rh = ref
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b_, g_, r_ = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    chroma = np.maximum(np.maximum(b_, g_), r_) - np.minimum(np.minimum(b_, g_), r_)
    m = ((gray > 55) | (chroma > 45)).astype(np.uint8)
    m[by - 6:by + bh + 6, bx - 6:bx + bw + 6] = 0      # 扣棋盘
    m[:int(by * 0.40), :] = 0                          # 扣顶部 UI
    m[max(0, rx - 60):, :] = 0                         # 扣参考面板
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)), gray


def count_blobs(img, board, ref):
    """数托盘里像碎片的亮块个数。仅作日志：碎片会黏连，30 块常只数出 12~17。"""
    m, _ = blob_mask(img, board, ref)
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    cnt = 0
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area >= 4000 and 55 <= w <= 420 and 55 <= h <= 420:
            cnt += 1
    return cnt


# ------------------------------------------------------------------ 就绪闸门
def wait_ready(win, timeout=300):
    """等到「画面确实是游戏 + 参考图已渲染 + 棋盘全空 + 托盘有货 + 托盘已静止」。

    四道闸门缺一不可：
      1. 画面真伪：能检到正好 5 个白格（否则截到的是别的窗口）；
      2. 就绪状态：棋盘全空、托盘 ≥24 块；
      3. 稳定性：托盘区域两次采样几乎一致 —— 游戏是「先生成碎片、再撒到托盘」，
         撒的过程中算出的坐标会全部作废（曾因此 8 步 0 落子）。
    """
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < timeout:
        force_foreground(win)
        img = grab(win)
        board, ref = V3.resolve_geometry(win, img, verbose=False)
        if board and ref:
            g, filled = gray_and_filled(img, board)
            cells = ref_cells(img, ref)
            ws = [k for k, v in cells.items() if v["white"]]
            pieces = tray_pieces(img, board, ref)
            nblob = count_blobs(img, board, ref)
            ok = (len(ws) == 5) and (len(filled) == 0) and (len(pieces) >= 24)
            if ok:
                g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[600:1800, :2300].astype(np.int16)
                time.sleep(0.7)
                img2 = grab(win)
                g2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)[600:1800, :2300].astype(np.int16)
                drift = float(np.abs(g1 - g2).mean())
                if drift > 1.2:
                    print(f"  托盘还在动（drift={drift:.2f}），等它稳定…", flush=True)
                    time.sleep(0.5)
                    continue
                print(f"就绪：白格 {len(ws)}，空棋盘，托盘 {len(pieces)} 块(亮块 {nblob}) "
                      f"drift={drift:.2f}（等待 {time.time() - t0:.1f}s）", flush=True)
                return img2, board, ref, cells
            if time.time() - last > 6:
                print(f"  未就绪：白格 {len(ws)} / 已填 {len(filled)} / 托盘 {len(pieces)}"
                      f"(亮块 {nblob}) …（请确保是重开后的新手局画面）", flush=True)
                last = time.time()
        time.sleep(0.8)
    return None


# ------------------------------------------------------------------ 快速指派
def fast_plan(img, board, ref, scale=0.5):
    """给每个照片格找出「它的碎片在托盘哪里」——返回 {(r,c): {box, coarse, exact, ok}}。

    算法（5 步）：
      1. 模板 = 该参考格的**中心 50%**。四边各切 25% 是因为碎片盒边缘有缺口，
         缺口露出黑色画布底，整块比分会从 0.98 掉到 0.47；
      2. 粗匹配：模板与截图同缩到 scale 倍，在缩小图上滑一遍，取峰值 → 快 4 倍；
      3. 掩膜 + 腐蚀：把棋盘 / 参考图 / 顶部 UI 涂黑（不涂黑的话模板会在参考图
         上匹配到 1.00 分），再用「模板尺寸」的核腐蚀，保证模板整体落在允许区；
      4. 精修：回到原分辨率，在峰值 ±6px 窗口内用原尺寸模板再匹配一次；
      5. 换坐标：减去中心裁剪的偏移 (m*sx, m*sy)，得到**碎片盒左上角**。
    双阈值 coarse ≥ 0.70 且 exact ≥ 0.70 才算这格指派成功。
    """
    bx, by, bw, bh = board
    rx, ry, rw, rh = ref
    pw, ph = bw / N, bh / N
    tpw, tph = int(round(pw)), int(round(ph))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cells = ref_cells(img, ref)
    photo = {k: v for k, v in cells.items() if not v["white"]}

    allowed = np.full(gray.shape, 255, np.uint8)
    allowed[by - 2:by + bh + 2, bx - 2:bx + bw + 2] = 0
    allowed[ry - 30:ry + rh + 30, rx - 30:rx + rw + 30] = 0
    allowed[:365, :] = 0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    allowed_s = cv2.resize(allowed, (small.shape[1], small.shape[0]),
                           interpolation=cv2.INTER_NEAREST)

    plan = {}
    for (r, c), info in photo.items():
        cell = info["img"]
        H, W = cell.shape
        m = int(round(min(H, W) * 0.25))
        sub = cell[m:H - m, m:W - m]
        sx, sy = tpw / W, tph / H
        tw, th = int(round(sub.shape[1] * sx)), int(round(sub.shape[0] * sy))
        if tw < 8 or th < 8:
            continue
        full_t = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_AREA)
        small_t = cv2.resize(full_t, (max(4, int(tw * scale)), max(4, int(th * scale))),
                             interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(small, small_t, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        ok = cv2.erode(allowed_s, np.ones(small_t.shape, np.uint8))[:res.shape[0], :res.shape[1]]
        res[ok < 128] = -1.0
        iy, ix = np.unravel_index(int(np.argmax(res)), res.shape)
        coarse = float(res[iy, ix])
        cx, cy = int(ix / scale), int(iy / scale)
        pad = 6
        x0 = max(0, cx - pad); y0 = max(0, cy - pad)
        x1 = min(gray.shape[1], cx + tw + pad); y1 = min(gray.shape[0], cy + th + pad)
        roi = gray[y0:y1, x0:x1]
        if roi.shape[0] >= th and roi.shape[1] >= tw:
            res2 = cv2.matchTemplate(roi, full_t, cv2.TM_CCOEFF_NORMED)
            res2 = np.nan_to_num(res2, nan=-1.0)
            jy, jx = np.unravel_index(int(np.argmax(res2)), res2.shape)
            box = (x0 + jx - int(round(m * sx)), y0 + jy - int(round(m * sy)))
            exact = float(res2[jy, jx])
        else:
            box = (cx - int(round(m * sx)), cy - int(round(m * sy)))
            exact = coarse
        plan[(r, c)] = {"box": box, "coarse": coarse, "exact": exact,
                        "ok": coarse >= 0.70 and exact >= 0.70}
    return plan


# ------------------------------------------------------------------ 执行器
class Runner:
    """唯一的鼠标入口：拖一次、判一次。"""

    def __init__(self, win):
        self.win = win
        self.moves = 0          # 与游戏记步口径一致：一次完整拖拽 = 1 步（失败也记）

    def drag(self, fx, fy, tx, ty):
        pyautogui.moveTo(self.win.left + fx, self.win.top + fy)
        time.sleep(MOVE_TO_PAUSE)
        pyautogui.mouseDown()
        time.sleep(DOWN_PAUSE)          # 必须给浏览器记录拾取点的时间
        pyautogui.moveTo(self.win.left + tx, self.win.top + ty, duration=DRAG_DUR)
        time.sleep(UP_PAUSE)
        pyautogui.mouseUp()
        time.sleep(SETTLE)
        self.moves += 1

    def place(self, fx, fy, tx, ty):
        """拖过去，并用进度计数器差分判定是否真的吸附。"""
        before = grab_prog(self.win)
        self.drag(fx, fy, tx, ty)
        return changed(before, grab_prog(self.win))
