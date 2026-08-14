param(
    [switch]$Watch,
    [switch]$Check,
    [switch]$Quality,
    [switch]$Assemble,
    [string]$Brief = "",
    [string]$Plan = "",
    [switch]$ReuseTranscript,
    [switch]$AlsoResolve,
    [string]$Model = "medium",
    [switch]$Library,
    [switch]$LibraryIngest,
    [string]$Url = "",
    [string]$ItemId = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $Python = $venvPython
} else {
    $Python = "python"
}

$env:RESOLVE_SCRIPT_API = "$env:PROGRAMDATA\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$ScriptsDir = Join-Path $Root "scripts"
$env:PYTHONPATH = "$ScriptsDir;$env:RESOLVE_SCRIPT_API\Modules;$env:PYTHONPATH"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Python: $Python"
Write-Host "Root:   $Root"

if ($Check) {
    & $Python (Join-Path $Root "scripts\check_resolve.py")
    exit $LASTEXITCODE
}

if ($LibraryIngest) {
    if (-not $Url) { throw "Укажи -Url ссылку на YouTube" }
    $ingest = @((Join-Path $Root "scripts\library.py"), "ingest", "--url", $Url)
    if ($ItemId) { $ingest += @("--id", $ItemId) }
    & $Python @ingest
    exit $LASTEXITCODE
}

if ($Library) {
    & $Python (Join-Path $Root "scripts\library.py") "serve"
    exit $LASTEXITCODE
}

if ($Quality -or $Assemble) {
    if (-not $Brief) {
        $Brief = Join-Path $Root "templates\brief.narrative.example.json"
    }
    if ($Assemble) {
        $argsList = @(
            (Join-Path $Root "scripts\run_quality_edit.py"),
            "--stage", "assemble",
            "--brief", $Brief,
            "--overlap", "0"
        )
        if ($Plan) { $argsList += @("--plan", $Plan) }
        if ($AlsoResolve) { $argsList += "--also-resolve" }
        if ($PSBoundParameters.ContainsKey("OutName")) { }
        & $Python @argsList
        exit $LASTEXITCODE
    }

    $argsList = @(
        (Join-Path $Root "scripts\run_quality_edit.py"),
        "--stage", "transcribe",
        "--brief", $Brief,
        "--model", $Model
    )
    if ($ReuseTranscript) { $argsList += "--reuse-transcript" }
    & $Python @argsList
    exit $LASTEXITCODE
}

$argsList = @((Join-Path $Root "scripts\process_inbox.py"))
if ($Watch) {
    $argsList += "--watch"
}

& $Python @argsList
exit $LASTEXITCODE
