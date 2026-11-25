# 逐行代码导读（CODE GUIDE）

> ⚠️ **版本说明**：本文写于代码整理之前，章节里包含整理时**已删除**的函数
> （`build_plan`、`masked_ncc`、`cell_mean`、`drag`、`find_white_pieces`、`snap_to_lattice`、
> 三个遗留 `main()`）。这些内容作为历史与原理参考仍然有效；**当前代码实际有哪些函数，
> 以 `FUNCTIONS.md` 与源码为准**，删除清单见 `FILES.md` 第六节。

> 目的：把四个核心文件**逐个函数、逐段代码**讲透，做到「别人随便问一句，你能指到具体那一行并说出为什么」。
> 阅读约定：每个函数给出「签名 → 输入/输出 → 逐行含义 → 为什么这样写 → 常见提问」。代码片段是从当前版本原样摘录的。

文件规模与建议阅读顺序：

| 顺序 | 文件 | 行数 | 为什么这个顺序 |
|---|---|---|---|
| 1 | `solve_v7.py` | 205 | 入口，先看清整体骨架和调度 |
| 2 | `solve_v6_safe.py` | 约 470 | 所有判据与时序都在这里 |
| 3 | `solve_v3.py` | 约 400 | 感知与几何的底层 |
| 4 | `solve_white.py` | 约 470 | 最"数学"的一块，放最后 |

---

# 一、`solve_v7.py`（205 行）—— 调度层

它是唯一需要运行的文件。全部逻辑就是：**等就绪 → 算指派 → 按环序逐格尝试 → 收尾报告**。

## 1.1 文件头与常量（1–23 行）

```python
# -*- coding: utf-8 -*-
"""v7：交错顺序版（正确处理「照片格被白格包围」的死锁）。..."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np
import solve_v3 as V3
import solve_white as SW
import solve_v6_safe as S

BUDGET = 33
```

逐行含义：

- `# -*- coding: utf-8 -*-`：文件里有中文，声明编码。Python 3 默认 UTF-8，这行是防御性的（老编辑器 / 老解释器会读错）。
- `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`：
  **把自己所在目录插到模块搜索路径最前面**。作用是：无论从哪个工作目录启动，`import solve_v3` 都能找到同目录的兄弟文件。这是"四个文件必须放一起"的代码侧原因。
- `import solve_v3 as V3` / `import solve_white as SW` / `import solve_v6_safe as S`：三个内部模块，起了短别名。注意 `S.find_win`、`S.grab` 其实是从 `solve_v3` 转手过来的（见 §2.1）。
- `BUDGET = 33`：**步数上限**。来源是站点源码 `moveTarget = ceil(25 × 1.3) = 33`。

> **问：为什么预算写死 33，而不从页面读？**
> 答：页面上的 `步数: N / 33` 需要 OCR 才能读；而 33 是纯函数 `ceil(pieces×1.3)`，25 格必然是 33，没必要读。**读不出来的东西，就用能算出来的等价物代替**——这是全项目反复用的思路。

## 1.2 `main()` 入口与就绪等待（26–36 行）

```python
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
```

- `S.find_win()`：拿到 Edge 窗口对象（有 `.left/.top/.width/.height`）。
- `S.wait_ready(win)`：**四道闸门**（画面真伪 / 就绪状态 / 托盘稳定 / 超时），返回 `(img, board, ref, cells)` 或 `None`。
  这里就体现了设计取向：**宁可一步不动，也不在错误画面上动手**。
- `board = (bx, by, bw, bh)`：棋盘矩形（屏幕坐标）。
- `ref = (rx, ry, rw, rh)`：参考图（合成图）矩形。
- `pw, ph = bw / S.N, bh / S.N`：**单块碎片的逻辑盒尺寸**（约 146 × 109.2）。`S.N` 是 5。
- `cells`：`{(r,c): {"img","mean","std","white"}}`，参考图 25 格的分类结果。
- `white_cells`：这局哪 5 格是纯白格。**每局位置都不同**（源码里是随机抽 5 个索引）。

> **问：为什么用 `set` 而不是 `list`？**
> 答：后面有 `cell in white_cells` 的成员判断，`set` 是 O(1)。这是小优化，但循环里每格都判一次。

## 1.3 指派 + 完整性闸门（38–53 行）

```python
    t0 = time.perf_counter()
    plan = S.fast_plan(img, board, ref)
    okn = sum(1 for d in plan.values() if d["ok"])
    for extra in range(6):
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
```

- `t0 = time.perf_counter()`：用**单调时钟**（不受系统时间调整影响）记开始时间，用于最后报耗时。
- `S.fast_plan(...)`：返回 `{(r,c): {"box","coarse","exact","ok"}}`，只含**照片格**（白格不在里面）。
- `okn`：合格的照片格数。25 格里 5 格是白格 → 照片格共 20 格，所以满分是 20。
- `for extra in range(6)` + `if okn >= 19: break`：**最多重算 6 次**，等页面彻底稳定。
  阈值选 19 而不是 20：偶尔一块因为被遮挡而分数不够，留一格余量可以继续（缺的那格由 `place_photo` 的兜底去试）。
- `time.sleep(1.0)` + 重新截图 + 重新指派：每次都用新画面。
- `return 7`：退出码 7 = "指派不完整，主动放弃"。**此时一步鼠标都没动**，不浪费这一局。

> **问：为什么退出码要区分？**
> 答：方便外部包装脚本/bat 判断失败原因（7 = 画面问题，3 = 没拼完，0 = 成功）。

## 1.4 状态容器（55–57 行）

```python
    r = S.Runner(win)
    placed = set()
    tried_white = {}          # cell -> 已试过的白块坐标
```

- `r = S.Runner(win)`：**执行器**，封装"拖拽 + 判据"，内部维护 `r.moves`（本局已用步数）。
- `placed`：已经确认吸附的格子集合。注意它和页面真实状态可能瞬时不同步，但因为我们只在 `place()` 返回 True 时才加入，语义是可靠的。
- `tried_white`：`{(r,c): {(x,y), ...}}`，记录**每个白格试过哪些白块**。
  这是踩过的坑：早期版本每次都取候选列表第一个，导致同一块在同一格试 5 次，白烧 20 步。

## 1.5 托盘格点表（59–68 行）

```python
    step_x, step_y = 1.16 * pw, 1.16 * ph
    COLS = []
    for k in range(4):
        COLS.append(54.0 + k * step_x + (step_x - pw) / 2)
        COLS.append(54.0 + (bx - 54.0) + bw + k * step_x + (step_x - pw) / 2)
    ROWS, k = [], 0
    while 616.0 + k * step_y + (step_y - ph) / 2 + ph <= img.shape[0]:
        ROWS.append(616.0 + k * step_y + (step_y - ph) / 2)
        k += 1
```

这 10 行是**托盘槽位坐标**，公式直接来自站点源码 `traySlots()`：

- `step_x = 1.16 × pw`：槽位横向间距**比碎片宽 16%**（因为凸扣要伸出盒外，源码注释写了 "Tabs stick out of the piece box, so slots are spaced slightly wider"）。
- `54.0`：画布（canvas 元素）在屏幕上的左边界。这是从实测反推的常量。
- 左带 4 列：`54 + k×step_x + 半个余量`，`(step_x - pw)/2` 是把"槽位宽"对齐到"碎片盒宽"的居中偏移。
- 右带 4 列：起点是 `54 + (bx - 54.0) + bw` = 画布原点 + 棋盘右边界，再按同样步长排 4 列。
- `616.0`：画布顶边。`while ... + ph <= img.shape[0]`：**行数动态求解**，直到放不下为止。
  这行是修 bug 的关键——曾经写死 `range(8)`，而实际有 **9 行**，第 9 行的白碎片整块漏掉。

> **问：为什么列是 4+4=8 列，行却要动态算？**
> 答：列数由 `floor(boardX / step_x)` 决定，实测恒为 4；行数由画布**高度**决定，而画布高度取决于分辨率，所以必须动态。

## 1.6 `slot_of(x, y)`（70–72 行）

```python
    def slot_of(x, y):
        return (min(COLS, key=lambda v: abs(v - x)), min(ROWS, key=lambda v: abs(v - y)))
```

