# Registers the scheduled task "Regime watch" (CLO-45): pythonw -m pionex_lab regime-watch, started at logon, restarted
# every minute on failure, no time limit. It checks the market regime every 5 minutes on LIVE Pionex data and runs the
# hourly strategy-health pass (stop-only: it can write var/LIVE_STOP_<id>, never trade). Same shape as "Forward shadow".
$repo = "C:\Users\Desj Griesel\pionex"
$py = "C:\Users\Desj Griesel\AppData\Local\Programs\Python\Python312\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "-m pionex_lab regime-watch" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Regime watch" -Action $action -Trigger $trigger -Settings $settings `
    -Description "CLO-45 regime watch (5 min) + hourly strategy-health stop-only pass. Research/monitor only." -Force | Out-Null
Start-ScheduledTask -TaskName "Regime watch"
