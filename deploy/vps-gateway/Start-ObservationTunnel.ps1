param(
    [Parameter(Mandatory=$true)][string]$HostName,
    [Parameter(Mandatory=$true)][string]$KeyFile,
    [Parameter(Mandatory=$true)][string]$KnownHosts,
    [string]$UserName='Administrator',
    [int]$Port=18765
)
$ErrorActionPreference='Stop'
if ($HostName -notmatch '^[a-zA-Z0-9.-]+$' -or $UserName -notmatch '^[a-zA-Z0-9_-]+$' -or $Port -lt 1024 -or $Port -gt 65535) {
    throw 'Invalid tunnel endpoint'
}
if (!(Test-Path -LiteralPath $KeyFile) -or !(Test-Path -LiteralPath $KnownHosts)) {
    throw 'Pinned SSH identity files are required'
}
$mutex=[Threading.Mutex]::new($false, "Local\NiblitObservationTunnel-$Port")
$owned=$false
try {
    try { $owned=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned=$true }
    if (!$owned) { exit 0 }
    $delay=2
    $ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
    while ($true) {
        $started=Get-Date
        & $ssh -N -T -i $KeyFile -o "UserKnownHostsFile=$KnownHosts" -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -L ("127.0.0.1:{0}:127.0.0.1:{0}" -f $Port) "$UserName@$HostName"
        if (((Get-Date)-$started).TotalSeconds -gt 60) { $delay=2 }
        Start-Sleep -Seconds $delay
        $delay=[Math]::Min(30,$delay*2)
    }
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