把任意坐标**吸附到最近的槽位**（横纵独立取最近）。用途见 §1.9 `do_place` 的失败回槽。
复杂度 O(8 + R)，R≈9，可忽略。

## 1.7 `grab_point(x0, y0)`（74–81 行）

```python
    def grab_point(x0, y0):
        sx, sy = slot_of(x0, y0)
        off = max(abs(sx - x0), abs(sy - y0))
        if off > 12:
            return x0 + pw * 0.85, y0 + ph * 0.85
        return x0 + pw / 2, y0 + ph / 2
```

**决定按哪儿下鼠标。**

- `off`：这个盒偏离最近槽位多少。正常开局 ≤4px（游戏只加 ±2.5% 的抖动）。
- `off > 12` 意味着**这块不在槽位上**——通常是之前失败的拖拽把它挤到了两格之间，而且很可能与另一块**重叠**。
- 重叠时按中心抓会怎样？`getPieceAt` 是从数组末尾往前扫、返回**最上面那块**，于是抓到的是**压在上面的另一块** → 拖错对象 → 永远吸不上。
- 所以偏离时改抓 `(0.85, 0.85)` 即**右下角**：实测重叠发生在左上方向，右下角在目标块内、且不在另一块的盒内。

> **问：0.85 这个系数有依据吗？**
> 答：没有精确推导，是"足够靠近角、又不至于落到凸扣外"的经验值；实测一次成功。理论更优解是"在目标盒内找一个不被任何其它盒覆盖的点"，但那需要精确知道所有块的位置（重叠时很难检测）。

## 1.8 `centre(cell)`（83–84 行）

```python
    def centre(cell):
        return bx + (cell[1] + 0.5) * pw, by + (cell[0] + 0.5) * ph
```

格子中心坐标。注意 `cell = (row, col)`，所以**行用 ph、列用 pw**（顺序容易写反，这是常见 bug 点）。

## 1.9 `anchored(cell)`（86–91 行）

```python
    def anchored(cell):
        rr, cc = cell
        if rr in (0, S.N - 1) or cc in (0, S.N - 1):
            return True
        return any((a, b) in placed for a, b in
                   [(rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)])
```

**复刻游戏的锚点规则**（源码 `hasAnchor`）：

1. 自身格在外圈（行是 0 或 4，列是 0 或 4）→ 无条件可放；
2. 否则四邻中有一块已放置 → 可放。

这是整个调度层的**约束来源**：不可放的格子必须等，否则这次拖拽一定白费。

> **问：为什么不放就跳过，而不是硬试？**
> 答：锚点不满足时 `checkSnap` 直接 return false，试了必然失败、记 1 步。**知道会失败就不要动鼠标**。

## 1.10 `do_place(box, cell)`（93–104 行）

```python
    def do_place(box, cell):
        x0, y0 = int(box[0]), int(box[1])
        gx, gy = grab_point(x0, y0)
        ccx, ccy = bx + cell[1] * pw, by + cell[0] * ph
        rx_, ry_ = gx + (ccx - x0), gy + (ccy - y0)
        ok = r.place(gx, gy, rx_, ry_)
        if not ok:
            sx, sy = slot_of(x0, y0)
            r.drag(rx_, ry_, sx + pw / 2, sy + ph / 2)
        return ok
```

这是**落子的核心 6 行**，三个要点：

1. `gx, gy = grab_point(...)`：抓取点可能不在中心。
2. **落点换算**：游戏移动碎片量 = `释放点 − 抓取点`。要让碎片左上角从 `(x0,y0)` 落到 `(ccx,ccy)`，需要位移 `(ccx−x0, ccy−y0)`，所以
   `释放点 = 抓取点 + (目标左上角 − 当前左上角)`。
   **这一步让"任意抓取点"都能精确落子**，是 1.7 能存在的前提。
3. 失败时拖回**最近槽位**（`slot_of`），不是拖回 `(x0,y0)`——因为 `(x0,y0)` 可能就是漂移后的错误位置，拖回去会继续漂。

> **问：为什么不直接按中心抓、省掉这套换算？**
> 答：重叠时中心抓不到目标块（见 1.7）。换算只是两行算术，代价远小于抓错。

## 1.11 `place_photo(cell)`（106–138 行）

```python
    def place_photo(cell):
        d = plan.get(cell)
        if d and d["ok"]:
            if do_place(d["box"], cell):
                return True
            return False
        # 计划里没有 -> 用托盘候选按相似度试（最多 2 个）
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
```

主路径（前 5 行）：计划里有且合格 → 直接放，**一次到位**。

兜底路径（计划里没有这一格，比如它被遮挡过）：现场重新算一个"相似度排序"。

逐行解释兜底：

- `xr, yr`：按参考图 5×5 推出的该格在**屏幕上的**参考图位置。注意参考图已经在屏幕上，所以直接用屏幕坐标切片即可。
- `m2 = 25% × min(H,W)`：取中心 50%（四边各去掉 25%），**同样是为了避开缺口**。
- `rs`：把参考格缩到 48×36 的 float32，再**去均值**（零均值化）。
- `rn = sqrt(Σrs²)`：参考向量的模长，后面做余弦相似度用。
- 循环里对每块托盘碎片：按盒切片 → 先放大到 `(W,H)`（与参考格同尺寸）→ 再取中心 50% → 缩到 48×36 → 去均值。
- `d2 = sqrt(Σb2²) × rn`：分母是两向量模长之积 → 于是 `(b2·rs)/d2` 就是**归一化互相关**（等价余弦相似度）。
- `scored.sort(key=lambda t: -t[0])`：按分数降序。
- `[x for x in scored[:2] if x[0] >= 0.55]`：只取前 2 个、且相似度 ≥0.55。**限次**是防"兜底烧步数"（曾有一版每格试 4 个，烧到 94 步）。

> **问：为什么兜底限制 2 个候选？**
> 答：兜底本身是异常路径。多于 2 个说明这一格很可能是白格或碎片被遮挡，继续试只是烧步数，不如留给下一趟（`placed` 会更新，可能解锁锚点）。

## 1.12 `place_white(cell)`（140–167 行）

```python
    def place_white(cell):
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
```

白块没有"内容指纹"可用（都是白的），只能靠形状：

1. `required_shape(...)`：从棋盘这个**空格的四条边界**读它"需要什么形状"（`[上,右,下,左]`，未知为 `None`）。
2. 对每块可用白块：`isolate_component` 隔离出它自己 → `white_piece_signature` 量出它的形状。
3. **评分规则**：每边对上 +2、对不上 −3、未知跳过。
   为什么不对称？**因为猜错的代价（2 步）大于猜对省下的（1 步）**，所以宁可保守：对不上要重罚，让"未知"的候选排前面也一样安全。
4. `tried_white` 记录已试过的块，**逐块换**（不是重复试同一块）。
5. 只试前 2 个候选：形状只有约 70% 可靠，多试没有信息增益。

> **问：形状判断错了怎么办？**
> 答：`do_place` 的返回值来自**进度差分**（模块 C），那是 100% 可靠的终裁。形状只影响"先试谁"，不影响"最终对不对"。这就是"排序用弱信号、裁决用强信号"的分工。

## 1.13 主循环：五趟 + 熔断（169–193 行）

```python
    order = V3.ring_order()
    fail_streak = 0
    abort = False
    for pass_i in range(5):
        progressed = False
        for cell in order:
            if cell in placed or r.moves >= BUDGET:
                continue
            if not anchored(cell):
                continue
            ok = place_white(cell) if cell in white_cells else place_photo(cell)
            if ok:
                placed.add(cell); progressed = True; fail_streak = 0
                print(f"  ✅ {cell}  已放 {len(placed)}/25  (步 {r.moves})", flush=True)
            else:
                fail_streak += 1
                if fail_streak >= 4:
                    print(f"连续失败 {fail_streak} 次，停止（疑似时序/环境问题，不再烧步数）", flush=True)
                    abort = True
                    break
        print(f"— 第 {pass_i + 1} 趟结束：已放 {len(placed)}/25，{r.moves} 步", flush=True)
        if abort or len(placed) >= 25 or not progressed:
            break
```

三个终止条件：

