# Cloudworks watchdog: every 5 minutes (task "Cloudworks watchdog"), make sure Paperclip, Wave Lab and the
# Wave Lab alerts, the Shadow grid and the Forward shadow books are running; restart what is down and tell the owner (critical Telegram, once a day per
# service). Read-only otherwise. Log: var\logs\watchdog.log
$repo = "C:\Users\Desj Griesel\pionex"
$log = "$repo\var\logs\watchdog.log"
$state = "$repo\var\watchdog_state.json"
function Log($m) { Add-Content -Path $log -Value "$(Get-Date -Format s) $m" -Encoding utf8 }
function Listening($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function Notify($key, $text) {
    Push-Location $repo
    try { & py -m pionex_lab notify --level critical --key "$key-$(Get-Date -Format yyyy-MM-dd)" $text | Out-Null } catch {}
    Pop-Location
}
$st = @{}
if (Test-Path $state) { try { (Get-Content $state -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $st[$_.Name] = [int]$_.Value } } catch {} }

function Check($name, $task, $healthy, $kill, $limit = 3) {
    if (& $healthy) { $st[$name] = 0; return }
    $st[$name] = 1 + [int]$st[$name]
    $t = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if ($null -eq $t) { Log "$name down and task $task missing"; return }
    if ($t.State -ne 'Running') {
        Start-ScheduledTask -TaskName $task; Log "$name down (task $($t.State)): started $task"
        Notify "watchdog-$name" "Watchdog: $name was down and has been restarted."
    } elseif ($st[$name] -ge $limit) {
        Log "$name unhealthy for $limit checks while $task runs: restarting"
        Stop-ScheduledTask -TaskName $task; & $kill; Start-Sleep -Seconds 5; Start-ScheduledTask -TaskName $task
        Notify "watchdog-$name" "Watchdog: $name was stuck for $(5 * $limit) minutes and has been restarted."
        $st[$name] = 0
    }
}

Check "Paperclip" "Paperclip" {
    try { (Invoke-RestMethod -Uri http://127.0.0.1:3100/api/health -TimeoutSec 20).status -eq 'ok' } catch { $false }
} { Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -match 'paperclipai' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } } 5   # startup after a crash can take ~10 min
Check "WaveLab" "WaveLab" { Listening 8770 } {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'pionex_lab waves' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }
Check "WaveLabAlerts" "WaveLab Alerts" {
    [bool](Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'wave-alerts' }) } {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'wave-alerts' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }

Check "ShadowGrid" "Shadow grid" {
    [bool](Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'shadow-grid' }) } {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'shadow-grid' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }

Check "ForwardShadow" "Forward shadow" {
    [bool](Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'forward-shadow' }) } {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'forward-shadow' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }

$st | ConvertTo-Json | Set-Content -Path $state -Encoding utf8
