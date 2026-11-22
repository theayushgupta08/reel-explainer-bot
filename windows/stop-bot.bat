@echo off
rem Stops the background (auto-started) bot and any run.bat copy of it.
powershell -NoProfile -Command ^
  "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*bot.py*' };" ^
  "if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host 'Bot stopped.' } else { Write-Host 'Bot was not running.' }"
pause
