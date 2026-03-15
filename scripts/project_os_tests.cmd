@echo off
setlocal
py "%~dp0project_os_tests.py" %*
exit /b %errorlevel%
