$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$BackupDir = Join-Path $Root "backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile -Encoding UTF8) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $index = $line.IndexOf('=')
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim().Trim('"')
        if ($key -in @("BACKUP_DIR", "BACKUP_KEEP_DAYS", "BACKUP_PASSPHRASE")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

if (-not $env:BACKUP_DIR) { $env:BACKUP_DIR = "backups" }
Set-Location $Root

$Bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $Bash)) { $Bash = "C:\Program Files\Git\usr\bin\bash.exe" }
if (-not (Test-Path $Bash)) { $Bash = (Get-Command bash).Source }

$log = Join-Path $BackupDir "backup.log"
"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====" | Out-File -FilePath $log -Append -Encoding UTF8
"root=$Root env_exists=$(Test-Path $EnvFile) pass_parsed=$([bool]$env:BACKUP_PASSPHRASE) bash=$Bash" | Out-File -FilePath $log -Append -Encoding UTF8
& $Bash -c "scripts/backup_docker.sh >> backups/backup.log 2>&1"
$code = $LASTEXITCODE

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls $BackupDir /inheritance:r /grant:r "${user}:(OI)(CI)F" | Out-Null
Get-ChildItem $BackupDir -File | ForEach-Object {
    icacls $_.FullName /inheritance:r /grant:r "${user}:(F)" | Out-Null
}

exit $code
