param(
    [switch]$Demo,
    [switch]$Test,
    [switch]$OpenReport,
    [double]$Amount = 10000
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'

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
$InstalledDigest = if (Test-Path $Marker) { (Get-Content $Marker -Raw).Trim() } else { '' }
if ($Digest -ne $InstalledDigest) {
    & $VenvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access.' }
    Set-Content -Path $Marker -Value $Digest -Encoding ASCII
}

if ($Test) {
    & $VenvPython -m unittest discover -s (Join-Path $Root 'tests') -t $Root -v
    exit $LASTEXITCODE
}
$Arguments = @(
    (Join-Path $Root 'analyze_etfs.py'),
    '--amount', $Amount.ToString([System.Globalization.CultureInfo]::InvariantCulture)
)
$ReportDir = if ($Demo) { Join-Path $Root 'demo_reports' } else { Join-Path $Root 'reports' }
$Arguments += @('--output', $ReportDir)
if ($Demo) { $Arguments += '--demo' }
& $VenvPython @Arguments
$Result = $LASTEXITCODE
if ($Result -eq 0 -and $OpenReport) { Start-Process (Join-Path $ReportDir 'report.html') }
exit $Result
