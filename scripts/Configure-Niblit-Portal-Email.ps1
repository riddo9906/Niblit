# One-time local Gmail SMTP setup. Does not print the App Password.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$path='D:\NiblitAIOS\config\client-portal\smtp-app-password.txt'
New-Item -ItemType Directory -Force -Path (Split-Path $path -Parent)|Out-Null
if(Test-Path $path) {
  Write-Output 'Gmail App Password file already exists. Delete the file explicitly before reconfiguring it.'
  return
}
$secure=Read-Host 'Enter the 16-character Gmail App Password (input hidden)' -AsSecureString
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $secret=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  if([string]::IsNullOrWhiteSpace($secret) -or $secret.Replace(' ','').Length -lt 16) {
    throw 'An App Password of at least 16 characters is required'
  }
  # Gmail accepts the app password without display spaces.
  $secret=$secret.Replace(' ','')
  [IO.File]::WriteAllText($path,$secret,[Text.UTF8Encoding]::new($false))
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
& icacls.exe $path /inheritance:r | Out-Null
& icacls.exe $path /grant:r "$($env:USERNAME):(R,W)" | Out-Null
Write-Output ('Portal SMTP credentials configured at '+$path)
Write-Output 'Restart the Portal service using Restart-Niblit-Client-Portal.ps1 and test a new registration.'