- `abort`（连续失败 4 次）：**异常熔断**。曾有一局因为时序参数错误，一路失败到 34 步才发现，这道闸把它压到 8 步。
- `len(placed) >= 25`：完成。
- `not progressed`：**一整趟毫无进展** → 再趟也没意义（锚点关系不会再变）。

`for pass_i in range(5)`：理论上最多 2 趟就够（环序 + 延迟），5 是保险上限。

> **问：为什么"一趟没进展"就可以停？**
> 答：锚点约束是单调的——只依赖 `placed`。如果一趟里没有任何格子被放上，`placed` 没变，则下一趟的内层循环条件完全相同，结果必然相同。这是**不动点判据**。

## 1.14 收尾（195–201 行）

```python
    im = S.grab(win)
    cv2.imwrite(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v7_final.png"), im)
    _, filled = S.gray_and_filled(im, board)
    empty = [(rr, cc) for rr in range(S.N) for cc in range(S.N) if (rr, cc) not in filled]
    print(f"\n共 {r.moves} 步，脚本 {time.perf_counter() - t0:.1f}s，"
          f"剩余空格 {len(empty)} {empty}", flush=True)
    return 0 if not empty else 3
```

- 存一张终局截图（便于事后核对，不参与逻辑）。
- `gray_and_filled` 按格均值 ≥60 判"有内容"，得到 `filled` 列表。
- `empty`：25 格里不在 `filled` 中的 → 剩余空格。
- 退出码：0 = 全拼完；3 = 还有空格。
  **注意**：这里的判据是"格子里有没有东西"，不是"是否吸附"——因为终局时若全部吸附，两者等价；若有未吸附的碎片落在格子上，它会误报成功。这是已知的精度边界（真正可靠的还是进度计数器，但终局不需要再读了）。

---

# 二、`solve_v6_safe.py`（422 行）—— 判据与执行层

这个文件是**全系统最关键**的一块：它定义"什么是吸附成功"，也是唯一碰鼠标的地方。
注意：文件名叫 v6，里面的 `main()` 是**旧的 v5 流程**（先照片后白块），v7 不用它；
**v7 复用的是本文件的工具函数与 `Runner` 类**。

## 2.1 文件头（16–34 行）

```python
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cv2
import mss
import ctypes
import pyautogui

import solve_v3 as V3
import solve_white as SW
from solve_v3 import find_win, grab, ref_cells, N

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

PROG = (2540, 505, 250, 80)
BOARD = (791, 935, 730, 546)
REF = (2309, 964, 721, 541)
MOVE_BUDGET = 33
```

- `pyautogui.PAUSE = 0.0`：**关掉 pyautogui 自带的每次调用后延迟**。它默认 0.1 秒/次，
  一次拖拽有 4 次调用，会白白多花 0.4 秒。我们自己用显式 `sleep` 控制节奏，所以关掉。
- `pyautogui.FAILSAFE = False`：**关掉"鼠标移到屏幕角落就抛异常"的保护**。
  我们的坐标是自己算的，不会有失控；而实测中出现过"用户把光标留在角落 → 一启动就抛 FailSafeException"。
- `PROG`：**进度计数器的读取区域**（窗口内相对坐标，250×80）。
  这是 3098×1850 窗口下量出来的：`x 2540..2790, y 505..585`。
  ⚠️ **窗口尺寸/DPI 一变，这个矩形就废了**——这是"必须保持窗口最大化"的代码级原因。
- `BOARD` / `REF`：棋盘与参考图的**兜底几何**（正常走检测 + `layout.json` 缓存，这两个是最后防线）。
- `MOVE_BUDGET = 33`：与 v7 的 `BUDGET` 同义（本文件 main 用）。

## 2.2 时序常量（36–41 行）

```python
MOVE_TO_PAUSE = 0.05
DOWN_PAUSE = 0.05        # 已验证：设 0 会让浏览器来不及记录拾取点，绝不能动
DRAG_DUR = 0.28          # 回退：0.22 实测导致大面积未吸附
UP_PAUSE = 0.06
SETTLE = 0.30            # 回退：0.20 太短，进度计数器还没刷新就判定，误判为未吸附
```

五个数字，每个都有物理含义：

| 常量 | 值 | 物理含义 | 如果设太小 |
|---|---|---|---|
| `MOVE_TO_PAUSE` | 0.05 | 光标移到起点后等一帧 | 起点事件与按下同批到达 |
| `DOWN_PAUSE` | 0.05 | **等浏览器处理 mousedown**（记录拾取点 + 拖动偏移） | **碎片位移恒为 0，一次都吸不上** |
| `DRAG_DUR` | 0.28 | 按下到释放之间的移动时长 | 移动事件被合并（实测 0.22 就出问题） |
| `UP_PAUSE` | 0.06 | 移动到终点后、抬起前 | 终点位置可能没被记录 |
| `SETTLE` | 0.30 | 抬起后等游戏重绘 + 更新进度文本 | **判据读到旧画面，误判未吸附** |

> **问：为什么不把这些都压小来提速？**
> 答：试过（0.22 / 0.20），结果一局 34 步只落 2 块。原因：`SETTLE` 太短时进度文本还没重绘，
> 判据读到的和拖拽前一样 → 误判失败 → 把已吸附的块又去拖 → 连锁崩坏。
> **判据的正确性优先于速度**，这是本项目的核心取向。

## 2.3 `grab_prog(win)`（45–49 行）

```python
def grab_prog(win):
    with mss.MSS() as sct:
        r = {"left": win.left + PROG[0], "top": win.top + PROG[1],
             "width": PROG[2], "height": PROG[3]}
        return np.array(sct.grab(r))[:, :, :3].copy()
```

- `win.left + PROG[0]`：把**窗口内相对坐标**换成**屏幕绝对坐标**。
- `mss.MSS()` 放在 `with` 里：**每次新建一个截图上下文**（mss 对象不能跨线程用，且窗口可能移动）。
- `[:, :, :3]`：mss 返回 BGRA 四通道，去掉 alpha。
- `.copy()`：`np.array(...)` 有时返回视图，`.copy()` 保证是独立内存，避免后续被覆盖。
- 耗时实测 **6.0 ms**（对比整窗截图 60.6 ms）——这是"只截需要的区域"的收益。

## 2.4 `changed(a, b)`（52–55 行）

```python
def changed(a, b):
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.int16)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.int16)
    return int((np.abs(ga - gb) > 30).sum()) > 50
```

**全系统最重要的一行判据。**

- 转灰度：文字颜色变化在灰度上同样明显，且减少 3 倍计算量。
- `.astype(np.int16)`：**必须**。`uint8` 相减会下溢（例如 5 − 200 变成 61），
  先转有符号再减才正确。
- `> 30`：单像素差异阈值，过滤抗锯齿/子像素渲染带来的噪声。
- `.sum() > 50`：**至少 50 个像素明显变化**才算"文本变了"。
  为什么是 50：数字从 `9` 变 `10` 只改一个字符，约 100~300 个像素；
  而纯噪声一般 <20。50 是一个安全的分离点。
- 返回 bool：**只关心"变没变"，不关心变成几**——这是把一个 OCR 问题降维成二元判据的关键。

> **问：如果进度从 19 变 20，只变了一位数字，会不会测不到？**
> 答：会变约 100+ 个像素（数字 9→0 加一位 2），远超 50。实测 19 次吸附全部被正确识别。

## 2.5 `force_foreground(win)`（59–83 行）

```python
def force_foreground(win):
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
        u.ShowWindow(h, 3)
        u.BringWindowToTop(h)
        u.SetForegroundWindow(h)
    except Exception:
        pass
    try:
        u.AttachThreadInput(tid_me, tid_fg, False)
    except Exception:
        pass
```

Windows 的**前台锁**（foreground lock）会阻止后台进程抢焦点。标准绕法是"线程输入挂接"：

1. `AttachThreadInput(me, fg_thread, True)`：把自己的输入队列**挂到当前前台线程上**，
   这样"我这边的焦点请求"被视为"前台进程的请求"，`SetForegroundWindow` 才会生效；
2. `ShowWindow(h, 3)`：`3 = SW_MAXIMIZE`，顺带把窗口最大化（保证几何一致）；
3. `BringWindowToTop` + `SetForegroundWindow`：置顶并激活；
4. `AttachThreadInput(..., False)`：**必须解除挂接**，否则输入队列会一直绑在一起。
5. 每一步都包 `try/except`：这些 API 在失败时的返回值/异常不稳定，**抢不到前台不应该让程序崩**——
   上层 `wait_ready` 会继续轮询。

