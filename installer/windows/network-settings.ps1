# Native desktop network settings. This file is UTF-8 with BOM for Windows PowerShell 5.1.
$script:networkFile = Join-Path $env:LOCALAPPDATA 'KTVibes\network.json'
$script:networkPort = 8765
$script:networkIP = ''
if ($env:KTVIBES_PORT -match '^\d+$' -and [int]$env:KTVIBES_PORT -ge 1 -and [int]$env:KTVIBES_PORT -le 65535) { $script:networkPort = [int]$env:KTVIBES_PORT }
if ($env:KTVIBES_ADVERTISE_IP) { $script:networkIP = $env:KTVIBES_ADVERTISE_IP }
try {
    $savedNetwork = Get-Content -LiteralPath $script:networkFile -Raw -ErrorAction Stop | ConvertFrom-Json
    if ([int]$savedNetwork.port -ge 1 -and [int]$savedNetwork.port -le 65535) {
        $script:networkPort = [int]$savedNetwork.port
        $script:networkIP = [string]$savedNetwork.ip
    }
} catch { }
$script:networkExternal = [string]$savedNetwork.external_url
$script:networkHash = [string]$savedNetwork.password_hash
$script:credentialType = [string]$savedNetwork.credential_type
$script:networkBusy = $false

function Show-NetworkSettings {
    param([switch]$Conflict)
    if ($script:networkForm -and -not $script:networkForm.IsDisposed) {
        $script:networkForm.Activate()
        if ($Conflict -or $script:portConflict) { Show-NetworkConflict }
        return
    }
    $script:networkForm = New-Object System.Windows.Forms.Form
    $script:networkForm.Text = 'Network Settings'
    $script:networkForm.ClientSize = New-Object System.Drawing.Size(510, 90)
    $script:networkForm.StartPosition = 'CenterScreen'
    $script:networkForm.FormBorderStyle = 'FixedDialog'
    $script:networkForm.MaximizeBox = $false
    $addressLabel = New-Object System.Windows.Forms.Label
    $addressLabel.Text = 'Remote address'; $addressLabel.SetBounds(20, 15, 110, 25)
    $script:networkAddress = New-Object System.Windows.Forms.Label
    $script:networkAddress.SetBounds(135, 15, 305, 25)
    $script:networkAddress.AutoEllipsis = $true
    $copy = New-Object System.Windows.Forms.Button
    $copy.SetBounds(450, 10, 35, 32)
    $copy.AccessibleName = 'Copy address'
    $copy.add_Paint({
        param($sender, $e)
        $pen = New-Object System.Drawing.Pen([System.Drawing.SystemColors]::ControlText, 1.4)
        try {
            $e.Graphics.DrawRectangle($pen, 11, 6, 12, 14)
            $e.Graphics.DrawLine($pen, 8, 10, 8, 23)
            $e.Graphics.DrawLine($pen, 8, 23, 19, 23)
        } finally { $pen.Dispose() }
    })
    $copy.add_Click({ if ($script:networkAddress.Text -ne 'Unavailable') { [System.Windows.Forms.Clipboard]::SetText($script:networkAddress.Text) } })
    $script:networkCopyTip = New-Object System.Windows.Forms.ToolTip
    $script:networkCopyTip.SetToolTip($copy, 'Copy address')
    $script:networkAdvancedToggle = New-Object System.Windows.Forms.CheckBox
    $script:networkAdvancedToggle.Text = 'Advanced settings'; $script:networkAdvancedToggle.SetBounds(20, 52, 200, 25)
    $script:networkAdvanced = New-Object System.Windows.Forms.Panel
    $script:networkAdvanced.SetBounds(20, 90, 470, 245); $script:networkAdvanced.Visible = $false
    $label = New-Object System.Windows.Forms.Label
    $label.Text = 'Network'; $label.SetBounds(0, 5, 85, 25)
    $script:networkChoices = New-Object System.Windows.Forms.ComboBox
    $script:networkChoices.SetBounds(100, 0, 370, 28); $script:networkChoices.DropDownStyle = 'DropDownList'
    $script:networkIPs = @('')
    [void]$script:networkChoices.Items.Add('Automatic')
    foreach ($adapter in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        if ($adapter.OperationalStatus -ne 'Up' -or $adapter.NetworkInterfaceType -eq 'Loopback') { continue }
        foreach ($entry in $adapter.GetIPProperties().UnicastAddresses) {
            if ($entry.Address.AddressFamily -ne 'InterNetwork') { continue }
            $script:networkIPs += $entry.Address.ToString()
            [void]$script:networkChoices.Items.Add($adapter.Name + ' — ' + $entry.Address)
        }
    }
    if ($script:networkIPs -notcontains $script:networkIP) {
        $script:networkIPs += $script:networkIP
        [void]$script:networkChoices.Items.Add('Unavailable — ' + $script:networkIP)
    }
    $script:networkChoices.SelectedIndex = [Array]::IndexOf($script:networkIPs, $script:networkIP)
    $portLabel = New-Object System.Windows.Forms.Label
    $portLabel.Text = 'Port'; $portLabel.SetBounds(0, 45, 85, 25)
    $script:networkPortInput = New-Object System.Windows.Forms.NumericUpDown
    $script:portBorder = New-Object System.Windows.Forms.Panel
    $script:portBorder.SetBounds(98, 38, 164, 32)
    $script:networkPortInput.SetBounds(2, 2, 160, 28)
    $script:portBorder.Controls.Add($script:networkPortInput)
    $script:networkPortInput.Minimum = 1; $script:networkPortInput.Maximum = 65535; $script:networkPortInput.Value = $script:networkPort
    $script:externalToggle = New-Object System.Windows.Forms.CheckBox
    $script:externalToggle.Text = 'External address'; $script:externalToggle.SetBounds(0, 82, 200, 25)
    $script:externalToggle.Checked = -not [string]::IsNullOrEmpty($script:networkExternal)
    $script:externalInput = New-Object System.Windows.Forms.TextBox
    $script:externalInput.SetBounds(100, 112, 370, 26); $script:externalInput.Text = $script:networkExternal
    $script:externalBorder = New-Object System.Windows.Forms.Panel
    $script:externalBorder.SetBounds(98, 108, 372, 32); $script:externalBorder.BackColor = [System.Drawing.SystemColors]::Window
    $script:externalInput.BorderStyle = 'None'; $script:externalInput.SetBounds(10, 7, 350, 22); $script:externalBorder.Controls.Add($script:externalInput)
    $script:passwordInput = New-Object System.Windows.Forms.TextBox
    $script:passwordInput.SetBounds(100, 147, 370, 26); $script:passwordInput.UseSystemPasswordChar = $true
    $script:pinBorder = New-Object System.Windows.Forms.Panel
    $script:pinBorder.SetBounds(98, 145, 372, 32); $script:pinBorder.BackColor = [System.Drawing.SystemColors]::Window
    $script:passwordInput.BorderStyle = 'None'; $script:passwordInput.SetBounds(10, 7, 350, 22); $script:pinBorder.Controls.Add($script:passwordInput)
    $script:urlLabel = New-Object System.Windows.Forms.Label
    $script:urlLabel.Text = 'HTTPS URL'; $script:urlLabel.SetBounds(0, 115, 95, 25)
    $script:passwordLabel = New-Object System.Windows.Forms.Label
    $script:passwordLabel.Text = 'PIN'; $script:passwordLabel.SetBounds(0, 150, 95, 25)
    $script:externalToggle.add_CheckedChanged({
        Update-NetworkLayout
    })
    $script:externalInput.Enabled = $script:externalToggle.Checked; $script:passwordInput.Enabled = $script:externalToggle.Checked
    $script:networkAdvanced.Controls.AddRange(@($script:externalToggle, $script:externalBorder, $script:pinBorder, $script:urlLabel, $script:passwordLabel))
    $script:networkHint = New-Object System.Windows.Forms.Label
    $script:networkHint.Text = 'Applying changes will restart the server. Leave PIN blank to keep an existing PIN.'; $script:networkHint.SetBounds(0, 192, 470, 45)
    $script:networkAdvanced.Controls.AddRange(@($label, $script:networkChoices, $portLabel, $script:portBorder, $script:networkHint))
    $script:networkButtons = New-Object System.Windows.Forms.Panel
    $script:networkButtons.SetBounds(20, 345, 470, 35); $script:networkButtons.Visible = $false
    $reset = New-Object System.Windows.Forms.Button
    $reset.Text = 'Reset'; $reset.SetBounds(0, 0, 90, 30)
    $reset.add_Click({ $script:networkChoices.SelectedIndex = 0; $script:networkPortInput.Value = 8765; $script:externalToggle.Checked = $false; $script:externalInput.Text = ''; $script:passwordInput.Text = '';  $script:portBorder.BackColor = [System.Drawing.SystemColors]::Control })
    $script:networkApply = New-Object System.Windows.Forms.Button
    $script:networkApply.Text = 'Apply'; $script:networkApply.SetBounds(380, 0, 90, 30); $script:networkApply.add_Click({ Apply-NetworkSettings })
    $script:networkApply.BackColor = [System.Drawing.Color]::FromArgb(0, 103, 192)
    $script:networkApply.ForeColor = [System.Drawing.Color]::White
    $script:networkApply.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $script:networkApply.FlatAppearance.BorderSize = 0
    $script:networkButtons.Controls.AddRange(@($reset, $script:networkApply))
    $script:networkAdvancedToggle.add_CheckedChanged({
        $script:networkAdvanced.Visible = $this.Checked
        $script:networkButtons.Visible = $this.Checked
        Update-NetworkLayout
    })
    $script:networkForm.Controls.AddRange(@($addressLabel, $script:networkAddress, $copy, $script:networkAdvancedToggle, $script:networkAdvanced, $script:networkButtons))
    $script:networkPoll = New-Object System.Windows.Forms.Timer
    $script:networkPoll.Interval = 500
    $script:networkPoll.add_Tick({
        if ($script:networkPolling) { return }
        $script:networkPolling = $true
        try { Update-NetworkSettings } catch { $script:networkHint.Text = $_.Exception.Message }
        finally { $script:networkPolling = $false }
    })
    $script:networkForm.add_FormClosing({ if ($script:networkBusy) { $_.Cancel = $true } })
    $script:networkForm.add_FormClosed({ $script:networkPoll.Stop(); $script:networkPoll.Dispose(); $script:networkCopyTip.Dispose() })
    Update-NetworkLayout
    if ($script:networkExternal -and $script:credentialType -ne 'pin') { $script:networkHint.Text = 'Set a new PIN before applying. Your old password still works until then.' }
    $script:networkForm.Show(); $script:networkPoll.Start(); Update-NetworkSettings
    if ($Conflict -or $script:portConflict) { Show-NetworkConflict }
}

