@echo off
rem Double-click this to try TelescopeYoke on Windows with a pretend telescope.
rem It installs the Python libraries it needs (Python 3.11 or newer must be
rem installed already), then opens TelescopeYoke (demo). Nothing real is
rem connected or moved. The window stays open if something goes wrong.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Demo
if errorlevel 1 pause
