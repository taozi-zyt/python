# 全自定义函数精读表（代码 + 逻辑 + 用处）

> ⚠️ **版本说明**：本表写于代码整理之前，收录了当时的 39 个函数。整理后删除了其中 7 个
> 历史/无用函数（`build_plan`、`masked_ncc`、`cell_mean`、`drag`、`find_white_pieces`、
> `snap_to_lattice`、`side_offsets_white`）与 3 个遗留 `main()`。当前实际 API 以源码为准，
> 删除清单见 `FILES.md` 第六节；被删函数的原理说明作为历史参考仍然有效。

> 每个函数：**关键源码 → 逻辑 → 用处 → 精度要求（若有）**
> 标 ⭐ 的是"精度敏感"函数，答问最容易被追到这里。

---

# 一、`solve_v7.py`（调度层，8 个）

## 1. `main()` — 入口，串联全流程

```
等就绪 → 算 plan → 指派闸门(≥19/20) → 环序逐格 place → 收尾统计
```

**用处**：唯一的运行入口。
**逻辑**：不实现算法，只负责"按正确顺序调用下面这些函数"。

## 2. ⭐ `slot_of(x, y)` — 吸附到最近槽位

```python
return (min(COLS, key=lambda v: abs(v - x)), min(ROWS, key=lambda v: abs(v - y)))
```

**逻辑**：在槽位坐标表里找"离给定值最近"的那个。
**用处**：失败拖回时用它算"回哪个槽位"，避免按漂移位置拖回导致越漂越远。
**精度**：横纵独立取最近，槽位间距 171×127，碎片盒 146×109 —— 不会吸附错位。

## 3. ⭐ `grab_point(x0, y0)` — 决定按哪儿下鼠标

```python
sx, sy = slot_of(x0, y0)
off = max(abs(sx - x0), abs(sy - y0))
if off > 12:
    return x0 + pw * 0.85, y0 + ph * 0.85     # 抓右下角
return x0 + pw / 2, y0 + ph / 2               # 抓中心
```

**逻辑**：盒偏离槽位 ≤12px 说明它正常在槽位上 → 抓中心；偏得多说明被挤过、可能和别的块重叠 → 抓右下角。
**用处**：避免"按中心抓，抓到压在上面那块"（`getPieceAt` 返回最上面那块）。
**精度**：`12` = 正常抖动 ±4 与异常漂移的分界；`0.85` = 靠角但不落到凸扣外的经验值。

## 4. `centre(cell)` — 格子中心

```python
return bx + (cell[1] + 0.5) * pw, by + (cell[0] + 0.5) * ph
```

**逻辑**：列 `c` 用 `pw`、行 `r` 用 `ph`。
**用处**：拖拽的落点。
**精度**：⚠️ 最容易写反的地方（`c*pw` / `r*ph`），写反不报错但全错。

## 5. ⭐ `anchored(cell)` — 复刻游戏的锚点规则

```python
if rr in (0, S.N - 1) or cc in (0, S.N - 1):
    return True
return any((a, b) in placed for a, b in
           [(rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)])
```

**逻辑**：外圈 → 可放；否则四邻有一块已放 → 可放。
**用处**：决定"这一格现在能不能放"，不满足就跳过（避免必败的一步）。
**精度**：与源码 `hasAnchor` 完全一致，不多不少。

## 6. ⭐ `do_place(box, cell)` — 落子（核心算术）

```python
gx, gy = grab_point(x0, y0)
ccx, ccy = bx + cell[1] * pw, by + cell[0] * ph
rx_, ry_ = gx + (ccx - x0), gy + (ccy - y0)
ok = r.place(gx, gy, rx_, ry_)
if not ok:
    sx, sy = slot_of(x0, y0)
    r.drag(rx_, ry_, sx + pw / 2, sy + ph / 2)
```

**逻辑**：
1. 抓取点 `gx,gy`（可能不在中心）；
2. 目标左上角 `ccx,ccy`；
3. **释放点 = 抓取点 + 位移**，保证盒左上角精确落到格子左上角；
4. 失败 → 拖回最近槽位。

