# -*- coding: utf-8 -*-
"""白块形状层：把「一条边的凸/凹/平」读出来，并反推「某个空格需要什么形状」。

纯白碎片彼此像素完全相同，唯一区别是四条边的凹凸，所以只能用形状区分。
本模块只做「测量」，不做「决策」——形状只用于排序候选，最终是否吸附由
进度计数器差分判定（见 solve_v6_safe.changed）。

形状编码，每条边 ∈ {+1 凸(tab), 0 平(flat), -1 凹(notch), None 未知}：
    边框恒为 0；内部边只能是 ±1（源码里没有 0，读到 0 内部边即测量错误）。
"""
import numpy as np
import cv2

from solve_v3 import N


def content_mask(gray, lo=55, chroma_min=45, img=None):
    """「有内容」= 比背景亮，或带颜色（色度大）。

    不能用局部方差：碎片的投影(shadowBlur 8)会制造梯度，被误判成内容。
    也不能只看亮度：凸扣里填的是邻格照片像素，可能是深色。
    色度阈值不能降到 27 —— 棋盘底色 #0f172a 的色度正好是 27。
    """
    bright = gray > lo
    if img is not None:
        b = img[:, :, 0].astype(np.int16)
        g2 = img[:, :, 1].astype(np.int16)
        r = img[:, :, 2].astype(np.int16)
        chroma = np.maximum(np.maximum(b, g2), r) - np.minimum(np.minimum(b, g2), r)
        return bright | (chroma > chroma_min)
    return bright


def _cls_extreme(probes, tab_sign):
    """凸扣只占边中部约 30%，所以必须用极值判定，不能用中位数
    （中位数会落在「平」的区间里，把清晰的凸/凹读成 0）。

    tab_sign=+1：内容越往 +方向伸 = 邻块凸进来（我们凹 -1）；
                 内容整体缩回 -方向 = 邻块凹（我们凸 +1）。
    """
    if not probes:
        return None
    hi, lo = float(max(probes)), float(min(probes))
    if tab_sign > 0:
        if hi > 10:
            return -1
        if lo < -10:
            return +1
    else:
        if lo < -10:
            return -1
        if hi > 10:
            return +1
    return 0


def side_shape(mask, x0, y0, x1, y1, side, thick=10, span=(0.16, 0.84)):
    """在一条边上量凸(+1)/凹(-1)/平(0)，**用整条边的中位数自校准**。

    凸扣只占边中部约 30%，两侧各 35% 落在真实盒线上，所以
    「中位数 = 盒线」，中段相对中位数的偏移量就是凸/凹，与盒子标定误差无关。
    （之前用格点盒绝对位置判定，6~10px 偏移就会把凸读成凹。）

    side: 0=上 1=右 2=下 3=左；阈值 12px ≈ 凸扣深度(约 27px)的一半。
    """
    H, W = mask.shape
    if side in (0, 2):
        prof = []
        for xx in range(int(x0 + (x1 - x0) * span[0]), int(x0 + (x1 - x0) * span[1])):
            if not (0 <= xx < W):
                continue
            lo, hi = max(0, int(y0 - thick)), min(H, int(y1 + thick))
            col = np.where(mask[lo:hi, xx])[0]
            if col.size:
                prof.append(col.min() + lo if side == 0 else col.max() + lo)
        if len(prof) < 10:
            return None
        prof = np.array(prof, float)
        med = np.median(prof)
        up, dn = med - prof.min(), prof.max() - med
        if side == 0:
            return +1 if up > 12 else (-1 if dn > 12 else 0)
        return +1 if dn > 12 else (-1 if up > 12 else 0)

    prof = []
    for yy in range(int(y0 + (y1 - y0) * span[0]), int(y0 + (y1 - y0) * span[1])):
        if not (0 <= yy < H):
            continue
        lo, hi = max(0, int(x0 - thick)), min(W, int(x1 + thick))
        row = np.where(mask[yy, lo:hi])[0]
        if row.size:
            prof.append(row.min() + lo if side == 3 else row.max() + lo)
    if len(prof) < 10:
        return None
    prof = np.array(prof, float)
    med = np.median(prof)
    lf, rt = med - prof.min(), prof.max() - med
    if side == 3:
        return +1 if lf > 12 else (-1 if rt > 12 else 0)
    return +1 if rt > 12 else (-1 if lf > 12 else 0)


