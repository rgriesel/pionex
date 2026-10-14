' Starts the local Paperclip server (http://127.0.0.1:3100) without a console window and waits for it,
' so the "Paperclip" scheduled task stays running and Windows restarts it if it stops.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = sh.ExpandEnvironmentStrings("%USERPROFILE%")
WScript.Quit sh.Run("""" & sh.ExpandEnvironmentStrings("%APPDATA%") & "\npm\paperclipai.cmd"" run", 0, True)
