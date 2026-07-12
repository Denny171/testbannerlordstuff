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

function Start-GUI {
    $guiExe = Join-Path $ScriptDir "bridgegui.exe"
    $guiPy  = Join-Path $ScriptDir "bridgegui.py"

    if (Test-Path $guiExe) {
        try {
            $exeProc = Start-Process -FilePath $guiExe -WorkingDirectory $ScriptDir -PassThru -ErrorAction Stop
            Start-Sleep -Milliseconds 1200
            $exeProc.Refresh()
            if (-not $exeProc.HasExited) {
                return $true
            }
            Write-Host "  bridgegui.exe exited immediately (code $($exeProc.ExitCode)). Falling back to Python GUI..." -ForegroundColor Yellow
        } catch {
            Write-Host "  Failed to launch bridgegui.exe: $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    if (Test-Path $guiPy) {
        try {
            $pyCmd = Get-Command "python" -ErrorAction SilentlyContinue
            $pyExe = if ($pyCmd -and (Test-Path $pyCmd.Source)) { $pyCmd.Source } else { "python" }
            Start-Process -FilePath $pyExe -ArgumentList "`"$guiPy`"" -WorkingDirectory $ScriptDir -ErrorAction Stop | Out-Null
            return $true
        } catch {
            Write-Host "  Failed to launch bridgegui.py: $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    Write-Host "  GUI file not found (bridgegui.exe or bridgegui.py)." -ForegroundColor Yellow
    return $false
}

function Run-Installer {
    $guiExe = Join-Path $ScriptDir "bridgegui.exe"
    $guiPy  = Join-Path $ScriptDir "bridgegui.py"

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

    # Let user choose Ollama model only when config does not already specify one
    $existingCfg = Load-Config
    $defaultRouterModel = "qwen2.5:0.5b"
    $hasConfiguredRouterModel = $false
    if ($existingCfg -and -not [string]::IsNullOrWhiteSpace("$($existingCfg.router_model)")) {
        $defaultRouterModel = "$($existingCfg.router_model)".Trim()
        $hasConfiguredRouterModel = $true
    }

    if ($hasConfiguredRouterModel) {
        $selectedRouterModel = $defaultRouterModel
        Write-Host "  Using configured Ollama model from config.json: $selectedRouterModel" -ForegroundColor DarkGray
        Start-Sleep -Milliseconds 700
    } else {
        Clear-Host
        Draw-Banner
        Write-Host "  [3/$TOTAL]  Ollama model setup" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Enter the Ollama model to pull:" -ForegroundColor DarkGray
        Write-Host "  Press ENTER to use default: $defaultRouterModel" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  Model: " -NoNewline -ForegroundColor Cyan
        $userModelInput = Read-Host

        $selectedRouterModel = if ([string]::IsNullOrWhiteSpace($userModelInput)) {
            $defaultRouterModel
        } else {
            $userModelInput.Trim()
        }
    }

    # Pull model
    Set-Running 3 "Pulling $selectedRouterModel (may take a few minutes)..."
    Draw-InstallScreen

    & "$ollamaExe" pull $selectedRouterModel 2>&1 | ForEach-Object {
        $line  = "$_"
        $short = if ($line.Length -gt 60) { $line.Substring(0,60) + "..." } else { $line }
        Draw-InstallScreen $short
    }
    if ($LASTEXITCODE -ne 0) {
        Set-Err 3 "[E-OL-PULL] Model pull failed"
        Draw-InstallScreen
        Show-InstallError -Code "E-OL-PULL" `
            -Title "Ollama model pull failed" `
            -Detail "Model: $selectedRouterModel" `
            -Hint "Check model name and internet access, then rerun installer."
        Read-Host "  Press ENTER to exit"
        exit 1
    }

    Set-Done 3 "$selectedRouterModel ready"
    Draw-InstallScreen

    # --- STEP 4: Non-interactive configuration (Ollama model only) ---
    $existingCfg = Load-Config
    $modeVal = if ($existingCfg -and $existingCfg.mode) { "$($existingCfg.mode)" } else { "player2" }
    $baseUrlVal = if ($existingCfg -and $existingCfg.base_url) { "$($existingCfg.base_url)" } else { "http://127.0.0.1:4315/v1" }
    $apiKeyVal = if ($existingCfg -and $existingCfg.api_key) { "$($existingCfg.api_key)" } else { "" }
    $modelVal = if ($existingCfg -and $existingCfg.model) { "$($existingCfg.model)" } else { "" }
    $showInterceptsVal = if ($existingCfg -and ($null -ne $existingCfg.show_intercepts)) { [bool]$existingCfg.show_intercepts } else { $false }
    $inputCostVal = if ($existingCfg -and ($null -ne $existingCfg.input_token_cost_per_m)) { [double]$existingCfg.input_token_cost_per_m } else { 0.0 }
    $outputCostVal = if ($existingCfg -and ($null -ne $existingCfg.output_token_cost_per_m)) { [double]$existingCfg.output_token_cost_per_m } else { 0.0 }

    $cfg = [ordered]@{
        mode                  = $modeVal
        base_url              = $baseUrlVal
        api_key               = $apiKeyVal
        model                 = $modelVal
        router_model          = $selectedRouterModel
        show_intercepts       = $showInterceptsVal
        input_token_cost_per_m  = $inputCostVal
        output_token_cost_per_m = $outputCostVal
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

    Set-Done 4 "config.json saved (router: $selectedRouterModel)"
    Draw-InstallScreen

    # Success Screen
    Start-Sleep -Milliseconds 400
    Clear-Host
    Draw-Banner
    Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Green
    Write-Host "  |                                                               |" -ForegroundColor Green
    Write-Host "  |   OK   Installation complete!                                 |" -ForegroundColor Green
    Write-Host "  |        Setup is ready. Opening GUI...                         |" -ForegroundColor Green
    Write-Host "  |                                                               |" -ForegroundColor Green
    Write-Host "  +---------------------------------------------------------------+" -ForegroundColor Green
    Write-Host ""
    Start-Sleep -Milliseconds 500
    if (-not (Start-GUI)) {
        Read-Host "  Press ENTER to close"
        exit 1
    }
    exit 0
}

# ==============================================================
# MAIN ROUTING
# ==============================================================
Clear-Host
Draw-Banner
Write-Host "  What would you like to do?" -ForegroundColor Yellow
Write-Host ""
Write-Host "    [1]  Start GUI instantly" -ForegroundColor Green
Write-Host "    [2]  Run update / installer" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Your choice (default 1): " -NoNewline -ForegroundColor White
$startupChoice = Read-Host

if ($startupChoice -eq "2") {
    Run-Installer
} else {
    if (-not (Start-GUI)) {
        Write-Host "  GUI could not be launched. Running installer/update instead..." -ForegroundColor Yellow
        Start-Sleep -Milliseconds 900
        Run-Installer
    }
}
