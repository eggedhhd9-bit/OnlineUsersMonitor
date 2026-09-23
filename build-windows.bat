@echo off
setlocal
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements-build.txt
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name StaffAttendance staff_attendance.py
if errorlevel 1 exit /b 1
echo Build complete: dist\StaffAttendance.exe
endlocal
