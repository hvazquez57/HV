param(
    [switch]$Demo,
    [switch]$Test,
    [switch]$OpenReport,
    [double]$Amount = 10000,
    [string]$Cached,
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if ($Demo -and $Cached) { throw '-Demo and -Cached are mutually exclusive.' }

if (-not (Test-Path $VenvPython)) {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
    )
    $Python = $null
    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) { $Python = $Candidate; break }
    }
    if (-not $Python) {
        $Command = Get-Command python -ErrorAction SilentlyContinue
        if ($Command -and $Command.Source -notlike '*\WindowsApps\*') {
            $Python = $Command.Source
        }
    }
    if (-not $Python) {
        throw 'Python 3.10+ is required. Install from python.org or run: winget install --id Python.Python.3.13 --exact --scope user'
    }
    & $Python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

$Requirements = Join-Path $Root 'requirements.txt'
$Marker = Join-Path $Root '.venv\requirements.sha256'
$Digest = (Get-FileHash $Requirements -Algorithm SHA256).Hash
$Constraints = Join-Path $Root 'constraints-windows-py313.txt'
$PythonInfoJson = & $VenvPython -c "import json,platform,struct,sys; print(json.dumps({'series': str(sys.version_info.major) + '.' + str(sys.version_info.minor), 'machine': platform.machine(), 'bits': struct.calcsize('P') * 8}))"
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the virtual environment Python version.' }
$PythonInfo = $PythonInfoJson | ConvertFrom-Json
$ConstraintArguments = @()
if ($PythonInfo.series -eq '3.13' -and $PythonInfo.bits -eq 64 -and
    $PythonInfo.machine -in @('AMD64', 'x86_64')) {
    $ConstraintArguments = @('-c', $Constraints)
    $Digest += (Get-FileHash $Constraints -Algorithm SHA256).Hash
}
$Digest += $PythonInfoJson.Trim()
$InstalledDigest = if (Test-Path $Marker) { (Get-Content $Marker -Raw).Trim() } else { '' }
if ($Digest -ne $InstalledDigest) {
    & $VenvPython -m pip install -r $Requirements @ConstraintArguments
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access.' }
    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
    Set-Content -Path $Marker -Value $Digest -Encoding ASCII
}

if ($Test) {
    & $VenvPython -W error::DeprecationWarning -m unittest discover -s (Join-Path $Root 'tests') -t $Root -v
    exit $LASTEXITCODE
}
$Arguments = @((Join-Path $Root 'analyze_etfs.py'))
if (-not $Cached -or $PSBoundParameters.ContainsKey('Amount')) {
    $Arguments += @('--amount', $Amount.ToString([System.Globalization.CultureInfo]::InvariantCulture))
}
$ReportDir = if ($Cached) {
    Join-Path $Root 'cached_reports'
} elseif ($Demo) {
    Join-Path $Root 'demo_reports'
} else {
    Join-Path $Root 'reports'
}
if ($Output) { $ReportDir = [System.IO.Path]::GetFullPath($Output) }
$Arguments += @('--output', $ReportDir)
if ($Demo) { $Arguments += '--demo' }
if ($Cached) { $Arguments += @('--cached', $Cached) }
$StartedUtc = [DateTime]::UtcNow
& $VenvPython @Arguments
$Result = $LASTEXITCODE
if ($Result -eq 0 -and $OpenReport) {
    $LatestFile = Join-Path $ReportDir 'latest.json'
    if (-not (Test-Path $LatestFile) -or (Get-Item $LatestFile).LastWriteTimeUtc -lt $StartedUtc) {
        throw 'No new successful report pointer was published; refusing to open an old report.'
    }
    $Latest = Get-Content $LatestFile -Raw | ConvertFrom-Json
    $ReportPath = [System.IO.Path]::GetFullPath((Join-Path $ReportDir $Latest.report))
    $ExpectedRoot = [System.IO.Path]::GetFullPath($ReportDir).TrimEnd('\') + '\'
    if (-not $ReportPath.StartsWith($ExpectedRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path $ReportPath -PathType Leaf)) {
        throw 'The successful report pointer does not resolve inside the output directory.'
    }
    Start-Process $ReportPath
}
exit $Result
