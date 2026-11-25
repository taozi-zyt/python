# -*- coding: utf-8 -*-
"""录制一次完整求解过程为 MP4（不需要 ffmpeg，用 OpenCV 的 mp4v 编码）。

用法：
    python record_run.py                # 录制并求解，输出 demo.mp4
    python record_run.py my_demo.mp4    # 指定输出文件名

原理：
    后台线程按固定帧率用 mss 抓取游戏窗口，缩放到 1548×924 后写入 VideoWriter；
    主线程照常执行 solve_v7.main()（真实鼠标求解）。
    录制只做只读抓屏，不会干扰鼠标事件。
"""
import os
import sys
import time
import threading

import cv2
import numpy as np
import mss

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_v3 as V3
import solve_v6_safe as S
import solve_v7

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 8
OUT_SIZE = (1548, 924)          # 窗口 3098×1850 的一半


class Recorder(threading.Thread):
    """后台抓屏线程：只读，不影响鼠标操作。"""

    def __init__(self, win, path, fps=FPS, size=OUT_SIZE):
        super().__init__(daemon=True)
        self.win = win
        self.path = path
        self.fps = fps
        self.size = size
        self.stop_flag = threading.Event()
        self.frames = 0
        self.error = None

    def run(self):
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        vw = cv2.VideoWriter(self.path, fourcc, self.fps, self.size)
        if not vw.isOpened():
            self.error = "VideoWriter 打不开（mp4v 不可用）"
            return
        region = {"left": self.win.left, "top": self.win.top,
                  "width": self.win.width, "height": self.win.height}
        interval = 1.0 / self.fps
        with mss.MSS() as sct:
            next_t = time.time()
            while not self.stop_flag.is_set():
                now = time.time()
                if now < next_t:
                    time.sleep(min(0.01, next_t - now))
                    continue
                next_t = now + interval
                try:
                    fr = np.array(sct.grab(region))[:, :, :3]
                except Exception:
                    continue
                if fr.shape[1] == 0 or fr.shape[0] == 0:
                    continue
                vw.write(cv2.resize(fr, self.size, interpolation=cv2.INTER_AREA))
                self.frames += 1
        vw.release()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "demo_25of25.mp4"
    if not out.lower().endswith(".mp4"):
        out += ".mp4"
    final_path = os.path.join(HERE, out)
    # 先写临时文件，成功后再改名，避免中途失败把上一次的成功视频覆盖掉
    path = final_path[:-4] + ".part.mp4"

    win = S.find_win()
    if win is None:
        sys.exit("没找到游戏窗口（浏览器）")
    S.force_foreground(win)
    time.sleep(0.8)

    rec = Recorder(win, path)
    rec.start()
    time.sleep(0.3)                      # 先录一小段静止画面
    code = 3
    try:
        code = solve_v7.main()
    finally:
        time.sleep(0.6)                  # 录到终局画面
        rec.stop_flag.set()
        rec.join(5)

    if rec.error:
        print("录制失败:", rec.error, flush=True)
        return 1
    dur = rec.frames / FPS
    size_mb = os.path.getsize(path) / 1024 / 1024 if os.path.exists(path) else 0
    if code == 0:
        os.replace(path, final_path)
        path = final_path
    print(f"\n视频：{path}")
    print(f"  {rec.frames} 帧 @ {FPS}fps ≈ {dur:.1f}s，{size_mb:.1f} MB，{OUT_SIZE[0]}x{OUT_SIZE[1]}")
    return code


if __name__ == "__main__":
    sys.exit(main())
