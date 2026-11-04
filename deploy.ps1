dotnet build
if ($LASTEXITCODE -eq 0) {
    $dest = "$env:USERPROFILE\Documents\Klei\OxygenNotIncluded\mods\dev\OniAgent"
    Copy-Item "$PSScriptRoot\bin\Debug\net48\OniAgent.dll" $dest -Force
    Write-Host "Da copy xong"
}
else {
    Write-Host "Build loi, khong copy"
}