**用处**：所有落子都走这里。
**精度**：游戏只按"位移量"移动碎片，所以抓哪儿都行，只要释放点 = 抓取点 + 位移。

## 7. `place_photo(cell)` — 照片格的落子

```
有计划且 ok → do_place(plan[cell]["box"], cell)
否则 → 现场重算相似度，试前 2 个（≥0.55）
```

**逻辑**：优先用开局算好的计划（1 次到位）；计划里没有（被遮挡过）才现场兜底。
**用处**：20 个照片格。
**精度**：兜底限"2 个候选 + 相似度 ≥0.55"，防止烧步数。

## 8. `place_white(cell)` — 白格的试放

```python
req = SW.required_shape(mask, board, pw, ph, cell[0], cell[1])   # 需求形状
sig = SW.white_piece_signature(pm)[0]                            # 碎片形状
sc += 2 if sig[k] == req[k] else -3                              # 评分
```

**逻辑**：读这一格"需要什么形状"→ 给每块白碎片打分 → 排序 → 试前 2 个。
**用处**：5 个白格（内容完全相同，只能靠形状）。
**精度**：评分 `+2 / −3` 不对称——**猜错代价（2 步）大于猜对收益（1 步）**，所以对不上要重罚。

---

# 二、`solve_v6_safe.py`（判据/执行层，10 个）

## 9. `grab_prog(win)` — 只截进度计数器

```python
r = {"left": win.left + PROG[0], "top": win.top + PROG[1],
     "width": PROG[2], "height": PROG[3]}
return np.array(sct.grab(r))[:, :, :3].copy()
```

**逻辑**：把窗口内相对坐标换成屏幕绝对坐标，只抓 250×80。
**用处**：吸附判据的唯一数据源。
**精度**：`.copy()` 防视图被覆盖；窗口内相对坐标 + `win.left` 才对齐屏幕。

## 10. ⭐⭐ `changed(a, b)` — **全系统最重要的一行**

```python
ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.int16)
gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.int16)
return int((np.abs(ga - gb) > 30).sum()) > 50
```

**逻辑**：两帧灰度相减，数"差异 >30 的像素"有多少个，超过 50 个就算"进度文本变了"。
**用处**：**唯一的吸附判据**（吸附 → 进度 +1 → 文本必变）。
**精度（四个数都不能乱改）**：
- `np.int16`：`uint8` 相减会下溢（5−200→61），必须转有符号；
- `30`：单像素差异阈值，滤抗锯齿噪声；
- `50`：像素个数阈值，数字变化约 100~300 像素，噪声 <20，50 是分离点；
- 返回值是 bool：只关心"变没变"，不关心变成几（把 OCR 问题降维成二元判据）。

## 11. `force_foreground(win)` — 抢前台

```python
u.AttachThreadInput(tid_me, tid_fg, True)
u.ShowWindow(h, 3); u.BringWindowToTop(h); u.SetForegroundWindow(h)
u.AttachThreadInput(tid_me, tid_fg, False)
```

**逻辑**：把自己的输入队列挂到前台线程上，绕过 Windows 前台锁；结束后必须解除挂接。
**用处**：Edge 被压到后面时抢回前台（否则截图/点击全打在别的窗口上）。
**精度**：`3 = SW_MAXIMIZE`，顺带保证窗口尺寸不变（几何常量依赖它）。

## 12. `gray_and_filled(img, board)` — 逐格判"有无内容"

```python
if float(g[y0 + 8:y0 + int(ph) - 8, x0 + 8:x0 + int(pw) - 8].mean()) >= 60:
```

**逻辑**：每格内缩 8px 求均值，≥60 视为有内容。
**用处**：判空格、判终局完整性、就绪检查。
**精度**：内缩 8px 避开格线/描边；60 是"棋盘底色 23"与"有内容"之间的分离点。
⚠️ 注意：**有内容 ≠ 已吸附**（碎片可能只是躺在格子上）。

