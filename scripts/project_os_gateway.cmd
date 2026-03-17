@echo off
setlocal
py "%~dp0project_os_gateway_op.py" %*
exit /b %errorlevel%
