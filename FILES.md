# 文件清单（上交版）

> 目录：`C:\Users\张奕瑭\Documents\deepseek-harness\default-workspace\puzzle_v3\`
> 共 **20 个文件**：6 个 Python + 启动器 + 几何缓存 + 演示视频 + 测试图 + 2 张通关截图 + 8 份文档。
> 被取代的历史版本、实验脚本、调试截图已移到 `D:\yolo\rubbish\`。

---

## 一、可运行代码（6 个 .py）

| 文件 | 行数 | 职责 |
|---|---|---|
| `solve_v7.py` | 235 | **入口 / 调度层**。环序推进、锚点判断、延迟队列、失败熔断、落点换算。 |
| `solve_v6_safe.py` | 320 | **判据 / 执行层**。进度计数器差分判据、四道就绪闸门、快速模板指派、拖拽时序、`Runner`。 |
| `solve_v3.py` | 190 | **感知 / 几何层**。截图、定位棋盘与参考图、几何缓存、参考图切 5×5、环序、窗口识别。 |
| `solve_white.py` | 186 | **形状语言层**。四边凸/凹/平测量、从空格反推需求形状、隔离连通域。 |
| `record_run.py` | 96 | **演示录制**。后台线程抓屏 + `mp4v` 编码，主线程照常求解；成功才把 `.part.mp4` 改名。 |
| `test_offline.py` | 76 | **离线自检**。不碰鼠标、不开游戏，用 `calib_start.png` 跑 8 项检查。 |

四个核心文件合计 **931 行**。依赖关系：`solve_v7` → `solve_v6_safe` → (`solve_v3`, `solve_white`)；
`record_run` 调用 `solve_v7.main()`；`test_offline` 只调用识别层。

**入口**：
```powershell
python solve_v7.py run                      # 求解
python record_run.py demo_25of25.mp4        # 求解并录制
python test_offline.py                      # 离线自检
```

---

## 二、运行素材（3 个）

| 文件 | 作用 |
|---|---|
| `run_exam.bat` | 一键启动器（内部写死解释器路径，按自己环境改）。 |
| `layout.json` | 窗口几何缓存：`{窗口宽高 → 棋盘矩形, 参考图矩形}`。检测成功时写入，残局读取。删掉不会崩。 |
| `calib_start.png` | **回归测试用**：一张真实开局截图（3098×1850，碎片齐全），供 `test_offline.py` 使用。 |

---

## 三、演示与证据（3 个）

| 文件 | 内容 |
|---|---|
| `demo_25of25.mp4` | **完整求解录屏**：266 帧 / 8fps / 33.2 秒 / 1548×924 / 3.8 MB。结尾弹窗显示 25/25、33 步、用时 00:49。 |
| `V8_DONE.png` | 通关截图：25/25、33 步、用时 00:39。 |
| `V8_RUN2.png` | 通关截图：25/25、27 步、用时 00:49。 |

---

## 四、文档（8 个）

| 文件 | 内容 |
|---|---|
| `README.md` | **总说明**：效果、环境、运行、结构、算法要点、录屏、整理说明、已知限制。 |
| `ARCHITECTURE.md` | 架构与原理：数据流、四层职责、判据演化史、失败模式目录、性能数据。 |
| `CODE_GUIDE.md` | 逐行代码导读，每个函数配代码 + 逻辑 + 为什么 + 20 题自测。 |
| `FUNCTIONS.md` | 全函数速查表：`[类型] 做什么 → 为什么 / 谁用`。 |
| `NOTES.md` | 逆向记录：站点机制（判分/吸附/锚点/边矩阵）与每一局失败的复盘。 |
| `RUN.md` | 操作手册：怎么跑、硬约束、常见输出含义。 |
| `CRASH_COURSE.md` | 3 小时速通路线。 |
| `FILES.md` | 本文件。 |

> 注：`ARCHITECTURE.md` / `CODE_GUIDE.md` / `FUNCTIONS.md` 写于整理前，开头已加版本说明；
> 它们包含的已删函数讲解作为原理参考仍然有效，当前 API 以源码与 `README.md` 为准。

---

## 五、与旧版的差异

### 删除的死代码（不参与运行）

| 文件 | 删除内容 | 原因 |
|---|---|---|
| `solve_v3.py` | `drag`、`cell_mean`、`masked_ncc`、`build_plan`、`main` | nudge 判据时代与全分辨率对照实现 |
| `solve_white.py` | `main`（5! 排列求解）、`find_white_pieces`、`snap_to_lattice`、`side_offsets_white` | 被「试放 + 进度差分」取代 |
| `solve_v6_safe.py` | `main`（旧 v5「先照片后白块」流程） | v7 有自己的调度 |

### 修复的问题

1. **`find_win()` 误认窗口**：原按「标题含 puzzle」匹配，代码目录名 `puzzle_v3` 会让编辑器窗口命中
   → 改为按**进程名**识别浏览器（`msedge.exe` 等）+ 窗口尺寸下限。
2. **终局自检误报空格**：原用「格内均值 ≥60」判有内容，深色照片格会被判成空格
   → 改为以 `placed` 为准，灰度自检仅作提示。
3. **托盘格点表重复实现**：v6 与 v7 各写一遍 → 抽出 `tray_lattice()` 共用。
4. 清掉全部无用 import，常量只在一处定义。

### 功能等价性

清理前后在 `calib_start.png` 上跑检测与指派，棋盘、参考图、白格集合、托盘计数、
20 个 `box` 坐标与匹配分数**逐字段完全一致**；`test_offline.py` 8 项检查全 PASS。

---

## 六、`D:\yolo\rubbish`（历史存档）

| 类别 | 内容 |
|---|---|
| 历史主程序 | `solve_v3_full.py`、`solve_v4.py`（首次 25/25）、`solve_v5_fast.py`（失败实验） |
| 实验脚本 | `calib*`、`bench`、`compare_plans`、`oracle_test`、`seam_test`、三次指纹尝试、`verify_detect`、`check_white_thresh`、`probe_cells`、`find_last`、`finish_*`、`unblock`、`white_*`、`_diag_input` |
| 一次性工具 | `_snapshot.py`（清理前行为指纹）、`_auto_record.py` / `_auto_record2.py`（自动重开+录制） |
| 调试截图 | 约 60 张 |
| 清理前原版 | `_legacy_orig/` 下四个 `*_orig.py` |