def white_piece_signature(pmask):
    """白碎片的四边签名：先取自己的连通域外接框，再用边中位数自校准。"""
    ys, xs = np.where(pmask)
    if xs.size == 0:
        return None, None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    sig = [side_shape(pmask, x0, y0, x1, y1, s) for s in range(4)]
    return sig, (x0, y0, x1 - x0, y1 - y0)


def required_side(mask, board, pw, ph, r, c, side, reach=30, frac=0.34):
    """某个空格在这一侧需要什么：看邻块轮廓是凸进来还是缩回去。

    返回 +1(我们要凸) / -1(我们要凹) / 0 / None(未知)
    """
    bx, by, bw, bh = board
    x, y = bx + c * pw, by + r * ph
    H, W = mask.shape
    probes = []

    if side in (0, 2):                      # 上下边界，按列扫
        b = y if side == 0 else y + ph
        for xx in range(int(x + pw * (0.5 - frac / 2)), int(x + pw * (0.5 + frac / 2))):
            seg = mask[max(0, int(b - reach)):min(H, int(b + reach)), int(xx)]
            idx = np.where(seg)[0]
            if idx.size:
                yy = idx + max(0, int(b - reach))
                probes.append((yy.max() - b) if side == 0 else (yy.min() - b))
        # 上：内容越往 + 伸 = 邻块凸 -> 我们凹(-1)
        # 下：内容越往 - 伸 = 邻块凸 -> 我们凹(-1)
        return _cls_extreme(probes, +1 if side == 0 else -1)

    if side in (1, 3):                      # 左右边界，按行扫
        b = x if side == 3 else x + pw
        for yy in range(int(y + ph * (0.5 - frac / 2)), int(y + ph * (0.5 + frac / 2))):
            seg = mask[int(yy), max(0, int(b - reach)):min(W, int(b + reach))]
            idx = np.where(seg)[0]
            if idx.size:
                xx = idx + max(0, int(b - reach))
                probes.append((xx.max() - b) if side == 3 else (xx.min() - b))
        return _cls_extreme(probes, +1 if side == 3 else -1)

    return None


def required_shape(mask, board, pw, ph, r, c):
    """返回 [上,右,下,左]，边框为 0，邻块未知为 None。"""
    out = [None] * 4
    out[0] = 0 if r == 0 else required_side(mask, board, pw, ph, r, c, 0)
    out[1] = 0 if c == N - 1 else required_side(mask, board, pw, ph, r, c, 1)
    out[2] = 0 if r == N - 1 else required_side(mask, board, pw, ph, r, c, 2)
    out[3] = 0 if c == 0 else required_side(mask, board, pw, ph, r, c, 3)
    return out


def isolate_component(gray, box, pw, ph, pad=42, mask=None, img=None):
    """从盒中心取「这一块」的连通域。

    两个坑：
      1. 托盘槽位只隔 ~18px、凸扣深 ~27px，固定窗口里量会扫到邻块；
      2. 白碎片的凸扣里填的不是白色，而是合成图 margin 取来的**邻格照片像素**，
         所以不能只按「白」取，要按「非背景」取。
    """
    x, y = box
    xx0 = max(0, int(x - pad)); yy0 = max(0, int(y - pad))
    xx1 = min(gray.shape[1], int(x + pw + pad)); yy1 = min(gray.shape[0], int(y + ph + pad))
    src = content_mask(gray, img=img) if mask is None else (mask > 0)
    sub = src[yy0:yy1, xx0:xx1].astype(np.uint8)
    if sub.sum() < 500:
        return None
    n, lab = cv2.connectedComponents(sub, 8)
    cy = int(y + ph / 2) - yy0
    cx = int(x + pw / 2) - xx0
    cy = max(0, min(cy, sub.shape[0] - 1)); cx = max(0, min(cx, sub.shape[1] - 1))
    lbl = lab[cy, cx]
    if lbl == 0:
        ys, xs = np.where(sub > 0)
        d = (ys - cy) ** 2 + (xs - cx) ** 2
        i = int(np.argmin(d))
        lbl = lab[ys[i], xs[i]]
    full = np.zeros(gray.shape, np.uint8)
    full[yy0:yy1, xx0:xx1] = (lab == lbl).astype(np.uint8)
    return full.astype(bool)
