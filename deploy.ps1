#Запускать через powershell -ExecutionPolicy Bypass -File .\deploy.ps1


# Configuration
$SERVER_USER = "temp"
$SERVER_HOST = "thompson.uz"
$SERVER_PORT = "1089"
$REMOTE_PATH = "~/HW_Chechker_bot"

# Function to show status
function Show-Status($Message, $Type) {
    if ($Type -eq "info") {
        Write-Host "🔵 $Message" -ForegroundColor Cyan
    } elseif ($Type -eq "success") {
        Write-Host "✅ $Message" -ForegroundColor Green
    } elseif ($Type -eq "error") {
        Write-Host "❌ $Message" -ForegroundColor Red
    }
}

Write-Host "`n🚀 Starting deployment to $SERVER_HOST (port $SERVER_PORT)...`n" -ForegroundColor Yellow

# 1. Syncing code
Show-Status "Syncing code to server..." "info"
try {
    # В scp порт указывается через заглавную -P
    scp -P $SERVER_PORT -r bot.py Dockerfile docker-compose.yml requirements.txt "${SERVER_USER}@${SERVER_HOST}:${REMOTE_PATH}/"
    if ($LASTEXITCODE -ne 0) { throw "Failed to copy files." }
    Show-Status "Code synced successfully." "success"
} catch {
    Show-Status "Error syncing code: $_" "error"
    exit 1
}

# 2. Restarting container on server
Show-Status "Restarting Docker containers on server..." "info"
try {
    $commands = "cd $REMOTE_PATH && docker-compose down && docker-compose up -d --build"
    # В ssh порт указывается через строчную -p
    ssh -p $SERVER_PORT "${SERVER_USER}@${SERVER_HOST}" "$commands"
    if ($LASTEXITCODE -ne 0) { throw "Failed to restart containers." }
    Show-Status "Containers restarted and updated successfully!" "success"
} catch {
    Show-Status "Error restarting containers: $_" "error"
    exit 1
}

Write-Host "`n🎉 Deployment completed successfully!`n" -ForegroundColor Magenta
