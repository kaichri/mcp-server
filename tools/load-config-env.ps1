# Dot-source before local Python commands: . .\tools\load-config-env.ps1
# Reads only Exa settings. No evaluation, interpolation, persistence or value output.
param(
    [string]$ExaConfigPath = (Join-Path $PSScriptRoot '..\config.env')
)

$exaAllowedNames = @('EXA_API_KEY', 'EXA_PROVIDER', 'EXA_QUOTA_COOLDOWN_SECONDS', 'EXA_RATE_LIMIT_COOLDOWN_SECONDS')
$exaSettings = @{}
$exaLineNumber = 0
foreach ($exaLine in [IO.File]::ReadAllLines($ExaConfigPath)) {
    $exaLineNumber++
    $exaTrimmed = $exaLine.Trim()
    if (-not $exaTrimmed -or $exaTrimmed.StartsWith('#')) { continue }
    if ($exaTrimmed -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        throw "Invalid config.env syntax at line $exaLineNumber. Use NAME=value."
    }
    $exaName = $matches[1]
    $exaValue = $matches[2].Trim()
    if ($exaName -cnotin $exaAllowedNames) { continue }
    if ($exaSettings.ContainsKey($exaName)) {
        throw "Duplicate Exa setting at line $exaLineNumber."
    }
    if ($exaValue.StartsWith('"') -or $exaValue.StartsWith("'")) {
        if ($exaValue.Length -lt 2 -or $exaValue[-1] -ne $exaValue[0]) {
            throw "Unclosed quoted Exa setting at line $exaLineNumber."
        }
        $exaValue = $exaValue.Substring(1, $exaValue.Length - 2)
    }
    # Keep one common, literal format for PowerShell and Compose env_file.
    # Compose interprets $ and inline comments, so reject those ambiguous values.
    if ($exaValue.Contains('$') -or $exaValue.Contains('#') -or $exaValue -match '[\x00-\x1f]') {
        throw "Unsupported Exa value syntax at line $exaLineNumber. Use plain literal values."
    }
    $exaSettings[$exaName] = $exaValue
}
foreach ($exaEntry in $exaSettings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($exaEntry.Key, $exaEntry.Value, 'Process')
}