## 2.6 `gray_and_filled(img, board)`（86–96 行）

```python
def gray_and_filled(img, board):
    bx, by, bw, bh = board
    pw, ph = bw / N, bh / N
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    filled = []
    for r in range(N):
        for c in range(N):
            x0, y0 = int(bx + c * pw), int(by + r * ph)
            if float(g[y0 + 8:y0 + int(ph) - 8, x0 + 8:x0 + int(pw) - 8].mean()) >= 60:
                filled.append((r, c))
    return g, filled
```

- 逐格取**内缩 8px** 的矩形算均值：内缩是为了避开格线/描边/凸扣的边界效应。
- 阈值 `>= 60`：空格是棋盘底色（`#0f172a`，灰度 ≈ 23），有碎片时远高于 60。
- 返回 `(灰度图, 已填格列表)`：灰度图给调用方复用，省一次转换。

> **问：为什么判"有内容"用均值≥60，而判吸附要用进度差分？**
> 答：因为**有内容 ≠ 吸附成功**——碎片可能只是"躺"在格子上没被锁定。
> 均值判据只用于**粗筛**（空格/非空格）、以及终局的完整性检查（此时两者等价）。

## 2.7 `wait_ready(win, timeout=300)`（99–134 行）—— 四道闸门

```python
def wait_ready(win, timeout=300):
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
```

逐段：

- `t0 = time.time(); last = 0.0`：`last` 用于**限流打印**，否则每秒刷屏。
- 每轮都 `force_foreground`：因为用户可能切走了窗口。
- `V3.resolve_geometry`：检测棋盘 + 参考图（失败会用 `layout.json` 缓存）。
- 四道闸门的**判定式**：`len(ws)==5`（正好 5 个白格）、`len(filled)==0`（棋盘全空）、`len(pieces)>=24`（托盘有货）。
  为什么是"正好 5"：混合模式白格数 = `round(25 × 1/5) = 5`，是**确定值**；多一个少一个都说明分类或渲染有问题。
- **稳定性闸门**：取 `[600:1800, :2300]`（托盘主区域）两次采样的平均绝对差。
  - `> 1.2`：视为"还在撒碎片"，`continue` 重新来；
  - 为什么要 `astype(np.int16)`：同上，避免 uint8 下溢。
  - 为什么区域只到 `x<2300`：排除参考图面板（那里可能出现加载动画）。
- 返回的是 `img2`（**第二次**截图）：保证返回的图像与"稳定"这一判断对应。
- 超时返回 `None`，由调用方 `sys.exit`。

> **问：这一步对最终成绩有影响吗？**
> 答：没有——因为**游戏计时在"开始这一部分"时才启动**。推荐做法是"先跑脚本、再点开始"，脚本已在轮询，就绪后立刻动手，等待时间不计入。

## 2.8 `fast_plan(img, board, ref, scale=0.5)`（138–190 行）—— 提速版指派

```python
    bx, by, bw, bh = board
    rx, ry, rw, rh = ref
    pw, ph = bw / N, bh / N
    tpw, tph = int(round(pw)), int(round(ph))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cells = ref_cells(img, ref)
    photo = {k: v for k, v in cells.items() if not v["white"]}
```

准备：灰度图、参考格分类、只保留照片格。

```python
    allowed = np.full(gray.shape, 255, np.uint8)
    allowed[by - 2:by + bh + 2, bx - 2:bx + bw + 2] = 0
    allowed[ry - 30:ry + rh + 30, rx - 30:rx + rw + 30] = 0
    allowed[:365, :] = 0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    allowed_s = cv2.resize(allowed, (small.shape[1], small.shape[0]),
                           interpolation=cv2.INTER_NEAREST)
```

- `allowed`：255 = 允许匹配，0 = 禁止。三块被挖掉：棋盘、参考面板（外扩 30px）、顶部 365px 的 UI。
- `small`：**0.5 倍灰度图**，粗匹配在它上面做，面积只有 1/4。
- `allowed_s`：掩膜同步缩小。**必须用 `INTER_NEAREST`**——插值会把 0/255 混成中间值，破坏二值语义。

```python
    for (r, c), info in photo.items():
        cell = info["img"]
        H, W = cell.shape
        m = int(round(min(H, W) * 0.25))
        sub = cell[m:H - m, m:W - m]
        sx, sy = tpw / W, tph / H
        tw, th = int(round(sub.shape[1] * sx)), int(round(sub.shape[0] * sy))
```

- `m = 25% × min(H,W)`：四边各去掉 25%，即**取中心 50%**。
  依据：缺口深约 `0.22 × min(pw,ph)`，加上边距与抗锯齿，25% 是安全值。
- `sx, sy = tpw/W, tph/H`：**参考格像素 → 碎片盒像素**的缩放比。
  因为参考图显示尺寸（721/5 ≈ 144）与碎片盒（146）并不完全相等，必须换算，否则模板尺寸就错。

```python
        full_t = cv2.resize(sub, (tw, th), interpolation=cv2.INTER_AREA)
        small_t = cv2.resize(full_t, (max(4, int(tw * scale)), max(4, int(th * scale))),
                             interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(small, small_t, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
```

- 同时维护两个模板：`full_t`（原分辨率，用于精修）与 `small_t`（0.5 倍，用于粗搜）。
- `TM_CCOEFF_NORMED`：**归一化互相关**
  `R = Σ(T'·I') / sqrt(ΣT'²·ΣI'²)`，其中 `T' = T − mean(T)`。
  它对**线性光照变化免疫**（亮度/对比度变化不改变相关系数），且输出落在 [−1, 1]。
- `np.nan_to_num`：当模板或窗口是**常数**（方差为 0）时 NCC 是 0/0 = NaN，
  统一置 −1（等于"不合格"），避免 NaN 污染 `argmax`。

```python
        ok = cv2.erode(allowed_s, np.ones(small_t.shape, np.uint8))[:res.shape[0], :res.shape[1]]
        res[ok < 128] = -1.0
```

- **腐蚀技巧**：用"全 1 的模板尺寸核"腐蚀允许掩膜，
  结果中值为 255 的位置 ⟺ **模板整体都落在允许区**。
  这样才能保证匹配窗口不跨到棋盘或参考图里。
- 切片 `[:res.shape[0], :res.shape[1]]`：`matchTemplate` 输出比原图小，形状要对齐。

```python
        iy, ix = np.unravel_index(int(np.argmax(res)), res.shape)
        coarse = float(res[iy, ix])
        cx, cy = int(ix / scale), int(iy / scale)
```

- `argmax` + `unravel_index`：把扁平下标还原成 (row, col)。
- `cx, cy`：粗匹配坐标**映射回原分辨率**。

```python
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
```

- **局部精修**：只取粗匹配点周围 `±6px` 的小 ROI，用**原分辨率模板**再匹配一次。
  因为 ROI 很小（约 158×122），这一步几乎不耗时，却把精度拉回全分辨率水平。
- `box` 的换算：`jx` 是**中心 50% 模板**的左上角；要还原到**完整碎片盒**的左上角，
  需减去模板相对盒的偏移 `m * sx`（`m` 是参考图上的边距，`sx` 是缩放比）。
- 若 ROI 比模板还小（贴边等异常），退回粗匹配结果，`exact = coarse`。

```python
        plan[(r, c)] = {"box": box, "coarse": coarse, "exact": exact,
                        "ok": coarse >= 0.70 and exact >= 0.70}
```

- **双阈值**：粗匹配和精匹配都要 ≥0.70。粗匹配负责"别找错地方"，精匹配负责"确实对得上"。
- 实测两次全对时是 20/20，分数 0.90~0.99。

> **问：0.5 倍粗匹配会不会导致漏检（找到错峰）？**
> 答：理论上可能，但**精修是在原分辨率做的**；若粗匹配峰不对，精修分数（`exact`）就会低，
> 该格被判不合格，而不是被放进错误的盒。`compare_plans.py` 实测 20/20 格 **0px 偏差、分数一致**。

## 2.9 `blob_mask` / `count_blobs`（193–216 行）

