param(
    [string]$ShortcutName = "JNU Student Assistant Auto Refresh"
)

$project = Split-Path -Parent $PSScriptRoot
$python = (Get-Command pythonw.exe -ErrorAction Stop).Source
$daemon = Join-Path $project "scripts\automatic_update_daemon.py"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "$ShortcutName.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = "`"$daemon`""
$shortcut.WorkingDirectory = $project
$shortcut.Description = "Daily JNU student assistant data refresh"
$shortcut.Save()

Write-Host "Installed daily automatic refresh: $shortcutPath"
