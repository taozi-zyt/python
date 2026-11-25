@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  拼图视觉考核 自动求解器
echo  1) 先把 Edge 打开并最大化，进 exam 页
echo  2) 本脚本会等待「新手局 + 画面就绪」
echo  3) 就绪后才点「开始这一部分」也可以
echo  4) 运行期间不要碰鼠标键盘
echo ============================================
echo.
"D:\yolo_demo\yolovenv\Scripts\python.exe" -u solve_v7.py run
echo.
echo 退出码: %ERRORLEVEL%
pause