## 13. ⭐ `wait_ready(win, timeout=300)` — 四道闸门

```python
ok = (len(ws) == 5) and (len(filled) == 0) and (len(pieces) >= 24)
if ok:
    drift = np.abs(g1 - g2).mean()          # 相隔 0.7s 两次采样
    if drift > 1.2: continue                # 托盘还在动
    return img2, board, ref, cells
```

**逻辑**：① 画面真伪（能检到 5 白格）② 棋盘全空 ③ 托盘 ≥24 块 ④ **稳定性 drift ≤1.2**。
**用处**：一步不动地等到"可以安全开始"的那一刻。
**精度**：`drift ≤ 1.2` 是"碎片还在撒 vs 已静止"的分界——这一条曾避免了一局 8 步 0 落子。

## 14. ⭐⭐ `fast_plan(img, board, ref, scale=0.5)` — 提速版指派

关键四段：

```python
m = int(round(min(H, W) * 0.25))                    # 中心 50%
sub = cell[m:H - m, m:W - m]
```
```python
small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
```
```python
ok = cv2.erode(allowed_s, np.ones(small_t.shape, np.uint8))[:res.shape[0], :res.shape[1]]
res[ok < 128] = -1.0
```
```python
box = (x0 + jx - int(round(m * sx)), y0 + jy - int(round(m * sy)))
```

**逻辑**：中心 50% 当模板 → 0.5 倍粗搜 → 掩膜+腐蚀排除禁区 → 取峰 → 换算回原图 → ±6 窗口用原尺寸模板精修 → 减去中心裁剪偏移得 box。
**用处**：产出 `plan`（20 个照片格 → 碎片位置）。
**精度**：
- `0.25`：缺口深约 22%min(pw,ph)，取 25% 安全（整块比分 0.47 → 中心 50% 0.98）；
- `0.5`：粗搜快 4 倍，但必须配精修，否则偏 ±5px；
- `erode` 用**模板尺寸**当核：保证模板整体在允许区内；
- `m*sx`：把"参考图像素偏移"换算到"碎片盒像素偏移"；
- 阈值 `coarse ≥ 0.70 且 exact ≥ 0.70`。

## 15. `blob_mask(img, board, ref)` — "有东西"的掩码

```python
chroma = np.maximum(np.maximum(b_, g_), r_) - np.minimum(np.minimum(b_, g_), r_)
m = ((gray > 55) | (chroma > 45)).astype(np.uint8)
```

**逻辑**：亮 **或** 有颜色 = 内容（深色照片也能覆盖）。
**用处**：数碎片、诊断。
**精度**：`chroma > 45` 不能降——棋盘底色 `#0f172a` 的色度恰好 27，降到 26 会把整个棋盘当内容。

## 16. `count_blobs(img, board, ref)` — 数亮块

**逻辑**：连通域 + 尺寸过滤（面积 ≥4000、边长 55~420）。
**用处**：只作日志参考，**不做闸门**（碎片会黏连：30 块常只数出 12~17）。

## 17. ⭐ `tray_pieces(img, board, ref)` — 格点表点名

```python
step_x, step_y = 1.16 * pw, 1.16 * ph
cols.append(54.0 + k * step_x + (step_x - pw) / 2)
cols.append(54.0 + (bx - 54.0) + bw + k * step_x + (step_x - pw) / 2)
while 616.0 + k * step_y + (step_y - ph) / 2 + ph <= gray.shape[0]:   # 行数动态
```
```python
if box.size == 0 or float(box.mean()) < 40: continue
core = box[int(ph*0.3):int(ph*0.7), int(pw*0.3):int(pw*0.7)]
if core.size == 0 or float(core.mean()) < 40: continue
```
```python
white = (wf > 0.68) and (wf + df >= 0.93)
```

