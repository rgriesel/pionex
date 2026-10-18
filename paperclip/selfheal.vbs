' Runs the self-heal and engine controller without a console window (task "Cloudworks selfheal", every 2 minutes).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\Desj Griesel\pionex"
sh.Run "cmd /c py paperclip\selfheal.py >> var\logs\selfheal.log 2>&1 & py paperclip\engine_switch.py >> var\logs\selfheal.log 2>&1", 0, True
