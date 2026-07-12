@# 2>nul & @echo off
# 2>nul & set "SCRIPT_DIR=%~dp0"
# 2>nul & powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression ((Get-Content -LiteralPath '%~f0' | Select-Object -Skip 4) -join [char]10)"
# 2>nul & exit /b

# ==============================================================
#  BRIDGE FOR AI INFLUENCE -- Installer & Launcher v1.0
#  Mount & Blade II: Bannerlord AI companion backend setup
# ==============================================================

# Disables Windows console QuickEdit mode to prevent console freezes
function Disable-QuickEdit {
    try {
        $Signature = @"
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr GetStdHandle(int nStdHandle);
        
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out int lpMode);
        
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool SetConsoleMode(IntPtr hConsoleHandle, int dwMode);
        
        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        public static extern IntPtr CreateFile(
            string lpFileName,
            int dwDesiredAccess,
            int dwShareMode,
            IntPtr lpSecurityAttributes,
            int dwCreationDisposition,
            int dwFlagsAndAttributes,
            IntPtr hTemplateFile
        );
"@
        $guid = [Guid]::NewGuid().ToString("n")
        $type = Add-Type -MemberDefinition $Signature -Name "ConsoleUtils_$guid" -PassThru -ErrorAction SilentlyContinue
        if ($type) {
            $hInput = $type::CreateFile("CONIN$", -1073741824, 3, [IntPtr]::Zero, 3, 0, [IntPtr]::Zero)
            if ($hInput -eq [IntPtr]::Zero -or $hInput -eq -1) {
                $hInput = $type::GetStdHandle(-10)
            }
            $mode = 0
            if ($type::GetConsoleMode($hInput, [ref]$mode)) {
                $newMode = ($mode -band -not 0x0040) -bor 0x0080
                $null = $type::SetConsoleMode($hInput, $newMode)
            }
        }
    } catch {}
}
Disable-QuickEdit

$ScriptDir  = $env:SCRIPT_DIR
if (-not $ScriptDir) { $ScriptDir = Get-Location }
$ConfigPath = Join-Path $ScriptDir "config.json"
$TokensPath = Join-Path $ScriptDir "tokens.json"
$LogPath    = Join-Path $ScriptDir "install_log.txt"

$Host.UI.RawUI.WindowTitle = "Bridge for AI Influence"
$TOTAL = 4

# ==============================================================
# LOGGING
# ==============================================================
function Write-Log {
    param($msg)
    try {
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $line = "[$ts] $msg`r`n"
        $stream = [System.IO.File]::Open(
            $LogPath,
            [System.IO.FileMode]::Append,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::ReadWrite
        )
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($line)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
    } catch {}
}

# ==============================================================
# SHARED RENDERING
# ==============================================================
function Draw-Banner {
    Write-Host ""
    Write-Host "  +===============================================================+" -ForegroundColor Cyan
    Write-Host "  |   [*]  BRIDGE FOR AI INFLUENCE -- Bannerlord AI Companion [*] |" -ForegroundColor Cyan
    Write-Host "  |                         CONTROL PANEL                         |" -ForegroundColor Cyan
    Write-Host "  +===============================================================+" -ForegroundColor Cyan
    Write-Host ""
}

# ==============================================================
# CONFIG & TOKEN LOAD/SAVE
# ==============================================================
function Load-Config {
    if (Test-Path $ConfigPath) {
        return Get-Content $ConfigPath -Encoding UTF8 | ConvertFrom-Json
    }
    return $null
}

function Save-Config($cfg) {
    $cfg | ConvertTo-Json | Out-File -FilePath $ConfigPath -Encoding UTF8
}

function Load-Tokens {
    if (Test-Path $TokensPath) {
        return Get-Content $TokensPath -Encoding UTF8 | ConvertFrom-Json
    }
    return [pscustomobject]@{ total_tokens = 0; session_tokens = 0; total_saved_tokens = 0; session_saved_tokens = 0 }
}

function Save-Tokens($t) {
    $t | ConvertTo-Json | Out-File -FilePath $TokensPath -Encoding UTF8
}

function Draw-ConfigBlock($cfg) {
    Write-Host "  Current backend configuration:" -ForegroundColor DarkGray
    Write-Host ""
    if ($cfg.mode -eq "player2") {
        Write-Host "    Backend   :  " -NoNewline -ForegroundColor DarkGray
        Write-Host "Player 2  (local)" -ForegroundColor Cyan
        Write-Host "    Endpoint  :  http://127.0.0.1:4315" -ForegroundColor DarkGray
        Write-Host "    Model     :  (managed by Player 2 app)" -ForegroundColor DarkGray
    } else {
        Write-Host "    Backend   :  " -NoNewline -ForegroundColor DarkGray
        Write-Host "OpenRouter  (cloud)" -ForegroundColor Magenta
        Write-Host "    Model     :  " -NoNewline -ForegroundColor DarkGray
        Write-Host $cfg.model -ForegroundColor Magenta
        $key    = "$($cfg.api_key)"
        $masked = if ($key.Length -gt 8) {
            $key.Substring(0,4) + "*****" + $key.Substring($key.Length - 4)
        } else { "*******" }
        Write-Host "    API Key   :  $masked" -ForegroundColor DarkGray
    }
    Write-Host ""
}

