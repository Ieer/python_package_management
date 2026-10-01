@echo off  
setlocal  
  
:: 设置变量  
set "rootDir=%~dp0"
set "packageDir=%rootDir%package311"
set "pipReqFile=%rootDir%pwistron.txt"
set "zipFile=%packageDir%\ms-playwright.zip"  
set "destDir=C:\Users\%USERNAME%\AppData\Local"  
  
:: 第一步：使用pip安装指定的包  
pip install --no-index --find-links "%packageDir%" -r "%pipReqFile%"
if %errorlevel% neq 0 (  
    echo Failed to install packages using pip  
    pause  
    exit /b %errorlevel%  
)  

:: 第二步：检查ZIP文件是否存在  
if not exist "%zipFile%" (  
    echo ZIP file not found: %zipFile%  
    pause  
    exit /b 1  
)  
  
:: 设置7-Zip的路径（请根据你的7-Zip安装位置进行修改）  
set "sevenZipPath=C:\Program Files\7-Zip\7z.exe"  
  
:: 第二步：解压ZIP文件到指定目录  
"%sevenZipPath%" x "%zipFile%" -o"%destDir%" -y  
if %errorlevel% neq 0 (  
    echo Failed to extract ZIP file  
    pause  
    exit /b %errorlevel%  
)  
  
echo Packages have been installed and ZIP file has been extracted to %destDir%  
pause  
endlocal