function Show-NetworkConflict {
    $script:networkAdvancedToggle.Checked = $true
    $script:networkHint.Text = 'Port conflict: these ports are in use. Choose another port.'
    $script:networkHint.ForeColor = [System.Drawing.Color]::Firebrick
    $script:portBorder.BackColor = [System.Drawing.Color]::Firebrick
}

function Apply-NetworkSettings {
    if ($script:networkBusy) { return }
    $nextPort = [int]$script:networkPortInput.Value
    $nextIP = $script:networkIPs[$script:networkChoices.SelectedIndex]
    $nextExternal = ''; $nextHash = ''; $nextType = ''
    if ($script:externalToggle.Checked) {
        $uri = $null
        if (-not [Uri]::TryCreate($script:externalInput.Text.Trim(), [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -notin @('/', '/remote')) { $script:networkHint.Text = 'Enter an HTTPS address, optionally ending in /remote.'; return }
        $nextExternal = $uri.AbsoluteUri; $nextHash = $script:networkHash
        $nextType = 'pin'
        $plain = $script:passwordInput.Text
        if (-not $plain -and $script:credentialType -ne 'pin') { $script:networkHint.Text = 'Set a new PIN of at least 6 digits. Your old password works until Apply.'; return }
        if ($plain) {
            if ($plain -cnotmatch '^[0-9]{6,1024}$') { $script:networkHint.Text = 'Use at least 6 digits (0–9).'; return }
            $salt = New-Object byte[] 16
            $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $rng.GetBytes($salt) } finally { $rng.Dispose() }
            $derive = [Security.Cryptography.Rfc2898DeriveBytes]::new($plain, $salt, 600000, [Security.Cryptography.HashAlgorithmName]::SHA256)
            try { $hash = $derive.GetBytes(32) } finally { $derive.Dispose() }
            $nextHash = 'pbkdf2-sha256$600000$' + ([BitConverter]::ToString($salt).Replace('-', '').ToLowerInvariant()) + '$' + ([BitConverter]::ToString($hash).Replace('-', '').ToLowerInvariant())
        }
        if (-not $nextHash) { $script:networkHint.Text = 'Set a PIN of at least 6 digits.'; return }
    }
    if ($nextPort -eq $script:networkPort -and $nextIP -eq $script:networkIP -and $nextExternal -eq $script:networkExternal -and $nextHash -eq $script:networkHash -and -not $script:portConflict) { $script:networkForm.Close(); return }
    $script:previousType = $script:credentialType
    $script:previousExternal = $script:networkExternal; $script:previousHash = $script:networkHash
    $script:previousPort = $script:networkPort; $script:previousIP = $script:networkIP
    $script:networkBusy = $true; $script:networkRollback = $false
    $script:networkAdvancedToggle.Enabled = $false; $script:networkAdvanced.Enabled = $false; $script:networkButtons.Enabled = $false
    $script:networkApply.Text = 'Restarting…'
    $script:networkHint.Text = 'Applying changes will restart the server. Leave PIN blank to keep an existing PIN.'
    $script:networkHint.ForeColor = [System.Drawing.SystemColors]::ControlText
    $script:portBorder.BackColor = [System.Drawing.SystemColors]::Control
    Stop-KTVibes
    $script:credentialType = $nextType
    $script:networkExternal = $nextExternal; $script:networkHash = $nextHash; $script:passwordInput.Text = ""
    $script:networkPort = $nextPort; $script:networkIP = $nextIP
    $script:networkDeadline = [DateTime]::UtcNow.AddSeconds(150)
    try { Start-KTVibes } catch { Restore-NetworkSettings $_.Exception.Message }
}

function Restore-NetworkSettings([string]$Reason) {
    Stop-KTVibes
    $script:credentialType = $script:previousType
    $script:networkExternal = $script:previousExternal; $script:networkHash = $script:previousHash
    $script:networkPort = $script:previousPort; $script:networkIP = $script:previousIP
    $script:networkRollback = $true
    $script:networkFailure = $Reason
    $script:networkDeadline = [DateTime]::UtcNow.AddSeconds(150)
    try { Start-KTVibes }
    catch {
        $script:networkBusy = $false
        $script:networkAdvancedToggle.Enabled = $true; $script:networkAdvanced.Enabled = $true; $script:networkButtons.Enabled = $true
        $script:networkApply.Text = 'Apply'
        $script:networkHint.Text = 'The server could not restart. Open Show Logs for details.'
        $script:networkHint.ForeColor = [System.Drawing.Color]::Firebrick
    }
}

function Update-NetworkSettings {
    if (Test-Path $script:activePortFile) {
        $candidate = Get-Content -LiteralPath $script:activePortFile -Raw -ErrorAction SilentlyContinue
        if ($candidate -match '^\s*\d+\s*$') { $script:activePort = [int]$candidate }
    }
    if ($script:server -and $script:server.HasExited -and (Test-Path $script:conflictFile)) { $script:portConflict = $true }
    $config = $null
    try { $config = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $script:activePort + '/api/config') -Headers @{Authorization=('Bearer ' + $script:desktopToken)} -TimeoutSec 1 } catch { }
    if ($config -and $config.instance_id -ne $script:networkInstance) { $config = $null }
    $script:networkAddress.Text = if ($config) { $config.remote_url } else { 'Unavailable' }
    if ($script:networkBusy) {
        if ($config -and $config.instance_id -eq $script:networkInstance) {
            if ($script:networkRollback) {
                $script:networkBusy = $false
                $script:networkAdvancedToggle.Enabled = $true; $script:networkAdvanced.Enabled = $true; $script:networkButtons.Enabled = $true
                $script:networkApply.Text = 'Apply'
                $script:networkHint.Text = $script:networkFailure
                $script:networkHint.ForeColor = [System.Drawing.Color]::Firebrick
            } else {
                try {
                    [void](New-Item -ItemType Directory -Path (Split-Path $script:networkFile) -Force -ErrorAction Stop)
                    @{port=$script:networkPort; ip=$script:networkIP; external_url=$script:networkExternal; password_hash=$script:networkHash; credential_type=$script:credentialType} | ConvertTo-Json | Set-Content -LiteralPath ($script:networkFile + '.tmp') -Encoding UTF8 -ErrorAction Stop
                    Move-Item -LiteralPath ($script:networkFile + '.tmp') -Destination $script:networkFile -Force -ErrorAction Stop
                } catch { Restore-NetworkSettings ('Could not save settings: ' + $_.Exception.Message); return }
                $script:networkBusy = $false
                $script:networkForm.Close()
                return
            }
        } elseif ([DateTime]::UtcNow -gt $script:networkDeadline -or ($script:server -and $script:server.HasExited -and (Test-Path $script:conflictFile))) {
            if ($script:networkRollback) {
                $script:networkBusy = $false
                $script:networkAdvancedToggle.Enabled = $true; $script:networkAdvanced.Enabled = $true; $script:networkButtons.Enabled = $true
                $script:networkApply.Text = 'Apply'
                $script:networkHint.Text = 'The server could not restart. Open Show Logs for details.'
                $script:networkHint.ForeColor = [System.Drawing.Color]::Firebrick
            } else { Restore-NetworkSettings 'The new server could not start. Check the port and try again.' }
        }
    } elseif (-not $config -and $script:portConflict) { Show-NetworkConflict }
    elseif (-not $config -and -not $script:networkRollback) {
        $script:networkHint.Text = 'Server unavailable. Open Show Logs for details.'
        $script:networkHint.ForeColor = [System.Drawing.Color]::Firebrick
    }
}

function Update-NetworkLayout {
    if (-not $script:networkButtons) { return }
    $on = $script:externalToggle.Checked
    $script:externalInput.Enabled = $on; $script:passwordInput.Enabled = $on
    foreach ($control in @($script:externalBorder, $script:pinBorder, $script:urlLabel, $script:passwordLabel)) { $control.Visible = $on }
    $script:networkHint.Top = $(if ($on) { 192 } else { 117 })
    $script:networkAdvanced.Height = $(if ($on) { 245 } else { 170 })
    $script:networkButtons.Top = $(if ($on) { 345 } else { 270 })
    $height = if (-not $script:networkAdvancedToggle.Checked) { 90 } elseif ($on) { 390 } else { 315 }
    $script:networkForm.ClientSize = New-Object System.Drawing.Size(510, $height)
}