# ==============================================================
# ──────────────────────────────────────────────────────────────
#  PART 1 -- INSTALLER FLOW
# ──────────────────────────────────────────────────────────────
# ==============================================================

function Run-Installer {
    Write-Log "=== Installer started ==="
    $Steps = [System.Collections.Generic.List[hashtable]]::new()

    function Add-Step($idx, $label) {
        $Steps.Add(@{ Idx=$idx; Label=$label; State="pending"; Detail="" })
    }
    function Set-Running($idx, $d) {
        for ($i = 0; $i -lt $Steps.Count; $i++) {
            if ($Steps[$i]["Idx"] -eq $idx) {
                $Steps[$i]["State"]  = "running"
                $Steps[$i]["Detail"] = $d
                break
            }
        }
    }
    function Set-Done($idx, $d) {
        for ($i = 0; $i -lt $Steps.Count; $i++) {
            if ($Steps[$i]["Idx"] -eq $idx) {
                $Steps[$i]["State"]  = "done"
                $Steps[$i]["Detail"] = $d
                break
            }
        }
    }
    function Set-Err($idx, $d) {
        for ($i = 0; $i -lt $Steps.Count; $i++) {
            if ($Steps[$i]["Idx"] -eq $idx) {
                $Steps[$i]["State"]  = "error"
                $Steps[$i]["Detail"] = $d
                break
            }
        }
    }

    Add-Step 1 "Bridge Code & Python"
    Add-Step 2 "Python dependencies"
    Add-Step 3 "Ollama  (local AI router)"
    Add-Step 4 "Configuration"

    function Draw-InstallScreen($sub = "") {
        Clear-Host
        Draw-Banner
        foreach ($s in $Steps) {
            $label  = "  [{0}/{1}]  {2}" -f $s.Idx, $TOTAL, $s.Label
            $padded = $label.PadRight(46)
            switch ($s.State) {
                "done"    { Write-Host $padded -NoNewline -ForegroundColor White
                            Write-Host "OK   $($s.Detail)" -ForegroundColor Green }
                "error"   { Write-Host $padded -NoNewline -ForegroundColor White
                            Write-Host "ERR  $($s.Detail)" -ForegroundColor Red }
                "running" { Write-Host $padded -NoNewline -ForegroundColor Yellow
                            Write-Host "...  $($s.Detail)" -ForegroundColor Yellow }
                default   { Write-Host $padded -ForegroundColor DarkGray }
            }
        }
        if ($sub -ne "") {
            Write-Host ""
            Write-Host "      $sub" -ForegroundColor DarkGray
        }
        Write-Host ""
    }

    function Show-InstallError($Code, $Title, $Detail = "", $Hint = "") {
        Write-Host ""
        Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Red
        Write-Host "  |  INSTALLATION ERROR                                           |" -ForegroundColor Red
        Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Error code  :  " -NoNewline -ForegroundColor DarkGray
        Write-Host $Code -ForegroundColor Red
        Write-Host "  Description :  $Title" -ForegroundColor White
        Write-Host ""
        if ($Detail -ne "") {
            Write-Host "  Details:" -ForegroundColor DarkGray
            $words = $Detail -split " "
            $line  = "    "
            foreach ($w in $words) {
                if (($line + $w).Length -gt 68) {
                    Write-Host $line -ForegroundColor DarkGray
                    $line = "    $w "
                } else { $line += "$w " }
            }
            if ($line.Trim() -ne "") { Write-Host $line -ForegroundColor DarkGray }
            Write-Host ""
        }
        if ($Hint -ne "") {
            Write-Host "  How to fix  :  $Hint" -ForegroundColor Yellow
            Write-Host ""
        }
        Write-Host "  Full log saved to: install_log.txt" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host "  DKDI132  |  https://github.com/DKDI132/aiinfluence_bridge" -ForegroundColor DarkGray
        Write-Host "  Discord  |  dkdi2 (if any problems)" -ForegroundColor DarkGray
        Write-Host ""
    }

    # --- Find Python Helper ---
    function Find-Python {
        $cmdPy    = Get-Command "python" -ErrorAction SilentlyContinue
        $fromPath = if ($cmdPy) { $cmdPy.Source } else { $null }
        if ($fromPath -and (Test-Path $fromPath)) {
            try {
                $v = & "$fromPath" --version 2>&1
                if ($v -match "Python \d") { return $fromPath }
            } catch {}
        }
        $cmdLaunch  = Get-Command "py" -ErrorAction SilentlyContinue
        $pyLauncher = if ($cmdLaunch) { $cmdLaunch.Source } else { $null }
        if ($pyLauncher) {
            try {
                $loc = & py -c "import sys; print(sys.executable)" 2>&1
                if ($loc -and (Test-Path "$loc")) { return "$loc".Trim() }
            } catch {}
        }
        $candidates = @()
        foreach ($ver in @("313","312","311","310","39")) {
            $candidates += "$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe"
            $candidates += "$env:ProgramFiles\Python$ver\python.exe"
            $candidates += "${env:ProgramFiles(x86)}\Python$ver\python.exe"
        }
        $candidates += "$env:USERPROFILE\scoop\apps\python\current\python.exe"
        foreach ($p in $candidates) {
            if (Test-Path $p) {
                try {
                    $v = & "$p" --version 2>&1
                    if ($v -match "Python \d") { return $p }
                } catch {}
            }
        }
        return $null
    }

    # --- STEP 1A: Git Check & Install & Repo Sync ---
    Set-Running 1 "Checking for Git..."
    Draw-InstallScreen
    
    $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
    $gitOk  = $false
    
    if ($gitCmd) {
        $gitOk = $true
        Write-Log "Git is already installed: $($gitCmd.Source)"
    } else {
        Set-Running 1 "Installing Git via winget..."
        Draw-InstallScreen
        
        $wingetCmd = Get-Command "winget" -ErrorAction SilentlyContinue
        if ($wingetCmd) {
            $spin = @("|","/","-","\\"); $i = 0
            $job  = Start-Job -ScriptBlock {
                winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements 2>&1
            }
            while ($job.State -eq "Running") {
                Draw-InstallScreen "$($spin[$i % 4])  Installing Git via winget... (please wait)"
                $i++; Start-Sleep -Milliseconds 600
            }
            $wingetOut = Receive-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force
            
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","User")
            $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
            if ($gitCmd) { $gitOk = $true }
        }
        
        if (-not $gitOk) {
            $gitInst = "$env:TEMP\GitSetup_$PID.exe"
            $gitUrl  = "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
            
            Set-Running 1 "Downloading Git setup (~60 MB)..."
            Draw-InstallScreen
            Write-Log "Downloading Git from $gitUrl"
            try {
                $oldErrorAction = $ErrorActionPreference
                $ErrorActionPreference = "Stop"
                $ProgressPreference    = "SilentlyContinue"
                Invoke-WebRequest -Uri $gitUrl -OutFile $gitInst -UseBasicParsing
                $ProgressPreference    = "Continue"
                $ErrorActionPreference = $oldErrorAction
            } catch {
                Write-Log "Git download failed: $($_.Exception.Message)"
            }
            
            if (Test-Path $gitInst) {
                Set-Running 1 "Installing Git silently..."
                Draw-InstallScreen
                try {
                    $proc = Start-Process -FilePath $gitInst -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP-" -PassThru -Wait
                    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                                [System.Environment]::GetEnvironmentVariable("PATH","User")
                    $gitCmd = Get-Command "git" -ErrorAction SilentlyContinue
                    if ($gitCmd) { $gitOk = $true }
                } catch {
                    Write-Log "Git installer failed: $($_.Exception.Message)"
                }
                Remove-Item $gitInst -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # --- Sync code ---
    $repoUrl = "https://github.com/Denny171/testbannerlordstuff.git"
    $guiRawUrl = "https://github.com/Denny171/testbannerlordstuff/blob/main/bridgegui.py"
    $hasBackend = Test-Path (Join-Path $ScriptDir "backend.py")
    $hasGuiPy = Test-Path (Join-Path $ScriptDir "bridgegui.py")
    $hasGitUpdate = $false
    
    try {
        if ($gitOk) {
            Set-Running 1 "Syncing code from GitHub using Git..."
            Draw-InstallScreen
            
            # Force Git to run in 100% non-interactive mode.
            # This completely blocks terminal login prompts and GUI popup windows (Git Credential Manager).
            $env:GIT_TERMINAL_PROMPT = "0"
            $env:GCM_INTERACTIVE = "never"
            
            $gitRepoPath = Join-Path $ScriptDir ".git"
            $hashBefore = ""
            if (Test-Path $gitRepoPath) {
                $hashBefore = (& git rev-parse HEAD 2>$null)
                if ($hashBefore) { $hashBefore = $hashBefore.Trim() }
            }

            if (Test-Path $gitRepoPath) {
                Write-Log "Git repo exists. Running pull..."
                & git -c credential.helper= fetch --all 2>&1 | Out-Null
                & git reset --hard origin/main 2>&1 | Out-Null
            } else {
                Write-Log "Cloning codebase..."
                & git init 2>&1 | Out-Null
                & git -c credential.helper= remote add origin $repoUrl 2>&1 | Out-Null
                & git -c credential.helper= fetch --all 2>&1 | Out-Null
                & git reset --hard origin/main 2>&1 | Out-Null
            }
            Write-Log "Git sync complete."

            if ($hashBefore) {
                $hashAfter = (& git rev-parse HEAD 2>$null)
                if ($hashAfter) { $hashAfter = $hashAfter.Trim() }
                if ($hashBefore -ne $hashAfter) {
                    $hasGitUpdate = $true
                }
            }
        } elseif (-not ($hasBackend -and $hasGuiPy)) {
            # Fallback to ZIP download if git is missing and core files are incomplete.
            Set-Running 1 "Downloading codebase via ZIP archive..."
            Draw-InstallScreen
            Write-Log "Git missing. Fetching repository ZIP archive..."
            
            $zipPath = Join-Path $env:TEMP "aiinfluence_main.zip"
            $zipUrl  = "a"
            
            $oldErrorAction = $ErrorActionPreference
            $ErrorActionPreference = "Stop"
            $ProgressPreference    = "SilentlyContinue"
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
            $ProgressPreference    = "Continue"
            
            Expand-Archive -Path $zipPath -DestinationPath $ScriptDir -Force
            $subDir = Join-Path $ScriptDir "aiinfluence_bridge-main"
            if (Test-Path $subDir) {
                Copy-Item -Path "$subDir\*" -Destination $ScriptDir -Recurse -Force
                Remove-Item -Path $subDir -Recurse -Force
            }
            Remove-Item $zipPath -Force
            $ErrorActionPreference = $oldErrorAction
            Write-Log "ZIP download fallback completed."
        }

        $guiPyPath = Join-Path $ScriptDir "bridgegui.py"
        if (-not (Test-Path $guiPyPath)) {
            Write-Log "bridgegui.py missing after sync. Attempting direct fetch from GitHub raw..."
            try {
                Set-Running 1 "Fetching missing GUI file..."
                Draw-InstallScreen
                Invoke-WebRequest -Uri $guiRawUrl -OutFile $guiPyPath -UseBasicParsing
                if (Test-Path $guiPyPath) {
                    Write-Log "bridgegui.py downloaded successfully from raw URL."
                } else {
                    Write-Log "WARNING: bridgegui.py fetch returned without creating file."
                }
            } catch {
                Write-Log "WARNING: Could not fetch bridgegui.py directly: $($_.Exception.Message)"
            }
        }

        if ($hasGitUpdate) {
            Write-Log "New update detected. Restarting launcher after file sync checks..."
            Write-Host ""
            Write-Host "  [!] New update pulled from GitHub!" -ForegroundColor Green
            Write-Host "  [!] Restarting launcher to load new code..." -ForegroundColor Yellow
            Start-Sleep -Seconds 2

            # Start a new instance of the batch file in a new window
            Start-Process "$MyInvocation.MyCommand.Path"
            exit
        }
    } catch {
        Write-Log "Code sync warning: $($_.Exception.Message). Continuing setup..."
    }

    # --- STEP 1B: Python Check & Install ---
    Set-Running 1 "Checking for Python..."
    Draw-InstallScreen
    $pyExe = Find-Python

    if ($pyExe) {
        $pyVer = & "$pyExe" --version 2>&1
        Set-Done 1 "$($pyVer.ToString().Trim())"
        Draw-InstallScreen
    } else {
        Set-Running 1 "Installing Python via winget..."
        Draw-InstallScreen
        $wingetCmd = Get-Command "winget" -ErrorAction SilentlyContinue
        $wingetOk  = $false

        if ($wingetCmd) {
            $spin = @("|","/","-","\\"); $i = 0
            $job  = Start-Job -ScriptBlock {
                winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements 2>&1
            }
            while ($job.State -eq "Running") {
                Draw-InstallScreen "$($spin[$i % 4])  Installing Python via winget... (please wait)"
                $i++; Start-Sleep -Milliseconds 600
            }
            $wingetOut = Receive-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force

            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","User")
            $pyExe = Find-Python
            if ($pyExe) { $wingetOk = $true }
        }

        if (-not $wingetOk) {
            $installer = "$env:TEMP\python_ai_$PID.exe"
            $pyUrl     = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
            $minBytes  = 20MB

            Set-Running 1 "Downloading Python 3.12.4..."
            Draw-InstallScreen
            try {
                $oldErrorAction = $ErrorActionPreference
                $ErrorActionPreference = "Stop"
                $ProgressPreference    = "SilentlyContinue"
                Invoke-WebRequest -Uri $pyUrl -OutFile $installer -UseBasicParsing
                $ProgressPreference    = "Continue"
                $ErrorActionPreference = $oldErrorAction

                $fileSize = (Get-Item $installer).Length
                if ($fileSize -lt $minBytes) {
                    throw "File too small: $([math]::Round($fileSize/1KB,1)) KB"
                }
            } catch {
                Set-Err 1 "[E-PY-DL] Download failed"
                Draw-InstallScreen
                Show-InstallError -Code "E-PY-DL" `
                    -Title "Python download failed" `
                    -Detail "$($_.Exception.Message)" `
                    -Hint "Install Python manually from python.org, tick 'Add Python to PATH', then restart."
                Read-Host "  Press ENTER to exit"
                exit 1
            }

            Set-Running 1 "Installing Python 3.12.4..."
            Draw-InstallScreen
            try {
                $proc = Start-Process -FilePath $installer `
                    -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" `
                    -PassThru -Wait
                if ($proc.ExitCode -ne 0) { throw "Exit code $($proc.ExitCode)" }
                Remove-Item $installer -Force -ErrorAction SilentlyContinue
            } catch {
                Set-Err 1 "[E-PY-INS] Installer failed"
                Draw-InstallScreen
                Show-InstallError -Code "E-PY-INS" `
                    -Title "Python silent install failed" `
                    -Detail "$($_.Exception.Message)" `
                    -Hint "Run as Administrator, or install Python manually."
                Read-Host "  Press ENTER to exit"
                exit 1
            }

            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","User")
            $pyExe = Find-Python
        }

        if ($pyExe) {
            $pyVer = & "$pyExe" --version 2>&1
            Set-Done 1 "Installed -- $($pyVer.ToString().Trim())"
        } else {
            Set-Err 1 "[E-PY-NF] Not found after install"
            Draw-InstallScreen
            Show-InstallError -Code "E-PY-NF" `
                -Title "Python executable not found after installation" `
                -Hint "Reinstall Python manually from python.org and tick 'Add Python to PATH'."
            Read-Host "  Press ENTER to exit"
            exit 1
        }
        Draw-InstallScreen
    }

    # --- STEP 2: pip dependencies ---
    Set-Running 2 "pip install fastapi openai uvicorn..."
    Draw-InstallScreen
    Write-Log "pip using: $pyExe"

    $pipOutput = & "$pyExe" -m pip install fastapi openai uvicorn 2>&1
    $pipExit   = $LASTEXITCODE

    if ($pipExit -eq 0) {
        $importCheck = & "$pyExe" -c "import fastapi, openai, uvicorn; print('ok')" 2>&1
        if ("$importCheck" -match "ok") {
            Set-Done 2 "fastapi  openai  uvicorn"
        } else {
            Set-Err 2 "[E-PIP-PKG] Import check failed"
            Draw-InstallScreen
            Show-InstallError -Code "E-PIP-PKG" `
                -Title "Packages installed but import check failed" `
                -Detail "$importCheck" `
                -Hint "Try running as Administrator."
            Read-Host "  Press ENTER to exit"
            exit 1
        }
    } else {
        Set-Err 2 "[E-PIP-RUN] pip failed (exit $pipExit)"
        Draw-InstallScreen
        Show-InstallError -Code "E-PIP-RUN" `
            -Title "pip install failed" `
            -Detail (($pipOutput | Select-Object -Last 5) -join " | ") `
            -Hint "Check internet connection. If error says 'not found', re-run installer."
        Read-Host "  Press ENTER to exit"
        exit 1
    }
    Draw-InstallScreen

    # --- STEP 3: Ollama check & install ---
    function Test-Ollama {
        $cmd = Get-Command "ollama" -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        foreach ($p in @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:ProgramFiles\Ollama\ollama.exe"
        )) {
            if (Test-Path $p) { return $p }
        }
        return $null
    }

    Set-Running 3 "Checking for Ollama..."
    Draw-InstallScreen
    $ollamaExe = Test-Ollama

    if (-not $ollamaExe) {
        $ollamaInst = "$env:TEMP\OllamaSetup_$PID.exe"
        $ollamaUrl  = "https://ollama.com/download/OllamaSetup.exe"

        Set-Running 3 "Downloading Ollama (~1.4 GB, please wait)..."
        Draw-InstallScreen
        Write-Log "Downloading Ollama from $ollamaUrl"

        $dlJob = Start-Job -ScriptBlock {
            param($url, $out)
            $ProgressPreference = "SilentlyContinue"
            try {
                Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
                "OK"
            } catch {
                "ERR: $($_.Exception.Message)"
            }
        } -ArgumentList $ollamaUrl, $ollamaInst

        $spin = @("|","/","-","\\"); $sCount = 0
        while ($dlJob.State -eq "Running") {
            $sizeMB = ""
            if (Test-Path $ollamaInst) {
                $bytes = (Get-Item $ollamaInst -ErrorAction SilentlyContinue).Length
                if ($bytes -gt 0) {
                    $sizeMB = "{0:N0} MB downloaded" -f ($bytes / 1MB)
                }
            }
            Draw-InstallScreen "$($spin[$sCount % 4])  OllamaSetup.exe  $sizeMB"
            $sCount++; Start-Sleep -Milliseconds 400
        }
        $dlResult = Receive-Job $dlJob -ErrorAction SilentlyContinue
        Remove-Job $dlJob -Force

        if ($dlResult -notmatch "^OK") {
            Set-Err 3 "[E-OL-DL] Download failed"
            Draw-InstallScreen
            Show-InstallError -Code "E-OL-DL" `
                -Title "Ollama download failed" `
                -Detail "$dlResult" `
                -Hint "Download and install Ollama manually from ollama.com, then restart."
            Read-Host "  Press ENTER to exit"
            exit 1
        }

        $finalMB = [math]::Round((Get-Item $ollamaInst -ErrorAction SilentlyContinue).Length / 1MB, 0)
        Set-Running 3 "Installing Ollama ($finalMB MB)..."
        Draw-InstallScreen

        try {
            $proc = Start-Process -FilePath $ollamaInst -ArgumentList "/VERYSILENT /NORESTART" -PassThru -ErrorAction Stop
            $spin2 = @("|","/","-","\\"); $j = 0
            while (-not $proc.HasExited) {
                Draw-InstallScreen "$($spin2[$j % 4])  Installing Ollama... (please wait)"
                $j++; Start-Sleep -Milliseconds 500
            }
        } catch {
            Set-Err 3 "[E-OL-INS] Installer failed"
            Draw-InstallScreen
            Show-InstallError -Code "E-OL-INS" `
                -Title "Ollama installation failed" `
                -Detail "$($_.Exception.Message)" `
                -Hint "Run as Administrator or install manually from ollama.com."
            Read-Host "  Press ENTER to exit"
            exit 1
        }
        Remove-Item $ollamaInst -Force -ErrorAction SilentlyContinue

        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        $ollamaExe = Test-Ollama

        if (-not $ollamaExe) {
            Set-Err 3 "[E-OL-NF] Not found after install"
            Draw-InstallScreen
            Show-InstallError -Code "E-OL-NF" `
                -Title "ollama.exe not found after installer finished" `
                -Hint "Install Ollama manually from ollama.com."
            Read-Host "  Press ENTER to exit"
            exit 1
        }
    }

    # Start Ollama service before pull
    Set-Running 3 "Starting Ollama service..."
    Draw-InstallScreen
    $null = Start-Process -FilePath "$ollamaExe" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Pull model
    Set-Running 3 "Pulling qwen2.5:0.5b (may take a few minutes)..."
    Draw-InstallScreen

    & "$ollamaExe" pull qwen2.5:0.5b 2>&1 | ForEach-Object {
        $line  = "$_"
        $short = if ($line.Length -gt 60) { $line.Substring(0,60) + "..." } else { $line }
        Draw-InstallScreen $short
    }
    Set-Done 3 "qwen2.5:0.5b ready"
    Draw-InstallScreen

    # --- STEP 4: Configuration Prompt ---
    function Draw-ConfigPrompt {
        Clear-Host
        Draw-Banner
        foreach ($s in ($Steps | Where-Object { $_.Idx -le 3 })) {
            Write-Host ("  [{0}/{1}]  {2}" -f $s.Idx, $TOTAL, $s.Label).PadRight(46) -NoNewline -ForegroundColor White
            Write-Host "OK   $($s.Detail)" -ForegroundColor Green
        }
        Write-Host ""
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  [4/$TOTAL]  Choose your AI backend:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "      [1]  Player 2    (local -- http://127.0.0.1:4315)" -ForegroundColor Cyan
        Write-Host "      [2]  OpenRouter  (cloud API)" -ForegroundColor Magenta
        Write-Host ""
        Write-Host "  Your choice: " -NoNewline -ForegroundColor White
    }

    Draw-ConfigPrompt
    $backendChoice = Read-Host

    if ($backendChoice -eq "2") {
        Clear-Host
        Draw-Banner
        Write-Host "  [4/$TOTAL]  OpenRouter Configuration" -ForegroundColor Magenta
        Write-Host ""
        Write-Host "  Model name (e.g. openai/gpt-4o-mini):" -ForegroundColor Cyan
        Write-Host "  > " -NoNewline -ForegroundColor Cyan
        $orModel = Read-Host
        Write-Host ""
        Write-Host "  API key:" -ForegroundColor Cyan
        Write-Host "  > " -NoNewline -ForegroundColor Cyan
        $orKey = Read-Host
        $cfg = [ordered]@{
            mode     = "openrouter"
            base_url = "https://openrouter.ai/api/v1"
            api_key  = $orKey.Trim()
            model    = $orModel.Trim()
        }
    } else {
        $cfg = [ordered]@{
            mode     = "player2"
            base_url = "http://127.0.0.1:4315/v1"
            api_key  = ""
            model    = ""
        }
    }

    try {
        $cfg | ConvertTo-Json | Out-File -FilePath $ConfigPath -Encoding UTF8
    } catch {
        Show-InstallError -Code "E-CFG-WR" `
            -Title "Cannot write config.json" `
            -Detail "$($_.Exception.Message)" `
            -Hint "Make sure folder is write-accessible."
        Read-Host "  Press ENTER to exit"
        exit 1
    }

    if (-not (Test-Path $TokensPath)) {
        try {
            [ordered]@{ total_tokens = 0; session_tokens = 0; total_saved_tokens = 0; session_saved_tokens = 0 } | ConvertTo-Json |
                Out-File -FilePath $TokensPath -Encoding UTF8
        } catch {}
    }

    Set-Done 4 "config.json saved (mode: $($cfg.mode))"
    Draw-InstallScreen

    # Success Screen
    Start-Sleep -Milliseconds 400
    Clear-Host
    Draw-Banner
    Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Green
    Write-Host "  |                                                               |" -ForegroundColor Green
    Write-Host "  |   OK   Installation complete!                                 |" -ForegroundColor Green
    Write-Host "  |        Setup is ready. Let's start the bridge!                |" -ForegroundColor Green
    Write-Host "  |                                                               |" -ForegroundColor Green
    Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Press ENTER to start the Launcher Dashboard..."
    Read-Host
}

# ==============================================================
# ──────────────────────────────────────────────────────────────
#  PART 2 -- LAUNCHER FLOW
# ──────────────────────────────────────────────────────────────
# ==============================================================

function Run-Launcher {
    $cfg = Load-Config

    # Reset session tokens for this run
    $tok = Load-Tokens
    $tok.session_tokens = 0
    $tok.session_saved_tokens = 0
    Save-Tokens $tok

    # Menu choices
    function Draw-Menu($c) {
        Clear-Host
        Draw-Banner
        Draw-ConfigBlock $c
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  Change settings or run update?" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "    [1]  Change model only" -ForegroundColor White
        Write-Host "    [2]  Change API key only" -ForegroundColor White
        Write-Host "    [3]  Change both (model + API key)" -ForegroundColor White
        Write-Host "    [4]  Switch backend  (Player 2  <->  OpenRouter)" -ForegroundColor White
        Write-Host "    [5]  No changes -- start GUI now" -ForegroundColor Green
        Write-Host "    [6]  Run Installer / Update from GitHub" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Your choice: " -NoNewline -ForegroundColor White
    }

    Draw-Menu $cfg
    $choice = Read-Host

    switch ($choice) {
        "1" {
            Clear-Host; Draw-Banner; Draw-ConfigBlock $cfg
            Write-Host "  New model name:" -ForegroundColor Cyan
            Write-Host "  > " -NoNewline -ForegroundColor Cyan
            $v = Read-Host
            if ($v.Trim() -ne "") { $cfg.model = $v.Trim(); Save-Config $cfg }
        }
        "2" {
            Clear-Host; Draw-Banner; Draw-ConfigBlock $cfg
            Write-Host "  New API key:" -ForegroundColor Cyan
            Write-Host "  > " -NoNewline -ForegroundColor Cyan
            $v = Read-Host
            if ($v.Trim() -ne "") { $cfg.api_key = $v.Trim(); Save-Config $cfg }
        }
        "3" {
            Clear-Host; Draw-Banner; Draw-ConfigBlock $cfg
            Write-Host "  New model name:" -ForegroundColor Cyan
            Write-Host "  > " -NoNewline -ForegroundColor Cyan
            $m = Read-Host
            Write-Host ""
            Write-Host "  New API key:" -ForegroundColor Cyan
            Write-Host "  > " -NoNewline -ForegroundColor Cyan
            $k = Read-Host
            if ($m.Trim() -ne "") { $cfg.model = $m.Trim() }
            if ($k.Trim() -ne "") { $cfg.api_key = $k.Trim() }
            Save-Config $cfg
        }
        "4" {
            Clear-Host; Draw-Banner
            if ($cfg.mode -eq "player2") {
                Write-Host "  Switching to OpenRouter." -ForegroundColor Magenta
                Write-Host ""
                Write-Host "  Model name (e.g. openai/gpt-4o-mini):" -ForegroundColor Cyan
                Write-Host "  > " -NoNewline -ForegroundColor Cyan
                $m = Read-Host
                Write-Host ""
                Write-Host "  API key:" -ForegroundColor Cyan
                Write-Host "  > " -NoNewline -ForegroundColor Cyan
                $k = Read-Host
                $cfg.mode     = "openrouter"
                $cfg.base_url = "https://openrouter.ai/api/v1"
                $cfg.model    = $m.Trim()
                $cfg.api_key  = $k.Trim()
            } else {
                Write-Host "  Switching to Player 2 (local)." -ForegroundColor Cyan
                $cfg.mode     = "player2"
                $cfg.base_url = "http://127.0.0.1:4315/v1"
                $cfg.model    = ""
                $cfg.api_key  = ""
            }
            Save-Config $cfg
        }
        "6" {
            # Run installer manually (will trigger Github sync/re-installation)
            Run-Installer
        }
    }

    # Reload fresh configs
    $cfg = Load-Config

    function Draw-Dashboard($cfg, $status) {
        Clear-Host
        Draw-Banner
        Draw-ConfigBlock $cfg
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host ""
        
        Write-Host "  [*] " -NoNewline -ForegroundColor Yellow
        Write-Host "Have a great game, commander! " -NoNewline -ForegroundColor Cyan
        Write-Host "May your kingdom stand strong!" -ForegroundColor DarkCyan
        Write-Host ""
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host ""

        Write-Host "  Status:      " -NoNewline -ForegroundColor DarkGray
        if ($status -eq "ACTIVE") {
            Write-Host "ACTIVE" -ForegroundColor Green
        } else {
            Write-Host "INACTIVE (Stopped)" -ForegroundColor Red
        }
        Write-Host ""

        # Token stats & Money saved (GPT-4 Classic pricing scale: $30 per 1M tokens = $0.00003 per token)
        $tok = Load-Tokens
        $totalSavedTokens = if ($tok.total_saved_tokens) { $tok.total_saved_tokens } else { 0 }
        $sessionSavedTokens = if ($tok.session_saved_tokens) { $tok.session_saved_tokens } else { 0 }
        $totalTokens = if ($tok.total_tokens) { $tok.total_tokens } else { 0 }
        $sessionTokens = if ($tok.session_tokens) { $tok.session_tokens } else { 0 }

        $totalSavedTokensFmt = "{0:N0}" -f [long]$totalSavedTokens
        $sessionSavedTokensFmt = "{0:N0}" -f [long]$sessionSavedTokens
        $totalTokensFmt   = "{0:N0}" -f [long]$totalTokens
        $sessionTokensFmt = "{0:N0}" -f [long]$sessionTokens
        
        $totalSavedCost      = [double]$totalSavedTokens * 0.00003
        $sessionSavedCost    = [double]$sessionSavedTokens * 0.00003
        $totalCost           = [double]$totalTokens * 0.00003
        $sessionCost         = [double]$sessionTokens * 0.00003
        
        $totalSavedCostFmt   = "{0:N4}" -f $totalSavedCost
        $sessionSavedCostFmt = "{0:N4}" -f $sessionSavedCost
        $totalCostFmt        = "{0:N4}" -f $totalCost
        $sessionCostFmt      = "{0:N4}" -f $sessionCost

        Write-Host "  [>] SAVED in your entire career:                  " -NoNewline -ForegroundColor DarkGray
        Write-Host "$totalSavedTokensFmt tokens " -NoNewline -ForegroundColor Magenta
        Write-Host "worth " -NoNewline -ForegroundColor DarkGray
        Write-Host "`$$totalSavedCostFmt " -NoNewline -ForegroundColor Green
        Write-Host "(GPT-4 classic scale)" -ForegroundColor DarkGray

        Write-Host "  [>] SAVED in this session only:                   " -NoNewline -ForegroundColor DarkGray
        Write-Host "$sessionSavedTokensFmt tokens " -NoNewline -ForegroundColor Magenta
        Write-Host "worth " -NoNewline -ForegroundColor DarkGray
        Write-Host "`$$sessionSavedCostFmt" -ForegroundColor Green
        Write-Host ""
        
        Write-Host "  [>] Sent to API in total (career/session):        " -NoNewline -ForegroundColor DarkGray
        Write-Host "$totalTokensFmt / $sessionTokensFmt tokens " -NoNewline -ForegroundColor DarkGray
        Write-Host "costing " -NoNewline -ForegroundColor DarkGray
        Write-Host "`$$totalCostFmt / `$$sessionCostFmt" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host ""

        # Footer
        Write-Host "  DKDI132  |  z" -ForegroundColor DarkGray
        Write-Host "  Discord  |  dkdi2 (if any problems)" -ForegroundColor DarkGray
        Write-Host ""
    }

    # Find python path dynamically
    function Find-Python-Launcher {
        $cmdPy    = Get-Command "python" -ErrorAction SilentlyContinue
        $fromPath = if ($cmdPy) { $cmdPy.Source } else { $null }
        if ($fromPath -and (Test-Path $fromPath)) { return $fromPath }
        $candidates = @()
        foreach ($ver in @("313","312","311","310","39")) {
            $candidates += "$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe"
            $candidates += "$env:ProgramFiles\Python$ver\python.exe"
        }
        foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
        return "python"
    }

    $pyExe = Find-Python-Launcher
    $StdoutPath = Join-Path $ScriptDir "backend_stdout.log"
    $StderrPath = Join-Path $ScriptDir "backend_stderr.log"

    Remove-Item $StdoutPath -Force -ErrorAction SilentlyContinue
    Remove-Item $StderrPath -Force -ErrorAction SilentlyContinue

    Write-Host "  Starting backend in the background..." -ForegroundColor Yellow
    Start-Sleep -Milliseconds 500

    $backendProc = $null
    try {
        $backendProc = Start-Process -FilePath $pyExe -ArgumentList "`"$ScriptDir\backend.py`"" `
            -NoNewWindow -PassThru -ErrorAction Stop `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath
    } catch {
        Write-Host "  Failed to start backend: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Make sure Python is installed and backend.py exists." -ForegroundColor Yellow
        Write-Host ""
        Read-Host "  Press ENTER to close"
        exit 1
    }

    $lastTotal = -1
    $lastSession = -1
    $lastStatus = ""

    while ($backendProc -and -not $backendProc.HasExited) {
        $status = "ACTIVE"
        $tok = Load-Tokens

        # Check if new thoughts are available
        $thoughtsPath = Join-Path $ScriptDir "thoughts.txt"
        if (Test-Path $thoughtsPath) {
            try {
                $thoughts = Get-Content -Path $thoughtsPath -Raw -ErrorAction SilentlyContinue
                if ($thoughts -and $thoughts.Trim() -ne "") {
                    # Show thoughts overlay
                    Clear-Host
                    Draw-Banner
                    Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
                    Write-Host "  [!] THE COMPANION'S INTERNAL THOUGHTS:" -ForegroundColor Yellow
                    Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
                    Write-Host ""
                    
                    # Word wrap thoughts for clean console output
                    $words = $thoughts -split " "
                    $line  = "  "
                    foreach ($w in $words) {
                        if (($line + $w).Length -gt 68) {
                            Write-Host $line -ForegroundColor Cyan
                            $line = "  $w "
                        } else { $line += "$w " }
                    }
                    if ($line.Trim() -ne "") { Write-Host $line -ForegroundColor Cyan }
                    
                    Write-Host ""
                    Write-Host "  -----------------------------------------------------------------" -ForegroundColor DarkGray
                    Write-Host "  Returning to overlay in 15 seconds..." -ForegroundColor DarkGray
                    Write-Host ""

                    # Wait and then clean up
                    Start-Sleep -Seconds 15
                    Remove-Item $thoughtsPath -Force -ErrorAction SilentlyContinue
                    # Force redraw of dashboard
                    Draw-Dashboard $cfg $status
                    $lastTotal = $tok.total_tokens
                    $lastSession = $tok.session_tokens
                    $lastStatus = $status
                }
            } catch {}
        }
        
        if ($tok.total_tokens -ne $lastTotal -or $tok.session_tokens -ne $lastSession -or $status -ne $lastStatus) {
            Draw-Dashboard $cfg $status
            $lastTotal = $tok.total_tokens
            $lastSession = $tok.session_tokens
            $lastStatus = $status
        }
        Start-Sleep -Seconds 1
    }

    $status = "INACTIVE"
    Draw-Dashboard $cfg $status

    Write-Host "  Backend stopped." -ForegroundColor Yellow
    Write-Host "  Check backend_stderr.log for details if it crashed." -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "  Press ENTER to close"
}

# ==============================================================
# MAIN ROUTING
# ==============================================================
$cfg = Load-Config
if ($cfg -eq $null -or -not (Test-Path (Join-Path $ScriptDir "backend.py"))) {
    Run-Installer
    # Run Launcher immediately after successful installation
    Run-Launcher
} else {
    Run-Launcher
}