```python
def blob_mask(img, board, ref):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b_, g_, r_ = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    chroma = np.maximum(np.maximum(b_, g_), r_) - np.minimum(np.minimum(b_, g_), r_)
    m = ((gray > 55) | (chroma > 45)).astype(np.uint8)
    m[by - 6:by + bh + 6, bx - 6:bx + bw + 6] = 0      # 扣棋盘
    m[:int(by * 0.40), :] = 0                          # 扣顶部 UI
    m[max(0, rx - 60):, :] = 0                         # 扣参考面板
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)), gray
```

- `chroma = max(B,G,R) − min(B,G,R)`：**色度**（饱和度的一种廉价近似）。
- "内容" = 够亮 **或** 够彩 —— 这样深色的照片碎片也不会被漏掉。
  ⚠️ 阈值不能太低：棋盘底色 `#0f172a` 的 chroma 恰好是 **27**，
  早期用 `chroma > 26` 时**整个棋盘都被当成内容**，导致所有测量崩坏。
- `MORPH_CLOSE`（先膨胀后腐蚀）：把同一块碎片内部的小孔/缝隙补上。
- 只用于**就绪检查的亮块计数**与诊断，不参与主流程定位。

`count_blobs`：连通域 + 尺寸过滤（面积 ≥4000、边长 55~420），统计"像碎片"的块数。
👉 这个数字**不可靠**（碎片会黏连，30 块常只数出 12~17），只作日志参考，**不做闸门**。

## 2.10 `tray_pieces(img, board, ref, lat=None)`（219–257 行）—— 格点表点名

```python
    step_x, step_y = 1.16 * pw, 1.16 * ph
    cols = []
    for k in range(4):
        cols.append(54.0 + k * step_x + (step_x - pw) / 2)
        cols.append(54.0 + (bx - 54.0) + bw + k * step_x + (step_x - pw) / 2)
    rows, k = [], 0
    while 616.0 + k * step_y + (step_y - ph) / 2 + ph <= gray.shape[0]:
        rows.append(616.0 + k * step_y + (step_y - ph) / 2)
        k += 1
```

与 v7 里的格点完全一致（那 10 行是从这里抄过去的）。差异：

- 这里 `rows` 的上限是 `gray.shape[0]`（整窗高度 1850），所以会多算几行"画布外"的槽位；
  但后面用 `if y0 + ph > gray.shape[0]` 与亮度过滤把它们排除。
- 实际有效行到 1638 为止。

```python
    out = []
    for x in cols:
        for y in rows:
            x0, y0 = int(round(x)), int(round(y))
            if y0 + ph > gray.shape[0] or x0 + pw > gray.shape[1]:
                continue
            box = gray[y0:y0 + int(ph), x0:x0 + int(pw)]
            if box.size == 0 or float(box.mean()) < 40:
                continue
            core = box[int(ph * 0.3):int(ph * 0.7), int(pw * 0.3):int(pw * 0.7)]
            if core.size == 0 or float(core.mean()) < 40:
                continue
```

**三重占用判定**（缺一不可）：

1. 越界检查：槽位不能被窗口裁掉；
2. `box.mean() >= 40`：整盒不能是全黑背景（空槽位）；
3. `core.mean() >= 40`：**中心区**也不能是全黑 —— 防止"凸扣伸进来一点点"被误当成一块碎片。

```python
            wf = float((box > 238).mean())
            df = float((box < 45).mean())
            white = (wf > 0.68) and (wf + df >= 0.93)
            out.append({"x": x0, "y": y0, "white": white, "wf": wf})
```

**白块判定的两个量**：

- `wf`（white fraction）：盒内近白像素占比；
- `df`（dark fraction）：盒内近黑（背景色）占比。

判据 `wf > 0.68 且 wf + df ≥ 0.93` 的几何含义：

> 白碎片的盒内像素只由两种东西填满——**纯白本体** + **缺口处露出的黑背景**，
> 所以 `wf + df ≈ 1`。而"白底照片"（白底黑伞、白底单车）中间的**对象**既不是白也不是黑，
> 于是 `wf + df` 明显偏小（实测 0.53~0.73）。

阈值来历：实测白块 `(0.79, 0.16)`、`(0.77, 0.19)`，`wf+df` 恰好 0.95；
白底照片 `(0.53, 0.20)`、`(0.62, 0.05)`。原来写 `≥0.95` 时因为浮点舍入
0.9499 被误判成照片 —— 所以放宽到 0.93 并配合 `wf>0.68`。

## 2.11 `class Runner`（260–279 行）—— 唯一的鼠标入口

```python
class Runner:
    def __init__(self, win):
        self.win = win
        self.moves = 0

    def drag(self, fx, fy, tx, ty):
        pyautogui.moveTo(self.win.left + fx, self.win.top + fy)
        time.sleep(MOVE_TO_PAUSE)
        pyautogui.mouseDown()
        time.sleep(DOWN_PAUSE)
        pyautogui.moveTo(self.win.left + tx, self.win.top + ty, duration=DRAG_DUR)
        time.sleep(UP_PAUSE)
        pyautogui.mouseUp()
        time.sleep(SETTLE)
        self.moves += 1

    def place(self, fx, fy, tx, ty):
        before = grab_prog(self.win)
        self.drag(fx, fy, tx, ty)
        return changed(before, grab_prog(self.win))
```

- `self.moves += 1` 放在 `drag` 里：**每一次拖拽都计数**（包括失败的、包括"拖回去"的）。
  这与游戏侧的记步规则一致（一次完整拖拽 = 1 步），所以 `r.moves` 可以当作"已用步数"直接比对预算。
- 坐标一律 `win.left + fx`：`fx` 是**窗口内相对坐标**（我们所有几何都是窗口相对坐标），
  这里统一转屏幕绝对坐标。
- `place()` 就是"拖 + 判"：**没有判据的拖拽不叫落子**。

## 2.12 `main()`（282–422 行）—— 旧流程，仅作参考

这里实现的是 **v5 的"先照片、后白块"** 顺序，v7 已不调用它。但里面有两段代码值得读：

1. **补缺**（333–366 行）：对空着的照片格，用"中心 50% + 48×36 归一化相关"在托盘候选里排序，
   只试前 2 个且要求 ≥0.55。这段逻辑解释了 v7 `place_photo` 兜底分支的来历。
2. **白块阶段**（374–410 行）：`req` 一次性算好、`whites` 一次性算好，
   然后按"约束最多的格子优先"处理。v7 改成了**每次现场重算**（因为棋盘在变），
   但"评分规则 +2/−3"和"每格最多试 3 个"的思想完全一样。

> **问：为什么保留一个不用的 main？**
> 答：作为对照与回归参考；也保留了"照片→白块"这条被证明会在某些布局下死锁的顺序，
> 便于复现问题。实际运行入口只有 `solve_v7.py`。

---

# 三、`solve_v3.py`（360 行）—— 感知与几何层

这是最早写的一层：**把屏幕像素变成可用的几何与语义**。v7 用到的是
`find_win / grab / detect_board / detect_ref / ref_cells / resolve_geometry / ring_order`，
另外 `build_plan`（全分辨率版指派）保留作对照与回归。

## 3.1 常量（文件头）

```python
N = 5              # 5×5
BG = 45            # 画布背景灰度上限
FRAC = 0.5         # 粗匹配使用的参考格中心比例
COARSE_MIN = 0.70  # 粗匹配合格线
DELTA_MIN = 0.10   # 与次佳的差值下限
DRAG_DUR = 0.28
```

- `BG = 45`：画布背景（`#0b1220` 一带）的灰度上限。用于"扣掉背景像素"。
  注意它**低于**棋盘底色 `#0f172a` 的灰度（≈23）？不，23 < 45，所以棋盘底色**低于** BG——
  语义是"比 BG 更暗 = 背景/空白"。
- `FRAC = 0.5`：取参考格中心 50%（四边各去 25%）。
- `COARSE_MIN` / `DELTA_MIN`：见 §3.7。

## 3.2 `find_win()`

```python
def find_win():
    for w in gw.getAllWindows():
        t = w.title.strip()
        if t and ('拼图' in t or 'puzzle' in t.lower()):
            return w
    for w in gw.getAllWindows():
        if t and 'Edge' in w.title:
            return w
    return None
```

