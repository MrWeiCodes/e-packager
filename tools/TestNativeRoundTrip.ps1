param(
    [Parameter(Mandatory = $true)]
    [string[]]$InputFiles,
    [string]$OutputRoot = "$PSScriptRoot/../temp/native-roundtrip-$([guid]::NewGuid().ToString('N'))",
    [string]$BinRoot = "$PSScriptRoot/../bin"
)

$ErrorActionPreference = 'Stop'
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "Output directory already exists: $OutputRoot" }
[IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$results = @()
$index = 0
foreach ($inputFile in $InputFiles) {
    $source = Get-Item -LiteralPath $inputFile
    if ($source.Length -eq 0) { continue }
    $originalHash = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash
    $index++
    $caseRoot = Join-Path $OutputRoot $index
    [IO.Directory]::CreateDirectory($caseRoot) | Out-Null
    $copy = Join-Path $caseRoot $source.Name
    Copy-Item -LiteralPath $source.FullName -Destination $copy
    foreach ($arch in @('Win32', 'x64')) {
        $tool = Join-Path $BinRoot "$arch/Release/e-packager.exe"
        $workspace = Join-Path $caseRoot $arch
        $output = Join-Path $caseRoot ($arch + $source.Extension)
        # Windows PowerShell 会将原生 stderr 转为 ErrorRecord；版本提示不代表失败。
        $previousErrorAction = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $log = & $tool verify-roundtrip $copy $workspace $output 2>&1 | Out-String
            $verifyExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorAction
        }
        $log | Set-Content -LiteralPath (Join-Path $caseRoot "$arch.log") -Encoding utf8
        $exists = Test-Path -LiteralPath $output
        $bytesEqual = $false
        $md5Equal = $false
        if ($exists) {
            & "$env:SystemRoot/System32/fc.exe" /b $copy $output > $null
            $bytesEqual = $LASTEXITCODE -eq 0
            $md5Equal = (Get-FileHash -LiteralPath $copy -Algorithm MD5).Hash -eq
                (Get-FileHash -LiteralPath $output -Algorithm MD5).Hash
        }
        $originalUnchanged = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash -eq $originalHash
        $passed = $verifyExit -eq 0 -and $bytesEqual -and $md5Equal -and $originalUnchanged
        $results += [pscustomobject]@{
            File = $source.Name; Architecture = $arch; VerifyExit = $verifyExit
            BytesEqual = $bytesEqual; MD5Equal = $md5Equal; Passed = $passed
            Source = $source.FullName; OriginalUnchanged = $originalUnchanged; OriginalSHA256 = $originalHash
        }
        Write-Host "$arch $($source.Name): passed=$passed"
    }
}
$results | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputRoot 'results.json') -Encoding utf8
if ($results.Count -eq 0 -or @($results | Where-Object { -not $_.Passed }).Count -gt 0) {
    throw "Native roundtrip failed; see $OutputRoot"
}
Write-Host "PASS $($results.Count) native roundtrips: $OutputRoot"