**逻辑**：按槽位公式算出所有格点 → 逐点判断"有没有东西" → 判断"是不是纯白块"。
**用处**：找托盘里所有碎片（主要在旧 main / 诊断里用）。
**精度（三条都是坑）**：
- `1.16`：槽位间距比碎片宽 16%（凸扣要伸出）；
- **行数必须动态**：曾写死 8 行，而实际 9 行，第 9 行的白块整块漏掉；
- `wf>0.68 且 wf+df≥0.93`：白碎片的盒内只有"白本体 + 缺口黑底"→ 两者相加≈1；白底照片的中间对象既非白非黑 → 相加只有 0.53~0.73。

## 18. ⭐ `class Runner` — 唯一碰鼠标的地方

```python
def drag(self, fx, fy, tx, ty):
    pyautogui.moveTo(...); time.sleep(MOVE_TO_PAUSE)   # 0.05
    pyautogui.mouseDown(); time.sleep(DOWN_PAUSE)      # 0.05  ← 必须！
    pyautogui.moveTo(..., duration=DRAG_DUR)           # 0.28
    time.sleep(UP_PAUSE)                               # 0.06
    pyautogui.mouseUp()
    time.sleep(SETTLE)                                 # 0.30
    self.moves += 1

def place(self, fx, fy, tx, ty):
    before = grab_prog(self.win)
    self.drag(fx, fy, tx, ty)
    return changed(before, grab_prog(self.win))
```

**逻辑**：5 段时序 + 前/后各截一次进度区 → 差分判吸附。
**用处**：所有落子。
**精度（两个致命参数）**：
- `DOWN_PAUSE = 0.05`：设 0 会让浏览器把"按下"和"移动"合并 → 碎片位移为 0 → **一次都吸不上**（实测 56 步只落 1 块）；
- `SETTLE = 0.30`：设 0.20 时进度文本还没重绘就判定 → 误判未吸附 → **连锁失败**（实测 34 步只落 2 块）。

---

# 三、`solve_v3.py`（感知/几何层，11 个）

## 19. `find_win()` — 找窗口

**逻辑**：先按标题含「拼图 / puzzle」，退化找 Edge。
**用处**：所有后续操作的窗口对象来源。
⚠️ 已知瑕疵：退化分支用了泄漏的循环变量 `t`。

## 20. `grab(win)` — 按窗口矩形截图

```python
r = {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
```

**逻辑**：抓窗口而不是整屏，坐标与鼠标同一套物理像素。
**用处**：几何检测、模板匹配的底图。
**精度**：进程必须 DPI-aware，否则坐标被系统缩放改写。

## 21. ⭐ `detect_board(img)` — 颜色找棋盘

```python
target = np.array([42, 23, 15], dtype=np.int16)      # #0f172a 的 BGR
mask = (np.abs(img.astype(np.int16) - target).sum(axis=2) < 18).astype(np.uint8)
if w > 400 and h > 300 and area > 0.12 * w * h:      # 0.12 是放松过的条件
```

**逻辑**：找棋盘底色的大连通域。
**用处**：确定棋盘矩形（`BOARD`）。
**精度**：`area > 0.12·w·h` —— 碎片盖住棋盘后实际填充率会掉到 0.1 量级，早先要求 0.9 会在残局失效。

## 22. `load_layout(win)` / `save_layout(win, board, ref)`

**逻辑**：以"窗口宽高（±4px）"为键，缓存棋盘与参考图矩形。
**用处**：残局检测失败时兜底；成功时自动更新。
**精度**：键是窗口尺寸，所以换分辨率不会用错旧数据。

## 23. `detect_ref(img, board)` — 找参考图

```python
m[by-40:, x_start:] = (g[by-40:, x_start:] > BG).astype(np.uint8) * 255
m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
if w > 400 and h > 300 and area > w * h * 0.9:
```

**逻辑**：棋盘右侧找"最大的、几乎填满外接矩形的亮块"。
**用处**：确定参考图矩形（`REF`），进而切 5×5。
**精度**：填充率 0.9（参考图是实心矩形，与棋盘相反）。

