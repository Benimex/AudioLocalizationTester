@echo off
REM Build LocalizationTest.exe (single-file, no console).
REM Requires: pip install flask sounddevice numpy scipy slab pyinstaller pywebview
py -3 -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name LocalizationTest ^
  --add-data "static;static" ^
  --add-data "eq;eq" ^
  --add-data "stimuli;stimuli" ^
  --collect-all slab ^
  --collect-all webview ^
  desktop.py
echo.
echo Done. Output: dist\LocalizationTest.exe
