# -*- coding: utf-8 -*-
"""入口 / 调度层：决定「哪一块现在放、放到哪一格、放不上怎么办」。

整体流程：
    等就绪（四道闸门） -> 算指派（20 个照片格的碎片位置） -> 指派完整性闸门
    -> 按「外圈→内圈」逐格尝试 -> 收尾统计

为什么是「外圈→内圈」而不是「先照片后白块」：
    吸附要求「有锚点」（自身格在外圈，或四邻已有放置）。若某照片格的四个邻居
    全是白格，而白格要等照片阶段之后才放，这一格就**永远没有锚点**——几何死锁。
    所以按环序整体推进，遇到没锚点的格子跳过、下一趟再来。

两种格子两种放法：
    照片格 -> 开局算好的模板匹配结果（1 次到位），失败走现场相似度兜底；
    白  格 -> 读「这一格需要什么形状」，给白块按形状排序后试放（最多 2 块）。
    两者最终都由「进度计数器差分」裁决，形状只是排序依据。

用法：
    python solve_v7.py run
"""
import sys
import os
import time

import cv2
import numpy as np

import solve_v3 as V3
import solve_white as SW
import solve_v6_safe as S

BUDGET = S.MOVE_BUDGET          # 33 = ceil(25 × 1.3)
MAX_PASSES = 5                  # 环序 + 延迟队列，理论上 2 趟足够，5 是保险
FAIL_STREAK_LIMIT = 4           # 连续失败到此数就熔断，不再烧步数


