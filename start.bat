@echo off
chcp 65001 >nul
echo ========================================
echo         语音输入法启动脚本
echo ========================================
echo.

echo [1/3] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)
echo [OK] Python已安装

echo.
echo [2/3] 安装依赖包...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

echo.
echo [3/3] 启动服务...
echo.
echo ========================================
echo   启动中，请稍候...
echo   服务地址: http://localhost:5000
echo ========================================
echo.

set TENCENT_SECRET_ID=your_secret_id_here
set TENCENT_SECRET_KEY=your_secret_key_here

python app.py

pause