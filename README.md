# بررسی کاربران آنلاین ویندوز

برنامهٔ دسکتاپ سبک برای نمایش نشست‌های ورود همین رایانه و ثبت دوره‌ای آن‌ها در CSV.

## اجرا روی Windows 10/11

1. Python 3.12 را نصب کنید.
2. فایل `build-windows.bat` را اجرا کنید.
3. فایل `dist\OnlineUsersMonitor.exe` را اجرا کنید.

گزارش در `%LOCALAPPDATA%\OnlineUsersMonitor\online-users.csv` ذخیره می‌شود. بررسی هر ۳۰ ثانیه انجام می‌شود. برنامه از فرمان داخلی `quser` استفاده می‌کند و کاربران رایانه‌های دیگر را پایش نمی‌کند.

## ساخت خودکار در GitHub

با push کردن tag مانند `v1.0.0`، GitHub Actions فایل exe را ساخته و به GitHub Release همان tag پیوست می‌کند. اجرای دستی workflow نیز artifact قابل دانلود تولید می‌کند.
