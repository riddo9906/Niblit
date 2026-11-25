# Local Client Portal and email-review notifications. Never exposes Portal directly.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root='C:\Users\Riyaad\Documents\GitHub\Niblit'
$mailFile='D:\NiblitAIOS\config\client-portal\portal-mail.env'
$logs='D:\NiblitAIOS\diagnostics\android-frontend-20261121'
$port=8768
foreach($line in Get-Content -LiteralPath $mailFile){
    if($line -match '^([A-Z0-9_]+)=(.+)$'){
        [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')
    }
}
if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){
    try{
        $r=Invoke-RestMethod 'http://127.0.0.1:8768/api/health' -TimeoutSec 3
        if($r.status -eq 'ok'){
            Write-Output 'Niblit Client Portal already responding; no duplicate started'
            return
        }
    }catch{}
    throw 'Client Portal port is occupied by an unexpected service'
}
New-Item -ItemType Directory -Force -Path $logs|Out-Null
$p=Start-Process -FilePath "$root\niblit-env\Scripts\python.exe" -ArgumentList @(
    '-m','uvicorn','modules.server_manager:create_app','--factory',
    '--host','127.0.0.1','--port','8768','--no-proxy-headers'
) -WorkingDirectory $root -RedirectStandardOutput "$logs\portal.stdout.log" -RedirectStandardError "$logs\portal.stderr.log" -PassThru
Write-Output ("NIBLIT_PORTAL_PID="+$p.Id+" URL=http://127.0.0.1:8768/")
