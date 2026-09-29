# Pionex Lab one-line installer for Windows (paper trading only; no API keys, no real orders).
#
#   irm https://raw.githubusercontent.com/rgriesel/pionex/main/tools/install/windows.ps1 | iex
#
# What it does, in order:
#   1. Installs Python 3.12, Git and Node.js LTS with winget if they are missing.
#   2. Clones (or updates) https://github.com/rgriesel/pionex into %USERPROFILE%\pionex.
#   3. Runs init, verify and the Pionex capability probe.
#   4. Keeps the PC awake on mains power (sleep/hibernate "never").
#   5. Registers a per-user scheduled task "PionexLab" that starts the supervised runtime at logon
#      (collector + paper engine + dashboard + automatic daily research) and restarts it on failure.
#   6. Puts a "Pionex Lab Dashboard" shortcut on the desktop and opens the dashboard.
# Re-running it is safe: it updates the code and restarts the task.

& {
    $ErrorActionPreference = "Stop"
    $RepoUrl = "https://github.com/rgriesel/pionex.git"
    $Dir = Join-Path $env:USERPROFILE "pionex"
    $TaskName = "PionexLab"

    function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
    function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
    function Refresh-Path {
        $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $user = [Environment]::GetEnvironmentVariable("Path", "User")
        $env:Path = "$machine;$user"
    }
    function Install-Package($id) {
        if (-not (Have "winget")) {
            throw "winget is not available. Install 'App Installer' from the Microsoft Store, then run this again."
        }
        winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements | Out-Host
        Refresh-Path
    }
    function Python-Ok {
        if (-not (Have "py")) { return $false }
        $v = & py -3 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if (-not $v) { return $false }
        return ([version]$v -ge [version]"3.11")
    }

    Write-Host "Pionex Lab installer - paper trading only. No API keys are needed or used." -ForegroundColor Green

    Step "Checking Python 3.11+, Git and Node.js"
    if (-not (Python-Ok)) { Install-Package "Python.Python.3.12" }
    if (-not (Python-Ok)) { throw "Python 3.11+ is still not available. Open a new PowerShell window and run the installer again." }
    if (-not (Have "git")) { Install-Package "Git.Git" }
    if (-not (Have "git")) { throw "Git is still not available. Open a new PowerShell window and run the installer again." }
    if (-not (Have "node")) {
        try { Install-Package "OpenJS.NodeJS.LTS" } catch { Write-Warning "Node.js install failed; the built-in dry-run renderer will be used." }
    }

    Step "Getting the code into $Dir"
    if (Test-Path (Join-Path $Dir ".git")) {
        git -C $Dir pull --ff-only | Out-Host
    } else {
        git clone $RepoUrl $Dir | Out-Host
    }
    Set-Location $Dir

    if (Have "npm") {
        Step "Installing the pinned official Pionex CLI (dry-run previews only)"
        npm ci --prefix tools/pionex-cli --ignore-scripts --no-audit --no-fund | Out-Host
    }

    Step "Initialising and verifying"
    & py -3 -m pionex_lab init
    & py -3 -m pionex_lab verify
    if ($LASTEXITCODE -ne 0) { throw "Verification failed; not starting the runtime." }

    Step "Checking that this PC can reach the Pionex public API"
    & py -3 -m pionex_lab capability
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Some Pionex endpoints did not respond. The runtime will keep retrying and freeze entries until data is fresh."
    }

    Step "Keeping the PC awake on mains power"
    try {
        powercfg /change standby-timeout-ac 0 | Out-Null
        powercfg /change hibernate-timeout-ac 0 | Out-Null
    } catch { Write-Warning "Could not change sleep settings; set Sleep to 'Never' in Settings > System > Power." }

    Step "Registering the '$TaskName' task (starts at logon, restarts on failure)"
    $launcher = (Get-Command "pyw" -ErrorAction SilentlyContinue)
    if (-not $launcher) { $launcher = Get-Command "py" }
    $action = New-ScheduledTaskAction -Execute $launcher.Source -Argument "-3 -m pionex_lab run" -WorkingDirectory $Dir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Pionex Lab paper trading (simulated fills, no real orders)" -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName

    Step "Dashboard"
    $token = (Get-Content (Join-Path $Dir "var\dashboard.token") -Raw).Trim()
    $url = "http://127.0.0.1:8765/#token=$token"
    $shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Pionex Lab Dashboard.url"
    Set-Content -Path $shortcut -Value "[InternetShortcut]`r`nURL=$url" -Encoding ASCII
    Start-Sleep -Seconds 8
    Start-Process $url

    Write-Host ""
    Write-Host "Done. Pionex Lab is running in the background and starts again after every logon." -ForegroundColor Green
    Write-Host "Dashboard: the 'Pionex Lab Dashboard' shortcut on your desktop (this PC only)."
    Write-Host "Logs: $Dir\var\logs    Stop: Stop-ScheduledTask -TaskName $TaskName"
    Write-Host "Paper trading only: no exchange account is connected and no real orders are sent."
}