## 24. ⭐ `ref_cells(img, ref)` — 切 5×5 + 白格判定

```python
"white": float(cell.mean()) > 243 and float(cell.std()) < 8,
```

**逻辑**：切格 → 每格算 mean/std → 两条件判白格。
**用处**：`cells`（25 格分类表），决定后续每格走照片/白块流程。
**精度**：
- `243`：白格实测 mean ≥254，照片格 ≤221；
- `8`：白格实测 std ≤3.8（噪声上界），照片格 ≥23 → 8 = 噪声上界×2；
- 两个条件缺一不可（只看 mean 会误判白底照片）。

## 25. `masked_ncc(patch, tmpl, valid)` — 掩膜相关

```python
a = patch[valid]; b = tmpl[valid]
if a.size < 80 or a.std() < 1e-6 or b.std() < 1e-6: return -1.0
a -= a.mean(); b -= b.mean()
return (a*b).sum() / sqrt((a*a).sum() * (b*b).sum())
```

**逻辑**：只在 `valid` 像素上算 NCC（完整版，含完整的归一化）。
**用处**：`build_plan` 的精匹配。
**精度**：样本 <80 或任一方方差≈0 → 返回 −1（不可判，而不是乱判）。

## 26. ⭐ `build_plan(img, board, ref)` — 全分辨率版指派（对照）

比 `fast_plan` 多三处严格：

```python
r2[max(0,iy-120):iy+120, max(0,ix-120):ix+120] = -1.0
second = float(r2.max())                      # ① 次佳峰
```
```python
valid = patch > BG
if 0.35 <= float(valid.mean()) <= 1.0:        # ② 掩膜精匹配
```
```python
key = (round(box[0]/40), round(box[1]/40))    # ③ 冲突检测：两格抢一块 → 都作废
```

**逻辑**：粗匹配 + Δ 区分度 + 掩膜精匹配 + 冲突检测。
**用处**：验证/对照（`fast_plan` 少了 ①③）。
**精度**：`DELTA_MIN=0.10` —— 不仅"像"，还要"明显比第二名像"。

## 27. `resolve_geometry(win, img)` — 检测 → 缓存 → 返回

**逻辑**：检测成功就写缓存并返回；失败读缓存；都失败返回 None。
**用处**：所有几何的统一入口。

## 28. `ring_order()` — 环序

```python
if min(r, c, N-1-r, N-1-c) == d:
```

**逻辑**：按"到最近边的距离"分环，0 环（16 格）→ 1 环（8）→ 中心（1）。
**用处**：满足锚点偏序的拓扑序。

## 29. `drag(...)` / `cell_mean(...)` / `main()` — 遗留（v7 不用）

`drag`：无 SETTLE、不计数；`cell_mean`：格子均值；`main`：nudge 时代的旧流程。

---

# 四、`solve_white.py`（形状层，10 个）

## 30. ⭐ `content_mask(gray, img)` — 定义"内容"

```python
bright = gray > 55
chroma = max(B,G,R) - min(B,G,R)
return bright | (chroma > 45)
```

**逻辑**：亮 **或** 有颜色。
**用处**：形状测量的输入。
**精度**：不能用"局部方差"（碎片投影会骗人）；`chroma>45` 不能降（棋盘色度 27）。

## 31. `_cls_extreme(probes, tab_sign)` — 极值判凸凹

```python
hi, lo = max(probes), min(probes)
if tab_sign > 0:
    if hi > 10: return -1
    if lo < -10: return +1
```

**逻辑**：极值超阈值 → 判凸/凹，含方向修正。
**用处**：`side_shape` 的判据。
**精度**：用极值不是中位数（缺口处 V 形剖面的中位数落在"平"区间）。

## 32. ⭐⭐ `side_shape(mask, x0, y0, x1, y1, side)` — 核心

```python
prof = [每列的"最外缘内容行"]
med = np.median(prof)                 # ← 基准线从数据里长出来
up, dn = med - prof.min(), prof.max() - med
if side == 0: return +1 if up > 12 else (-1 if dn > 12 else 0)
```

