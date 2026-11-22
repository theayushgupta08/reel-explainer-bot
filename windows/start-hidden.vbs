' Starts the bot in the background with no window. Used by Windows auto-start.
' Logs go to bot.log in the project folder. Use stop-bot.bat to stop it.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

' Keep yt-dlp current (Instagram changes often break old versions). Waits up to ~30s.
sh.Run """.venv\Scripts\python.exe"" -m pip install -U yt-dlp --quiet --timeout 10 --retries 1", 0, True

' Start the bot hidden; don't wait for it.
sh.Run """.venv\Scripts\pythonw.exe"" bot.py", 0, False
