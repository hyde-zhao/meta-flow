param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ScriptDir "install.py"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $PythonScript @ForwardArgs
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $PythonScript @ForwardArgs
    exit $LASTEXITCODE
}

Write-Error "Python 3 is required to run install.ps1"
exit 1