**逻辑**：沿边采剖面 → **中位数当基准** → **极值判凸凹**。
**用处**：量一块碎片/一个格子的某条边。
**精度（两层各治一个 bug）**：
- 中位数基准：治**盒位置偏差**（盒有 6~10px 误差，用绝对坐标会把凸读成凹）；
- 极值判决：治**V 形剖面**（剖面 `+3.6 … −23.4 … +3.6`，中位数只有 −1.4 → 会误判为平）；
- `12px` 阈值：凸扣深约 27px，取一半留余量。

## 33. `white_piece_signature(pmask)` — 四边签名

```python
x0, x1 = xs.min(), xs.max(); y0, y1 = ys.min(), ys.max()
sig = [side_shape(pmask, x0, y0, x1, y1, s) for s in range(4)]
```

**逻辑**：取隔离掩膜的外接框，四条边各量一次 → `[上,右,下,左]`。
**用处**：白碎片的形状描述。

## 34. `side_offsets_white(...)` — 兼容包装

**逻辑**：用给定盒 + 更大的 `thick` 调 `side_shape`。
**用处**：旧调用兼容。

## 35. ⭐ `required_side(...)` / `required_shape(...)` — 反向读"需求形状"

```python
probes.append((yy.max() - b) if side == 0 else (yy.min() - b))   # 邻块伸进来多少
return _cls_extreme(probes, +1 if side == 0 else -1)
```
```python
if r == 0: out[0] = 0        # 外圈边恒为 0
```

**逻辑**：站在空格看邻居——邻块凸进我们 → 我们要凹；邻块缩回 → 我们要凸；边框 → 0；邻居未放 → None。
**用处**：给白格算出"需要什么形状"。
**精度**：在棋盘上量比在托盘里量可靠得多（空格纯黑、零污染）。

## 36. ⭐ `isolate_component(gray, box, pw, ph, ...)` — 隔离"这一块"

```python
sub = content_mask(...)[yy0:yy1, xx0:xx1]
lbl = lab[cy, cx]                       # 盒中心所在的连通域
if lbl == 0: 找离中心最近的白色像素所属连通域
```

**逻辑**：盒中心所在的连通域 → 还原成全图布尔掩膜。
**用处**：量形状前先把"邻居"排除。
**精度**：不隔离会把邻块凸扣算进来 → 形状读**反**（实测过）。

## 37. `find_white_pieces(...)` — 亮块找白块（诊断用）

**逻辑**：亮度 >232 的连通域 + 尺寸过滤。
**用处**：早期主检测器，现仅诊断（会漏黏连、会多算白底照片）。

## 38. `snap_to_lattice(cx, cy, ...)` — 中心吸附到槽位

```python
row_center = c0y + stepY/2 + round((cy_ - c0y - stepY/2) / stepY) * stepY
```

**逻辑**：`round()` 找最近整数格，再返回盒左上角。
**用处**：旧流程里把碎片中心变成盒坐标。

## 39. `main()` — 旧流程（v7 不用）

`5! = 120` 种排列打分求解 + "格内暗像素"判吸附（已证明不可靠）。

---

# 五、一图记住调用关系

```
solve_v7.main()
├── S.wait_ready()                 ← 四闸门
│   ├── force_foreground / grab
│   ├── V3.resolve_geometry        ← detect_board / detect_ref / 缓存
│   ├── V3.ref_cells               ← 白格判定(mean>243, std<8)
│   ├── tray_pieces                ← 格点表 + 白块判定
│   └── gray_and_filled
├── S.fast_plan()                  ← 20 个 box
│   └── ref_cells / 模板匹配 / erode 掩膜 / 精修
└── 环序循环
    ├── anchored()
    ├── place_photo() → do_place() → Runner.place() → changed()
    └── place_white() → SW.required_shape / SW.white_piece_signature
                      → do_place() → Runner.place() → changed()
```
