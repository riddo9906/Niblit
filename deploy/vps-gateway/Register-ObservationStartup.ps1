[CmdletBinding(SupportsShouldProcess=$true)]
param(
 [string]$BasePath='C:\NiblitGateway',
 [Parameter(Mandatory=$true)][string]$GatewayRelease,
 [Parameter(Mandatory=$true)][string]$GatewayPython,
 [string]$UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
)
$ErrorActionPreference='Stop'
foreach($path in @("$GatewayRelease\gateway.py",$GatewayPython,"$BasePath\config\gateway.json","$BasePath\scripts\Start-ObservedTerminal.ps1")){
 if(!(Test-Path -LiteralPath $path)){throw 'Required explicit application/configuration path is missing'}
}
$account=New-Object Security.Principal.NTAccount($UserId)
$sid=$account.Translate([Security.Principal.SecurityIdentifier]).Value
$service=New-Object -ComObject Schedule.Service
$service.Connect()
$folder=$service.GetFolder('\')
$entries=@(
 @{name='Niblit-XM-Observed-Terminal';delay='PT15S';exe='powershell.exe';args=('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "{0}\scripts\Start-ObservedTerminal.ps1"' -f $BasePath);directory="$BasePath\scripts"},
 @{name='Niblit-VPS-Gateway-0.2';delay='PT45S';exe=$GatewayPython;args=('-B "{0}\gateway.py" "{1}\config\gateway.json" "{1}\state"' -f $GatewayRelease,$BasePath);directory=$GatewayRelease}
)
foreach($entry in $entries){
 # Existing definitions preserve unrelated settings and current durable state.
 $definition=$folder.GetTask($entry.name).Definition
 $definition.Triggers.Clear()
 $logon=$definition.Triggers.Create(9)
 $logon.UserId=$sid;$logon.Delay=$entry.delay;$logon.Enabled=$true
 $reconnect=$definition.Triggers.Create(11)
 $reconnect.UserId=$sid;$reconnect.StateChange=3;$reconnect.Delay=$entry.delay;$reconnect.Enabled=$true
 $definition.Principal.UserId=$sid
 $definition.Principal.LogonType=3
 $definition.Principal.RunLevel=0
 $definition.Actions.Clear()
 $action=$definition.Actions.Create(0)
 $action.Path=$entry.exe;$action.Arguments=$entry.args;$action.WorkingDirectory=$entry.directory
 $definition.Settings.MultipleInstances=2
 $definition.Settings.StartWhenAvailable=$true
 $definition.Settings.RestartCount=3
 $definition.Settings.RestartInterval='PT1M'
 $definition.Settings.ExecutionTimeLimit=if($entry.name -eq 'Niblit-XM-Observed-Terminal'){'PT5M'}else{'PT0S'}
 if($PSCmdlet.ShouldProcess($entry.name,'Register account-bound interactive sign-in and RDP reconnect startup')){
  $null=$folder.RegisterTaskDefinition($entry.name,$definition,6,$sid,$null,3)
  Write-Output ("Registered "+$entry.name)
 }
}