两级匹配：先按标题里的「拼图 / puzzle」（页面 title 被 JS 设成「拼图视觉考核」），
再退化到任何 Edge 窗口。
⚠️ **注意第二段有个 bug**：`t` 用的是上一个循环残留的变量（Python 的循环变量会泄漏到作用域外），
所以退化分支实际判断的是"最后一个窗口的标题"。因为第一段几乎总能命中，这个 bug 从未触发——
但如果 Edge 标题不含「拼图」，退化匹配可能返回错误的窗口。

## 3.3 `grab(win)`

```python
def grab(win):
    with mss.MSS() as sct:
        r = {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
        return np.array(sct.grab(r))[:, :, :3]
```

按**窗口矩形**截图（不是整屏）。这里没有 `.copy()`——因为 `np.array(...)` 已经拷贝了。
耗时约 60 ms（3098×1850）。

## 3.4 `detect_board(img)` —— 颜色连通域找棋盘

```python
target = np.array([42, 23, 15], dtype=np.int16)          # #0f172a 的 BGR
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
```

四个要点：

1. **为什么用颜色而不是边缘**：棋盘的填充色是固定常量（源码 `ctx.fillStyle = '#0f172a'`），
   颜色匹配是"零成本的高置信特征"。
2. `sum(axis=2)` 对三通道差值求和 → 一维曼哈顿距离，阈值 18。
   （BGR 是 `(42,23,15)`，即 `#0f172a` 的字节序反转。）
3. **连通域**而不是"扫描找边界"：页面上可能有其它同色元素，取**最大**区域更稳。
4. **`area > 0.12 × w × h` 是放松过的条件**：早期要求 `> 0.9`（"矩形必须几乎实心"），
   但碎片放上去之后棋盘底色只剩缝隙，实心率骤降 → 残局检测必失败。
   0.12 保证"即便被 20 块碎片盖住，缝隙仍足以通过筛选"。

> **问：碎片盖满时这个函数还是会失败吧？**
> 答：会。所以有 `layout.json` 缓存兜底（§3.5）。**残局本来也不需要重新检测**。

## 3.5 `load_layout` / `save_layout`（几何缓存）

```python
LAYOUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout.json")

def load_layout(win):
    try:
        data = json.load(open(LAYOUT_PATH, encoding="utf-8"))
    except Exception:
        return None
    for rec in data.get("layouts", []):
        if abs(rec["w"] - win.width) <= 4 and abs(rec["h"] - win.height) <= 4:
            return rec
    return None
```

- 键是**窗口尺寸**（±4 px 容差）。不同分辨率/缩放会得到不同条目，互不干扰。
- `save_layout` 会先剔除同尺寸的旧条目再追加，等于"同尺寸只保留最新一次成功检测"。
- 这是**工程鲁棒性**而非算法：让程序在"棋盘被盖住"的中间状态也能重新进入。

## 3.6 `detect_ref(img, board)`、`ref_cells(img, ref)`

```python
m = np.zeros_like(g)
x_start = bx + bw + 40
m[by - 40:, x_start:] = (g[by - 40:, x_start:] > BG).astype(np.uint8) * 255
m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
```

- 只在"棋盘右侧 +40px 起"的区域找（参考面板在右边）。
- 阈值 `> BG`（45）：参考图是亮的合成图，面板底色是暗的。
- `MORPH_CLOSE(9×9)`：参考图内部有白色网格线/细缝，闭运算把它们连成整块。
- 筛选条件 `area > 0.9 × w × h`：参考图是**实心矩形**，填充率极高。
  （与棋盘相反——棋盘被遮挡，参考图不会。）

`ref_cells`：

```python
"white": float(cell.mean()) > 243 and float(cell.std()) < 8,
```

原理见 ARCHITECTURE §4.5：混合模式下白格是**纯白填充**（均值≈255、方差≈0），
照片格有内容（方差 25~108）。两个阈值之间是很宽的间隔，判定非常稳。

## 3.7 `masked_ncc(patch, tmpl, valid)` —— 带掩膜的归一化互相关

```python
a = patch[valid].astype(np.float64)
b = tmpl[valid].astype(np.float64)
if a.size < 80 or a.std() < 1e-6 or b.std() < 1e-6:
    return -1.0
a -= a.mean(); b -= b.mean()
d = np.sqrt((a * a).sum() * (b * b).sum())
return float((a * b).sum() / d) if d > 0 else -1.0
```

- 只取 `valid` 为真的像素，再算皮尔逊相关系数。
- 三个退化保护：样本 <80（太少不可信）、任一方标准差≈0（常数无法相关）。
- **为什么需要它**：碎片盒里有缺口，缺口像素是"黑色背景"而不是内容；
  把它们纳入相关会人为制造高相似度。

## 3.8 `build_plan(...)` —— 全分辨率版指派（对照用）

流程与 `fast_plan` 相同，但有三处**更严格**的地方：

```python
r2 = res.copy()
r2[max(0, iy - 120):iy + 120, max(0, ix - 120):ix + 120] = -1.0
second = float(r2.max())
```

1. **区分度 Δ**：把峰值附近 120×120 抹掉后取次高峰，
   `ok` 要求 `coarse − second ≥ DELTA_MIN(0.10)`。
   含义：不仅要"像"，还要"**明显比第二名像**"。

```python
valid = patch > BG
if 0.35 <= float(valid.mean()) <= 1.0:
    refine = masked_ncc(patch, tmpl, valid)
```

2. **精匹配用掩膜**：`valid = 盒内像素 > BG`（非背景），
   并要求有效像素占比在 [0.35, 1.0] —— 太低说明盒位置偏了。

```python
seen = {}
for k, d in plan.items():
    key = (round(d["box"][0] / 40), round(d["box"][1] / 40))
    seen.setdefault(key, []).append(k)
for key, ks in seen.items():
    if len(ks) > 1:
        for k in ks:
            plan[k]["ok"] = False
```

3. **冲突检测**：把盒坐标按 40px 量化，两格落入同一桶 → 视为"抢同一块"，**双方都作废**。
   这是把"独立匹配"提升为"受一对一约束的指派"的关键一步。

> ⚠️ **已知差异**：`fast_plan`（v6）**没有** Δ 与冲突检测，只要求 `coarse≥0.70 且 exact≥0.70`。
> 实测两次都是 20/20、零冲突，所以没有触发问题；
> 但严格说，`build_plan` 的约束更强。若要绝对稳妥，可以把 Δ 与冲突检测加回 `fast_plan`
> （代价：多取一次次高峰，约 +2 ms/格）。

## 3.9 `resolve_geometry(win, img, verbose)`

```python
board = detect_board(img)
ref = detect_ref(img, board) if board else None
if board and ref:
    save_layout(win, board, ref)
    return board, ref
cached = load_layout(win)
if cached:
    return tuple(cached["board"]), tuple(cached["ref"])
return board, ref
```

**检测优先，缓存兜底**。成功即写缓存（越用越准）。
返回值可能是 `(None, None)`，调用方必须判空。

## 3.10 `ring_order()` —— 环序

```python
for d in range((N + 1) // 2):
    for r in range(N):
        for c in range(N):
            if min(r, c, N - 1 - r, N - 1 - c) == d:
                order.append((r, c))
```

`min(r, c, N-1-r, N-1-c)` 是"到最近边的距离"，即**环号**。
`d = 0` 得到 16 个外圈格，`d = 1` 得 8 个，`d = 2` 得中心 1 个（`(N+1)//2 = 3` 轮）。
这是一个满足"锚点偏序"的**拓扑序**。

## 3.11 `drag(...)`（旧版，v7 不用）

```python
pyautogui.moveTo(win.left + fx, win.top + fy)
time.sleep(0.05)
pyautogui.mouseDown()
time.sleep(0.05)
pyautogui.moveTo(win.left + tx, win.top + ty, duration=DRAG_DUR)
time.sleep(0.06)
pyautogui.mouseUp()
```

与 `Runner.drag` 的区别：**没有最后的 `SETTLE`，也不计数**。
v7 用 `Runner.drag`（带 0.30 s 静置），这个函数只被遗留的 `main()` 使用。

## 3.12 `main()`（遗留流程）

