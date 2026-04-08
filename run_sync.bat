@echo off
REM Incrementele order sync - draait elke 15 minuten via Task Scheduler
cd /d "C:\Users\migue\Documents\Earth water"
"C:\Users\migue\AppData\Local\Programs\Python\Python311\python.exe" sync_incremental.py
