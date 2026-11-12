# Server lifecycle and child environment used by the tray and network settings.
function Start-KTVibes {
    Remove-Item -LiteralPath $script:activePortFile -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $script:conflictFile -ErrorAction SilentlyContinue
    $script:activePort = $script:networkPort
    $script:portConflict = $false
    foreach ($oldLog in @((Join-Path $logDir 'ktvibes.log.1'), (Join-Path $logDir 'ktvibes.log.2'))) {
        if ((Test-Path $oldLog) -and (Get-Item $oldLog).Length -gt 5MB) { Remove-Item -LiteralPath $oldLog -Force }
    }
    if ((Test-Path $logPath) -and (Get-Item $logPath).Length -ge 5MB) {
        $second = Join-Path $logDir 'ktvibes.log.2'
        $first = Join-Path $logDir 'ktvibes.log.1'
        Remove-Item -LiteralPath $second -Force -ErrorAction SilentlyContinue
        if (Test-Path $first) { Move-Item -LiteralPath $first -Destination $second -Force }
        Move-Item -LiteralPath $logPath -Destination $first -Force
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $env:ComSpec
    $start.Arguments = '/c ""' + $cmdPath + '" >> "' + $logPath + '" 2>&1"'
    $start.WorkingDirectory = $appDir
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.EnvironmentVariables['KTVIBES_PORT'] = [string]$script:networkPort
    $start.EnvironmentVariables['KTVIBES_AUTO_PORT'] = '1'
    $start.EnvironmentVariables['KTVIBES_PORT_FILE'] = $script:activePortFile
    $start.EnvironmentVariables['KTVIBES_CONFLICT_FILE'] = $script:conflictFile
    $start.EnvironmentVariables['KTVIBES_ADVERTISE_IP'] = $script:networkIP
    $start.EnvironmentVariables.Remove('KTVIBES_REMOTE_URL')
    $script:networkInstance = [Guid]::NewGuid().ToString('N')
    $start.EnvironmentVariables['KTVIBES_INSTANCE_ID'] = $script:networkInstance
    if ($script:networkBusy) { $start.EnvironmentVariables['KTVIBES_OPEN_BROWSER'] = '0' }
    $script:server = [System.Diagnostics.Process]::Start($start)
}

function Stop-KTVibes {
    if ($script:server -and -not $script:server.HasExited) {
        $stop = New-Object System.Diagnostics.ProcessStartInfo
        $stop.FileName = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        $stop.Arguments = '/PID ' + $script:server.Id + ' /T /F'
        $stop.UseShellExecute = $false
        $stop.CreateNoWindow = $true
        $process = [System.Diagnostics.Process]::Start($stop)
        $process.WaitForExit()
        $process.Dispose()
    }
    $script:server = $null
}
