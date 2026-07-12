@echo off
setlocal
rem planning-with-files: Windows hook launcher for Codex (issue #201).
rem Codex runs each hook's commandWindows; on Windows that routes here as:
rem   cmd /c .codex\hooks\pwf-hook.cmd <script.py> [args...]
rem A .cmd is the one form that runs identically whether Codex spawns the hook
rem via cmd.exe, PowerShell, or direct CreateProcess, and it lets us fall back
rem from the py launcher to python.exe. The Microsoft Store python3.exe alias is
rem deliberately never selected. Always exits 0 so an advisory hook cannot
rem report "hook exited with code 1".
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY exit /b 0
%PY% "%~dp0%~1" %2 %3 %4 %5
exit /b 0
