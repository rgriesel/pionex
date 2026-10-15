' Runs the local Paperclip server (http://127.0.0.1:3100) without a console window and restarts it
' 15 s after it exits for any reason (a crash, or Windows freezing it in Modern Standby). Output goes to
' ~\.paperclip\instances\default\logs\server-console.log (rotated at 50 MB). Started at logon by the
' "Paperclip" scheduled task; the "Cloudworks watchdog" task starts that task again if this script dies.
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
home = sh.ExpandEnvironmentStrings("%USERPROFILE%")
exe = sh.ExpandEnvironmentStrings("%APPDATA%") & "\npm\paperclipai.cmd"
logDir = home & "\.paperclip\instances\default\logs"
logf = logDir & "\server-console.log"
q = Chr(34)
sh.CurrentDirectory = home
Do
  If fs.FolderExists(logDir) Then
    If fs.FileExists(logf) Then
      If fs.GetFile(logf).Size > 52428800 Then
        If fs.FileExists(logf & ".old") Then fs.DeleteFile logf & ".old"
        fs.MoveFile logf, logf & ".old"
      End If
    End If
  End If
  sh.Run "cmd /c " & q & q & exe & q & " run >> " & q & logf & q & " 2>&1" & q, 0, True
  WScript.Sleep 15000
Loop