def main():
    win = S.find_win()
    ready = S.wait_ready(win)
    if ready is None:
        sys.exit("等不到就绪的游戏画面")
    img, board, ref, cells = ready

    bx, by, bw, bh = board
    rx, ry, rw, rh = ref
    pw, ph = bw / S.N, bh / S.N
    white_cells = set(k for k, v in cells.items() if v["white"])
    print(f"白格 {sorted(white_cells)}", flush=True)

    # ---- 指派 + 完整性闸门 -------------------------------------------------
    t0 = time.perf_counter()
    plan = S.fast_plan(img, board, ref)
    okn = sum(1 for d in plan.values() if d["ok"])
    # 指派不完整说明页面还没完全稳定，再等等重算（最多 6 次）
    for _ in range(6):
        if okn >= 19:
            break
        print(f"  指派只有 {okn}/20，等页面稳定后重算…", flush=True)
        time.sleep(1.0)
        img = S.grab(win)
        plan = S.fast_plan(img, board, ref)
        okn = sum(1 for d in plan.values() if d["ok"])
    print(f"指派 {okn}/{len(plan)} 用时 {time.perf_counter() - t0:.2f}s", flush=True)
    if okn < 19:
        print("指派长期不完整，放弃这一局（不动鼠标）")
        return 7

    # ---- 状态容器 ----------------------------------------------------------
    r = S.Runner(win)
    placed = set()                 # 已确认吸附的格子
    tried_white = {}               # {(r,c): {(x,y), ...}} 每个白格试过哪些白块
    COLS, ROWS = S.tray_lattice(pw, ph, board, img.shape[0])

    def slot_of(x, y):
        """把任意盒位置吸附到最近的托盘槽位。"""
        return (min(COLS, key=lambda v: abs(v - x)),
                min(ROWS, key=lambda v: abs(v - y)))

    def grab_point(x0, y0):
        """抓取点：默认盒中心；若盒已偏离槽位（说明被挤过、可能与别的块重叠），
        改抓右下角——重叠通常发生在上/左侧，右下角能避开压在上面那块。"""
        sx, sy = slot_of(x0, y0)
        if max(abs(sx - x0), abs(sy - y0)) > 12:
            return x0 + pw * 0.85, y0 + ph * 0.85
        return x0 + pw / 2, y0 + ph / 2

    def centre(cell):
        return bx + (cell[1] + 0.5) * pw, by + (cell[0] + 0.5) * ph

    def anchored(cell):
        """复刻游戏的锚点规则：外圈无条件可放，否则四邻中需有一块已放置。"""
        rr, cc = cell
        if rr in (0, S.N - 1) or cc in (0, S.N - 1):
            return True
        return any((a, b) in placed for a, b in
                   ((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)))

    def do_place(box, cell):
        """把 (box) 这块拖到 cell。

        游戏按「位移量」移动碎片，所以只要
            释放点 = 抓取点 + (目标左上角 − 碎片盒左上角)
        碎片盒左上角就会精确落到格子左上角 —— 抓取点是否在中心无关紧要。
        失败时拖回**最近槽位**（不是漂移后的位置），避免碎片越漂越远。
        """
        x0, y0 = int(box[0]), int(box[1])
        gx, gy = grab_point(x0, y0)
        ccx, ccy = bx + cell[1] * pw, by + cell[0] * ph
        rx_, ry_ = gx + (ccx - x0), gy + (ccy - y0)
        ok = r.place(gx, gy, rx_, ry_)
        if not ok:
            sx, sy = slot_of(x0, y0)
            r.drag(rx_, ry_, sx + pw / 2, sy + ph / 2)
        return ok

    def place_photo(cell):
        """照片格：优先用开局算好的计划；计划缺失时现场按相似度试前 2 个。"""
        d = plan.get(cell)
        if d and d["ok"]:
            return do_place(d["box"], cell)

        im = S.grab(win)
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        xr = int(rx + cell[1] * rw / S.N); yr = int(ry + cell[0] * rh / S.N)
        refc = g[yr:yr + int(rh / S.N), xr:xr + int(rw / S.N)]
        H, W = refc.shape
        m2 = int(min(H, W) * 0.25)
        rs = cv2.resize(refc[m2:H - m2, m2:W - m2], (48, 36),
                        interpolation=cv2.INTER_AREA).astype(np.float32)
        rs -= rs.mean(); rn = np.sqrt((rs * rs).sum())
        scored = []
        for p in S.tray_pieces(im, board, ref):
            if p["white"]:
                continue
            b = g[int(p["y"]):int(p["y"] + ph), int(p["x"]):int(p["x"] + pw)]
            if b.size == 0:
                continue
            b2 = cv2.resize(cv2.resize(b, (W, H))[m2:H - m2, m2:W - m2], (48, 36),
                            interpolation=cv2.INTER_AREA).astype(np.float32)
            b2 -= b2.mean()
            d2 = np.sqrt((b2 * b2).sum()) * rn
            scored.append((float((b2 * rs).sum() / d2) if d2 > 0 else -1, p))
        scored.sort(key=lambda t: -t[0])
        for sc, p in [x for x in scored[:2] if x[0] >= 0.55]:
            if do_place((p["x"], p["y"]), cell):
                return True
        return False

    def place_white(cell):
        """白格：读「这一格需要什么形状」→ 给白块打分排序 → 试前 2 块。

        评分 +2 / −3 不对称：猜错的代价（2 步）大于猜对的收益（1 步），
        所以对不上要重罚，让"不确定"的候选排在保守位置。
        """
        im = S.grab(win)
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        mask = SW.content_mask(g, img=im)
        req = SW.required_shape(mask, board, pw, ph, cell[0], cell[1])
        cands = []
        for p in S.tray_pieces(im, board, ref):
            if not p["white"] or (p["x"], p["y"]) in tried_white.get(cell, set()):
                continue
            pm = SW.isolate_component(g, (p["x"], p["y"]), pw, ph, img=im)
            sig = SW.white_piece_signature(pm)[0] if pm is not None else None
            sc = -99
            if sig is not None:
                sc = 0
                for k in range(4):
                    if req[k] is None:
                        continue
                    sc += 2 if sig[k] == req[k] else -3
            cands.append((sc, p))
        cands.sort(key=lambda t: -t[0])
        for sc, p in cands[:2]:
            tried_white.setdefault(cell, set()).add((p["x"], p["y"]))
            ok = do_place((p["x"], p["y"]), cell)
            print(f"  白 {cell} <- ({p['x']},{p['y']}) 形状{sc} "
                  f"{'吸附' if ok else '未吸附'} (步 {r.moves})", flush=True)
            if ok:
                return True
        return False

    # ---- 主循环：环序 + 延迟队列 + 熔断 ------------------------------------
    order = V3.ring_order()
    fail_streak = 0
    abort = False
    for pass_i in range(MAX_PASSES):
        progressed = False
        for cell in order:
            if cell in placed or r.moves >= BUDGET:
                continue
            if not anchored(cell):
                continue                      # 没锚点，拖了必失败，等下一趟
            ok = place_white(cell) if cell in white_cells else place_photo(cell)
            if ok:
                placed.add(cell); progressed = True; fail_streak = 0
                print(f"  ✅ {cell}  已放 {len(placed)}/25  (步 {r.moves})", flush=True)
            else:
                fail_streak += 1
                if fail_streak >= FAIL_STREAK_LIMIT:
                    print(f"连续失败 {fail_streak} 次，停止（疑似时序/环境问题，不再烧步数）",
                          flush=True)
                    abort = True
                    break
        print(f"— 第 {pass_i + 1} 趟结束：已放 {len(placed)}/25，{r.moves} 步", flush=True)
        if abort or len(placed) >= 25 or not progressed:
            break

    # ---- 收尾 --------------------------------------------------------------
    im = S.grab(win)
    cv2.imwrite(os.path.join(os.path.dirname(os.path.abspath(__file__)), "final_board.png"), im)
    _, filled = S.gray_and_filled(im, board)
    empty = [(rr, cc) for rr in range(S.N) for cc in range(S.N) if (rr, cc) not in filled]
    print(f"\n共 {r.moves} 步，脚本 {time.perf_counter() - t0:.1f}s，"
          f"已放置 {len(placed)}/25，灰度自检空格 {len(empty)} {empty}", flush=True)
    # 成功判据以「进度计数器确认过的 placed」为准：
    # gray_and_filled 用格内均值 ≥60 判有内容，遇到**深色照片**（如黑底咖啡杯）
    # 会误判成空格，只能当提示，不能当判据。
    if len(placed) >= 25:
        if empty:
            print(f"  提示：灰度自检把 {len(empty)} 个深色格误判为空，以进度计数器为准", flush=True)
        return 0
    return 3


if __name__ == "__main__":
    sys.exit(main())
