# Run the Telegram relay bot (loads .env from project root)
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".env")) {
    Write-Host "Create a .env file first (copy from .env.example)." -ForegroundColor Yellow
    exit 1
}

pip install -r requirements.txt -q
python -m telegram_bot.bot
