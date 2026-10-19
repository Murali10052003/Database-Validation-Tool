[CmdletBinding()]
param(
    [string]$HostDataDir = $env:MV_HOST_DATA_DIR,
    [ValidateSet("Start", "Upgrade", "Stop", "Status", "Backup")]
    [string]$Action = "Start",
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [string]$Image = $env:MV_IMAGE,
    [string]$ImageTar,
    [string]$ComposeFile = (Join-Path $PSScriptRoot "docker-compose.yml"),
    [string[]]$Command
)

$ErrorActionPreference = "Stop"
if (-not $HostDataDir) {
    $localData = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not $localData) {
        throw "No local application-data folder was found. Specify -HostDataDir."
    }
    $HostDataDir = Join-Path $localData "MigrationValidator"
}
if ($HostDataDir -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
    throw "HostDataDir must be an absolute path on the Docker host."
}
$env:MV_HOST_DATA_DIR = [IO.Path]::GetFullPath($HostDataDir)
$env:MV_PORT = "$Port"
if ($Image) { $env:MV_IMAGE = $Image }
New-Item -ItemType Directory -Force -Path $HostDataDir | Out-Null
Write-Host "Persistent data: $env:MV_HOST_DATA_DIR"
$compose = @("compose", "--project-name", "migration-validator-desktop", "-f", $ComposeFile)
function Invoke-Compose {
    & docker @compose @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
}
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker failed with exit code $LASTEXITCODE" }
}
if ($ImageTar) {
    if ($Action -notin @("Start", "Upgrade") -or $Command) {
        throw "ImageTar supports only Start or Upgrade, without Command."
    }
    if (-not $Image) { throw "Supply -Image with the exact tag contained in the TAR." }
    if (-not (Test-Path -LiteralPath $ImageTar -PathType Leaf)) { throw "Image TAR not found: $ImageTar" }
    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) { throw "Compose file not found: $ComposeFile" }

    $engine = (Invoke-Docker info --format '{{json .}}') | ConvertFrom-Json
    if ($engine.OSType -ne "linux") { throw "Switch Docker Desktop to Linux containers." }
    $configuration = (Invoke-Compose config --format json) | ConvertFrom-Json
    $service = $configuration.services.'migration-validator'
    $mount = @($service.volumes | Where-Object { $_.target -eq "/app/data" })
    if ($mount.Count -ne 1 -or $mount[0].type -ne "bind" -or
        $mount[0].source.Replace('\', '/').TrimEnd('/') -ine $env:MV_HOST_DATA_DIR.Replace('\', '/').TrimEnd('/')) {
        throw "Compose must bind the requested HostDataDir to /app/data."
    }
    if ($service.image -ne $Image) { throw "Compose does not use the requested image tag." }
    $containers = @(Invoke-Compose ps --all --quiet migration-validator)
    if ($containers.Count -gt 1) { throw "Expected a single application container." }
    if ($Action -eq "Upgrade" -and $containers.Count -eq 0) {
        throw "Existing Compose installation not found. Verify the project and Compose file. Use Start for a first installation."
    }
    if ($Action -eq "Start" -and ($containers.Count -gt 0 -or
        (Test-Path -LiteralPath (Join-Path $HostDataDir "catalog.sqlite3")))) {
        throw "Existing installation or catalog found. Use Upgrade to back it up before replacement."
    }
    if ($containers.Count -eq 1) {
        $installed = @((Invoke-Docker inspect $containers[0]) | ConvertFrom-Json)[0]
        $installedMount = @($installed.Mounts | Where-Object { $_.Destination -eq "/app/data" })
        if ($installedMount.Count -ne 1 -or $installedMount[0].Type -ne "bind") {
            throw "Existing container does not use a supported bind mount. Contact the provider before upgrading."
        }
        $installedPath = $installedMount[0].Source.Replace('\', '/').TrimEnd('/')
        $requestedPath = $env:MV_HOST_DATA_DIR.Replace('\', '/').TrimEnd('/')
        $desktopPath = "/run/desktop/mnt/host/$($requestedPath.Substring(0, 1).ToLower())$($requestedPath.Substring(2))"
        if ($installedPath -ine $requestedPath -and $installedPath -ine $desktopPath) {
            throw "HostDataDir differs from the existing container mount ($installedPath). Supply the original -HostDataDir."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $HostDataDir "catalog.sqlite3") -PathType Leaf)) {
            throw "Existing catalog not found in HostDataDir. Contact the provider before upgrading."
        }
        Write-Host "Current image: $($installed.Config.Image)"
    }

    Write-Host "Loading image: $Image"
    $loaded = @(Invoke-Docker load --input $ImageTar)
    $loaded | ForEach-Object { Write-Host $_ }
    if ($loaded -notcontains "Loaded image: $Image") {
        throw "The TAR did not report the requested tag. Check -Image against docker load output."
    }
    $imageInfo = (Invoke-Docker image inspect $Image --format '{{json .}}') | ConvertFrom-Json
    $architecture = switch ($engine.Architecture) {
        "aarch64" { "arm64" }
        "x86_64" { "amd64" }
        default { $engine.Architecture }
    }
    if ($imageInfo.Os -ne "linux" -or $imageInfo.Architecture -ne $architecture) {
        throw "Image platform $($imageInfo.Os)/$($imageInfo.Architecture) does not match this Docker engine ($architecture)."
    }
    if ($Action -eq "Upgrade") {
        Write-Host "Wait for all validations to finish and ensure no other process writes to this data folder."
        if ((Read-Host "Type UPDATE to stop, back up, and replace the application") -cne "UPDATE") {
            throw "Update cancelled. The application was not stopped."
        }
        Invoke-Compose stop migration-validator
        $backup = "$($env:MV_HOST_DATA_DIR)-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        Copy-Item -LiteralPath $env:MV_HOST_DATA_DIR -Destination $backup -Recurse -ErrorAction Stop
        Copy-Item -LiteralPath $ComposeFile -Destination (Join-Path $backup "release-compose.yml") -ErrorAction Stop
        Write-Host "Full data backup: $backup"
        Write-Host "Keep the previous image ($($installed.Config.Image)) and its matching Compose file for recovery."
    }
    try {
        Invoke-Compose up -d --no-build --pull never --force-recreate --wait migration-validator
        Invoke-Compose ps
    }
    catch {
        Write-Warning "Startup failed. Preserve the data and backup; do not run an old image against a possibly upgraded catalog. Contact the provider."
        throw
    }
    Write-Host "Application: http://localhost:$Port"
    Write-Host "Refresh the browser, check saved history, test both connections, and run a small validation."
    return
}
if ($Command) {
    Invoke-Compose run --rm --no-deps migration-validator migration-validator @Command
    exit 0
}
switch ($Action) {
    "Stop" { Invoke-Compose down; exit 0 }
    "Status" { Invoke-Compose ps; exit 0 }
    "Backup" {
        Invoke-Compose exec -T migration-validator python -c "from app.core.catalog import Catalog; print(Catalog().backup())"
        exit 0
    }
    "Upgrade" {
        Invoke-Compose stop
        if (Test-Path (Join-Path $HostDataDir "catalog.sqlite3")) {
            Invoke-Compose run --rm --no-deps migration-validator python -c "from app.core.catalog import Catalog; print(Catalog().backup())"
        }
    }
}
if ($Image) { Invoke-Compose pull }
else { Invoke-Compose build }
Invoke-Compose up -d --no-build --wait
Write-Host "Application: http://localhost:$Port"