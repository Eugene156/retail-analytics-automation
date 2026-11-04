# Read-only prerequisites. No downloads, installs, account access or secret output.
$ErrorActionPreference = 'Continue'
$script:Failures = 0
function Invoke-Probe {
    param([string]$Label, [string]$Program, [string[]]$Arguments)
    Write-Output "`n$Label"
    if (-not (Get-Command $Program -ErrorAction SilentlyContinue)) {
        Write-Output "MISSING: $Program"
        $script:Failures += 1
        return
    }
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Output "FAILED: $Label"
        $script:Failures += 1
    }
}
Write-Output 'Retail Analytics Automation: read-only prerequisite check'
Write-Output ('UTC: ' + [DateTime]::UtcNow.ToString('o'))
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Write-Output ('OS: ' + $os.Caption + ' ' + $os.Version)
    Write-Output ('Architecture: ' + $os.OSArchitecture)
    Write-Output ('RAM GiB: ' + [Math]::Round(($os.TotalVisibleMemorySize / 1MB), 2))
    Write-Output ('Available RAM GiB: ' + [Math]::Round(($os.FreePhysicalMemory / 1MB), 2))
    $drive = (Get-Location).Drive
    if ($null -ne $drive -and $null -ne $drive.Free) {
        Write-Output ('Project drive free GiB: ' + [Math]::Round(($drive.Free / 1GB), 2))
    }
} catch {
    Write-Output 'Resource inspection unavailable; record OS/RAM/disk manually.'
}
Invoke-Probe -Label 'Git' -Program 'git' -Arguments @('--version')
Invoke-Probe -Label 'Docker client' -Program 'docker' -Arguments @('--version')
Invoke-Probe -Label 'Docker Compose' -Program 'docker' -Arguments @('compose', 'version')
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerOS = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or (($dockerOS | Out-String).Trim() -ne 'linux')) {
        Write-Output 'FAILED: Docker must be running and accessible with Linux containers.'
        $script:Failures += 1
    } else {
        Write-Output 'Docker daemon: available; container OS: linux'
    }
}
if (Get-Command wsl -ErrorAction SilentlyContinue) {
    Write-Output "`nWSL (informational)"
    & wsl --version
}
Write-Output ("`nBlocking prerequisite findings: " + $script:Failures)
Write-Output 'This does not verify G0 data, model, deployment, or resource adequacy.'
if ($script:Failures -gt 0) { exit 1 }
exit 0
