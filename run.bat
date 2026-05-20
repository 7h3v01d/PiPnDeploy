@echo off
REM Run PiPnDeploy GUI from the project root.
REM Must be run from G:\Projects\PnD\PiPnDeploy\ (the folder containing PiPnDeploy\)
REM
REM Two valid ways to launch:
REM   1. python -m PiPnDeploy.gui_main     (recommended — works when installed too)
REM   2. python PiPnDeploy\gui_main.py     (direct run — also works via import guard)

python -m PiPnDeploy.gui_main
pause
