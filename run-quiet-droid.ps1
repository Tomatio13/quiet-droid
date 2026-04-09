$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$env:OPENAI_BASE_URL = 
$env:OPENAI_API_KEY = 
$env:OPENAI_MODEL_ID = 

if ([string]::IsNullOrWhiteSpace($env:OPENAI_BASE_URL)) {
    Write-Error "OPENAI_BASE_URL is not set."
}

& python3 `
    (Join-Path $ScriptDir "quiet-droid.py") `
    --base-url $env:OPENAI_BASE_URL `
    --api-key $env:OPENAI_API_KEY `
    --model $env:OPENAI_MODEL_ID `
    @args
