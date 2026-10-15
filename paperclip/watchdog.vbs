' Runs paperclip\watchdog.ps1 without flashing a console window (started every 5 minutes by the
' "Cloudworks watchdog" scheduled task).
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\Desj Griesel\pionex\paperclip\watchdog.ps1""", 0, True