`build_plan` → 逐格 `drag_and_check`（用 `is_snap` 的 nudge 判据）。
这套是**v3 时代**的做法，nudge 会拽松已拼对的块，已被"进度差分 + 交错调度"取代。
保留它是为了复现历史行为。

---

# 四、`solve_white.py`（414 行）—— 形状语言层

它回答一个看似简单、实则最难的问题：**5 块纯白碎片彼此像素完全相同，怎么区分？**

答案是：**看四条边的凹凸形状**。这个文件就是把形状读出来、量化、比较。

> ⚠️ 注意：文件里的 `main()` 是**旧的"排列求解"流程**（5 块对 5 格做 120 种排列打分），
> v7 已经不用它。v7 复用的是本文件的**测量函数**：
> `content_mask / isolate_component / white_piece_signature / required_shape`。

## 4.1 头部（14–24 行）

```python
import itertools, os, sys, time
import numpy as np
import cv2
import pyautogui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve_v3 import find_win, grab, resolve_geometry, ref_cells, N, BG

HERE = os.path.dirname(os.path.abspath(__file__))
pyautogui.PAUSE = 0.03
DRAG_DUR = 0.28
```

- `itertools`：旧 flow 里生成 5! = 120 种排列。
- `HERE`：本文件目录，用于输出调试图。

## 4.2 `content_mask(gray, lo=55, chroma_min=45, img=None)`（28–42 行）

```python
    bright = gray > lo
    if img is not None:
        b = img[:, :, 0].astype(np.int16)
        g2 = img[:, :, 1].astype(np.int16)
        r = img[:, :, 2].astype(np.int16)
        chroma = np.maximum(np.maximum(b, g2), r) - np.minimum(np.minimum(b, g2), r)
        return bright | (chroma > chroma_min)
    return bright
```

**定义"什么算内容"**：`灰度 > 55` **或** `色度 > 45`。

为什么是这两条：

| 方案 | 问题 |
|---|---|
| 只看亮度 | 凸扣里填的是**邻格照片**，可能是深色（比如深色背景下的一只黑猫），会被漏掉 |
| 加"局部方差" | 未放置碎片带 `shadowBlur 8` 的**投影**，投影边缘方差很大，会被误判成内容 |
| 亮 **或** 彩 | 白/浅色内容靠亮度，深色但有颜色的内容靠色度 |

⚠️ `chroma_min` 不能设太低：棋盘底色 `#0f172a` 的色度恰好是 `42−15 = 27`。
早期用 26 时，**整个棋盘都被判定为"内容"**，所有边界测量全部崩坏。

## 4.3 `_cls_extreme(probes, tab_sign)`（45–62 行）

```python
def _cls_extreme(probes, tab_sign):
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
```

把一组"探针值"判成 `{+1, −1, 0}`。两个参数：

- `probes`：沿某条边采样得到的偏移量集合（正负号含义由方向决定）；
- `tab_sign`：方向修正。`+1` 表示"值越正 = 邻块凸进来"（我们的边要凹），
  `−1` 表示方向相反（用于下边界和右边界，因为它们的坐标增长方向相反）。

判定用**极值**而不是中位数，原因见 §4.4。

## 4.4 `side_shape(mask, x0, y0, x1, y1, side, thick=10, span=(0.16,0.84))`（65–110 行）—— 核心

```python
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
```

（左右边同理，只是按行扫描。）

**算法三步**：

1. **剖面**：沿边采样，每列（或每行）取"内容的最外缘"。
   上边取 `col.min()`（最上面的内容行），下边取 `col.max()`。
2. **中位数当基准线**：`med = median(prof)`。
   理由：凸扣只占边中部约 30%，两侧各 35% 落在**真实盒线**上，
   所以中位数自然等于"盒线"，**不需要知道盒的确切位置**。
3. **极值判决**：`up = med − min(prof)`（向上凸出多少）、`dn = max(prof) − med`（向下凹进多少），
   超过 12px 即判定。

**为什么必须用极值而不是中位数**（真实 bug）：

```
缺口处的剖面是 V 形：  +3.6  +3.6  ...  −23.4  ...  +3.6  +3.6
中位数 ≈ −1.4   → 落进"平"的区间 → 把清晰的凹口读成 0
极值  min = −23.4 → 正确判为"凹"
```

**为什么基准要用中位数而不是盒坐标**（另一个真实 bug）：
盒位置由格点公式推算，有 6~10px 误差（碎片本身还有 ±2.5% 抖动）。
若用绝对坐标当基准，`+27px 的凸`会被读成 `+17`，`−27px 的凹`会被读成 `−37`，
甚至符号翻转。中位数让基准**从数据里自己长出来**，与标定误差无关。

- `thick=10`：只在盒边上下各 10px 内找内容，避免扫到远处的东西。
- `span=(0.16, 0.84)`：沿边只取中间 68%，避开四角（角上属于邻边）。
- `len(prof) < 10` 返回 `None`：采样点太少（边被切掉）→ "未知"而不是猜。

## 4.5 `white_piece_signature(pmask)`（113–122 行）

```python
def white_piece_signature(pmask):
    ys, xs = np.where(pmask)
    if xs.size == 0:
        return None, None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    sig = [side_shape(pmask, x0, y0, x1, y1, s) for s in range(4)]
    return sig, (x0, y0, x1 - x0, y1 - y0)
```

- 输入是**隔离后的掩膜**（只含这一块碎片）。
- 用掩膜的**外接矩形**作为四条边的参考框（不是格点盒！）——因为中位数校准不依赖精确框。
- 返回 `(形状签名, 轮廓框)`。签名顺序固定为 `[上, 右, 下, 左]`。

## 4.6 `side_offsets_white(...)`（125–128 行）

```python
def side_offsets_white(mask, box, pw, ph, reach=34, frac=0.34):
    x, y = box
    return [side_shape(mask, x, y, x + pw, y + ph, s, thick=40) for s in range(4)]
```

兼容旧调用的包装：用给定盒 + 更大的 `thick`。新代码直接用 `white_piece_signature`。

## 4.7 `required_side(...)` / `required_shape(...)`（131–195 行）—— 反向读"需求形状"

```python
    if side in (0, 2):
        b = y if side == 0 else y + ph
        for xx in range(int(x + pw * (0.5 - frac / 2)), int(x + pw * (0.5 + frac / 2))):
            seg = mask[max(0, int(b - reach)):min(H, int(b + reach)), int(xx)]
            idx = np.where(seg)[0]
            if idx.size:
                yy = idx + max(0, int(b - reach))
                probes.append((yy.max() - b) if side == 0 else (yy.min() - b))
        return _cls_extreme(probes, +1 if side == 0 else -1)
```

这个函数站在**空格**的角度看它的邻居：

- 边界坐标 `b`：上边是 `y`，下边是 `y+ph`，左右同理。
- 沿边采样，看**邻块的内容**伸到哪：
  - 邻块的凸扣伸进我们的格子 → 我们这条边要**凹（−1）**；
  - 邻块缩回去了（它的凹口对着我们）→ 我们这条边要**凸（+1）**。
- `reach=30`：只看边界两侧 30px（凸扣深度约 27px）。
- 这里用 `frac=0.34`（中间 34%），比测碎片时的 68% 更窄——因为要看的是边界中部的凸/凹。

`required_shape` 再补上边界条件：

```python
    if r == 0:            out[0] = 0        # 上边框
    if c == N - 1:        out[1] = 0        # 右边框
    if r == N - 1:        out[2] = 0        # 下边框
    if c == 0:            out[3] = 0        # 左边框
```

**外圈边恒为 0**（源码事实）。其余边若邻格还没放，就留 `None`（未知）。

> **问：为什么"需求形状"比"碎片形状"更可信？**
> 答：需求形状是从棋盘上量的——空格是**纯黑画布**，照片块的凸扣是**高对比轮廓**，零污染。
> 碎片形状是在托盘里量的——邻块就在 18px 外，凸扣会互相侵入。
> 实测：需求形状与视觉一致率接近 100%，碎片形状只有约 70%。

## 4.8 `isolate_component(gray, box, pw, ph, pad=42, mask=None, img=None)`（198–225 行）

