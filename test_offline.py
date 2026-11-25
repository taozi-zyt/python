# -*- coding: utf-8 -*-
"""离线自检：不碰鼠标、不需要开游戏，用一张真实开局截图验证整条识别链路。

用法：
    python test_offline.py

检查项（全部应 PASS）：
    1. 棋盘与参考图能被检到，且尺寸合理；
    2. 白格恰好 5 个（混合模式的确定值）；
    3. 托盘碎片 ≥ 24 块，其中恰好 5 块是纯白块；
    4. 20 个照片格的模板指派全部合格；
    5. 环序为 16 + 8 + 1 = 25 格；
    6. 托盘格点表为 8 列 × 9 行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2

import solve_v3 as V3
import solve_v6_safe as S

HERE = os.path.dirname(os.path.abspath(__file__))
FRAME = os.path.join(HERE, "calib_start.png")


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")
    return ok


def main():
    if not os.path.exists(FRAME):
        print(f"缺少测试图：{FRAME}")
        return 2
    img = cv2.imread(FRAME)
    results = []

    board = V3.detect_board(img)
    ref = V3.detect_ref(img, board) if board else None
    results.append(check("棋盘定位", board is not None, f"board={board}"))
    results.append(check("参考图定位", ref is not None, f"ref={ref}"))
    if not (board and ref):
        return 1

    cells = V3.ref_cells(img, ref)
    whites = sorted(k for k, v in cells.items() if v["white"])
    results.append(check("白格数 == 5", len(whites) == 5, f"{whites}"))

    pieces = S.tray_pieces(img, board, ref)
    wp = [p for p in pieces if p["white"]]
    results.append(check("托盘碎片 >= 24", len(pieces) >= 24, f"{len(pieces)} 块"))
    results.append(check("纯白块 == 5", len(wp) == 5, f"{len(wp)} 块"))

    plan = S.fast_plan(img, board, ref)
    okn = sum(1 for d in plan.values() if d["ok"])
    results.append(check("模板指派 == 20/20", okn == 20 and len(plan) == 20, f"{okn}/{len(plan)}"))

    order = V3.ring_order()
    outer_ok = all(min(r, c, V3.N - 1 - r, V3.N - 1 - c) == 0 for r, c in order[:16])
    results.append(check("环序 == 25 格", len(order) == 25 and outer_ok,
                         f"前 16 格均为外圈"))

    pw, ph = board[2] / V3.N, board[3] / V3.N
    cols, rows = S.tray_lattice(pw, ph, board, img.shape[0])
    results.append(check("格点表 8 列 x 9 行", len(cols) == 8 and len(rows) == 9,
                         f"{len(cols)} 列 × {len(rows)} 行"))

    ok_all = all(results)
    print("\n结果：", "全部通过 ✅" if ok_all else "存在失败 ❌")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
