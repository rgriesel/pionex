# Wave Lab one-line setup for Windows (read-only charting; no API keys, no orders).
#
#   irm https://raw.githubusercontent.com/rgriesel/pionex/main/tools/install/wavelab.ps1 | iex
#
# What it does, in order:
#   1. Installs Python 3.12 and Git with winget if they are missing.
#   2. Gets the code into %USERPROFILE%\pionex-waves, repairing a copy cloned to a literal "~"
#      folder or with Windows line endings (which fail the mandate hash check). That folder is a
#      dedicated copy: local edits to tracked files there are discarded.
#   3. Puts a "Wave Lab" shortcut on the desktop.
#   4. Starts Wave Lab in its own minimised window and opens http://127.0.0.1:8770/.
# Re-running it is safe: it updates the code and reopens the page.

& {
    $ErrorActionPreference = "Stop"
    $RepoUrl = "https://github.com/rgriesel/pionex.git"
    # Wave Lab lives on this branch until its pull request is merged; then main has it.
    $Branches = @("claude/local-website-clone-g570ed", "main")
    $Dir = Join-Path $env:USERPROFILE "pionex-waves"
    $Url = "http://127.0.0.1:8770/"

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
    function Run-Git([string[]]$GitArgs) {  # not "Git": a function would shadow git.exe
        & git -C $Dir @GitArgs | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed" }
    }
    function Branch-Exists($name) {
        try { & git ls-remote --exit-code --heads $RepoUrl $name *> $null } catch { return $false }
        return ($LASTEXITCODE -eq 0)
    }

    Write-Host "Wave Lab setup - read-only charts. No API keys are needed or used." -ForegroundColor Green

    Step "Checking Python 3.11+ and Git"
    if (-not (Python-Ok)) { Install-Package "Python.Python.3.12" }
    if (-not (Python-Ok)) { throw "Python 3.11+ is still not available. Open a new PowerShell window and run this again." }
    if (-not (Have "git")) { Install-Package "Git.Git" }
    if (-not (Have "git")) { throw "Git is still not available. Open a new PowerShell window and run this again." }

    $Branch = $Branches | Where-Object { Branch-Exists $_ } | Select-Object -First 1
    if (-not $Branch) { throw "Could not reach $RepoUrl. Check the internet connection and run this again." }

    Step "Getting the code into $Dir"
    # An earlier "git clone ... ~/pionex-waves" in PowerShell creates a folder literally named "~".
    $stray = Join-Path $env:USERPROFILE "~\pionex-waves"
    if ((Test-Path -LiteralPath $stray) -and -not (Test-Path -LiteralPath $Dir)) {
        Move-Item -LiteralPath $stray -Destination $Dir
        $tilde = Join-Path $env:USERPROFILE "~"
        if (-not (Get-ChildItem -LiteralPath $tilde -Force)) { Remove-Item -LiteralPath $tilde }
    }
    if (Test-Path -LiteralPath (Join-Path $Dir ".git")) {
        # Stop a running copy first so its files can be rewritten.
        Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe' OR Name='pyw.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -like "*pionex_lab waves*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Run-Git @("fetch", "--quiet", "origin", $Branch)
        Run-Git @("checkout", "--quiet", "-B", $Branch, "origin/$Branch")
        # Re-check out every file with the repository's line endings (see .gitattributes).
        Run-Git @("rm", "-r", "-q", "--cached", ".")
        Run-Git @("reset", "-q", "--hard", "origin/$Branch")
    } else {
        & git clone --quiet --branch $Branch $RepoUrl $Dir | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    }
    Set-Location $Dir

    Step "Checking the install"
    & py -3 -c "from pionex_lab.mandate import load_mandate, DEFAULT_CONFIG_DIR; load_mandate(DEFAULT_CONFIG_DIR)"
    if ($LASTEXITCODE -ne 0) { throw "The safety check failed (see the error above); Wave Lab was not started." }

    Step "Adding a 'Wave Lab' shortcut to the desktop"
    $py = (Get-Command "py").Source
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Wave Lab.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $py
    $sc.Arguments = "-3 -m pionex_lab waves --open"
    $sc.WorkingDirectory = $Dir
    $sc.WindowStyle = 7  # minimised
    $sc.Description = "Wave Lab: local Elliott Wave charts (read-only)"
    $sc.Save()

    Step "Starting Wave Lab"
    Start-Process -FilePath $py -ArgumentList "-3", "-m", "pionex_lab", "waves", "--open" `
        -WorkingDirectory $Dir -WindowStyle Minimized

    Write-Host ""
    Write-Host "Done. Wave Lab is opening at $Url" -ForegroundColor Green
    Write-Host "It runs in a minimised window; close that window to stop it."
    Write-Host "Next time, double-click the 'Wave Lab' shortcut on your desktop."
    Write-Host "Read-only analysis: wave counts are pattern hypotheses, not forecasts. No orders are placed."
}