```python
    src = content_mask(gray, img=img) if mask is None else (mask > 0)
    sub = src[yy0:yy1, xx0:xx1].astype(np.uint8)
    if sub.sum() < 500:
        return None
    n, lab = cv2.connectedComponents(sub, 8)
    cy = int(y + ph / 2) - yy0
    cx = int(x + pw / 2) - xx0
    lbl = lab[cy, cx]
    if lbl == 0:
        ys, xs = np.where(sub > 0)
        d = (ys - cy) ** 2 + (xs - cx) ** 2
        i = int(np.argmin(d))
        lbl = lab[ys[i], xs[i]]
    full = np.zeros(gray.shape, np.uint8)
    full[yy0:yy1, xx0:xx1] = (lab == lbl).astype(np.uint8)
    return full.astype(bool)
```

**为什么需要它**：碎片间隔只有 18px，凸扣凸出 27px → 邻块的凸扣会进入我方的测量窗口。
不隔离的话，形状会读**反**（实测：视觉是「凸凹凸凹」，代码给「凹凸凹凸」）。

逐行：

- 在盒周围留 `pad=42px` 的窗口做连通域；`sum()<500` 说明窗口里几乎没内容 → 放弃。
- 取**盒中心**所在的那个连通域的标号 `lbl`。
- 若中心恰好落在背景（`lbl==0`，说明盒偏了），退化为"找离中心最近的白色像素"所属的连通域。
- 最后把该连通域还原成**全图尺寸的布尔掩膜**（坐标保持全局，方便后续用绝对坐标测量）。

> **问：如果两块碎片的凸扣真的黏在一起怎么办？**
> 答：会连通成一片，隔离会把两块都圈进来，形状测量不可靠。
> 这就是"形状只有 70% 可信"的物理来源之一。

## 4.9 `find_white_pieces(img, board, ref, pw, ph)`（228–262 行）

```python
    m = (g > 232).astype(np.uint8)
    m[by - 5:by + bh + 5, bx - 5:bx + bw + 5] = 0        # 扣棋盘
    m[:int(by * 0.40), :] = 0                            # 扣顶部 UI
    m[max(0, ry - 40):ry + rh + 40, max(0, rx - 40):] = 0  # 扣参考面板
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
```

纯白碎片是**极亮**的（>232），所以用亮度阈值 + 连通域就能找。
这是**早期版本的主检测器**，现在只用于诊断（主流程用 `tray_pieces` 的格点法）。
它的问题正是前面说的：会漏（黏连）也会多（白底照片的白色区域）。

## 4.10 `snap_to_lattice(...)`（265–281 行）

```python
    stepX, stepY = 1.16 * pw, 1.16 * ph
    c0y = 616.0
    row_center = c0y + stepY / 2 + round((cy_ - c0y - stepY / 2) / stepY) * stepY
    if cx_ < bx:
        origin = 54.0
    else:
        origin = 54.0 + (bx - 54.0) + bw
    col_center = origin + stepX / 2 + round((cx_ - origin - stepX / 2) / stepX) * stepX
    return (col_center - pw / 2, row_center - ph / 2)
```

把任意点吸附到**最近的槽位中心**，再返回该槽位的盒左上角。
`round(...)` 就是"最近整数格"的实现。`cx_ < bx` 判断落在左带还是右带。

## 4.11 `main()`（旧流程，v7 不用）

```
读画面 → 分白格 → 逐格算需求形状 → 找托盘白块 → 量形状
      → 5! = 120 种排列打分 → 选最优 → 逐个拖过去 → 用"格内暗像素"判吸附
```

两个值得理解的点：

1. **为什么 120 种排列**：5 块对 5 格是双射，最坏要枚举全部 120 种。
   打分规则是每边 `+2 / −3`（对不上罚得更重），再做白格之间的**互补约束**
   （相邻两块的白块，边必须相反）。v7 改成**逐格贪心 + 试放**，因为排列求解依赖一次算准所有形状，
   而形状本身只有 70% 可信——不如"猜一个、用进度差分验一个"。
2. **旧吸附判据 `dark_frac < 0.02` 是错的**：白块只要放上去就遮住格子，暗像素≈0，
   判据分不清"吸附"和"已放下"。这一条有明确的失败记录（(2,3) 暗=0.019 被判成功，其实没吸附），
   也是后来全面改用进度差分的原因。

---

# 五、一张图记住四个文件的分工

```
┌────────────── solve_v7.py ──────────────┐
│ 调度：谁先放、放哪格、要不要跳过          │
│   anchored() / do_place() / grab_point() │
└───────────────┬─────────────────────────┘
                │ 需要坐标、需要判据
   ┌────────────▼────────────┐   ┌──────────────────────┐
   │ solve_v6_safe.py        │   │ solve_white.py       │
   │ 判据：变没变（进度差分） │   │ 形状：[上,右,下,左]  │
   │ 时序：5 个 sleep         │   │ 中位数校准 + 极值判决 │
   │ 闸门：就绪/稳定/指派     │   │ 需求形状 vs 碎片形状  │
   └────────────┬────────────┘   └──────────┬───────────┘
                │ 需要画面与几何            │
                └──────────┬───────────────┘
                ┌──────────▼───────────────┐
                │ solve_v3.py               │
                │ 截图 / 棋盘 / 参考图 / 切格│
                │ 模板匹配 / 环序            │
                └───────────────────────────┘
```

---

# 六、自测：能答上这 20 题就算吃透

| # | 问题 | 答案所在 |
|---|---|---|
| 1 | 为什么不需要 YOLO？ | §2.8、ARCH §3.4（参考图=原图） |
| 2 | 模板匹配为什么只取中心 50%？ | §2.8、§4.4 |
| 3 | 缺口深度大约多少？怎么算出来的？ | `0.22 × min(pw,ph)` ≈ 24~27px，源码 `tabSize` |
| 4 | 0.5 倍粗匹配会不会降低精度？ | §2.8（精修 + 0px 偏差实测） |
| 5 | 什么决定了步数预算 33？ | `ceil(25 × 1.3)` |
| 6 | 一次拖拽记几步？什么情况不记步？ | §2.11、ARCH §3.1 |
| 7 | 吸附的三个条件是什么？ | ARCH §3.2 |
| 8 | 为什么 `mouseDown` 后必须停 50ms？ | §2.2、§2.11 |
| 9 | 为什么 `SETTLE` 不能短？ | §2.2（误判连锁） |
| 10 | 吸附判据为什么不用 nudge / 声音 / 棋盘 dump？ | §2.4、ARCH §6.1 |
| 11 | 怎么判断吸附成功？精度如何？ | §2.4（50 像素阈值） |
| 12 | 白块怎么区分？为什么不把形状当最终依据？ | §4.5–4.7 |
| 13 | 中位数校准解决什么问题？极值判决解决什么问题？ | §4.4 |
| 14 | 为什么托盘检测不用连通域？ | §2.10（30 块只数出 17 块） |
| 15 | 行数写死 8 行导致了什么后果？ | §2.10 |
| 16 | 白块判定的 `wf + df ≥ 0.93` 是什么含义？ | §2.10 |
| 17 | 为什么会"死锁"？怎么解决？ | §1.9、§1.13 |
| 18 | 两块碎片重叠时为什么抓错？怎么修？ | §1.7、§1.10 |
| 19 | 为什么失败要拖回"槽位"而不是原位？ | §1.10 |
| 20 | 连续失败 4 次即停，为什么是必要保护？ | §1.13 |

---

# 七、已知的瑕疵（面试/提问时主动说，比被问出来好）

1. `find_win()` 的退化分支用了泄漏的循环变量 `t`（§3.2）——第一段几乎总能命中，故未暴露。
2. `fast_plan` 少了 `build_plan` 的 Δ 区分度与冲突检测（§3.8）——实测 20/20 未出问题，但约束更弱。
3. 进度计数器区域 `PROG` 与格点常量 `54.0 / 616.0` 都是**按 3098×1850 标定的硬编码**，
   换分辨率/缩放就会失效（§2.1、§1.5）。
4. 终局完整性用的是"格内有无内容"，不是"是否吸附"（§1.14）——理论上可能把"躺在格子上的碎片"算作已拼。
5. 白块形状约 70% 可信，靠试放兜底；理想是 25 步，实测 27~33 步（§4.7）。
