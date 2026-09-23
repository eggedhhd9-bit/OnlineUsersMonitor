@echo off
setlocal
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements-build.txt
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name DNSCleanFinder dns_clean_finder.py
if errorlevel 1 exit /b 1
echo Build complete: dist\DNSCleanFinder.exe
endlocal
