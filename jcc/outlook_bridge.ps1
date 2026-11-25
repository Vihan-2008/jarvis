# JARVIS's bridge to classic Outlook on this PC (jcc/outlook.py runs it). Outlook lets programs on the same PC use the
# mail it already has through its object model: no app approval, no password. This script does a fixed set of things
# and nothing else. One request comes in on standard input; answers go out on standard output, one per line. Both are
# base64 of UTF-8 JSON (Windows PowerShell mangles other characters on its standard streams). What a request or a
# message says is never put on a command line, never written to a file, and never shown in an error.
$ErrorActionPreference = 'Stop'

function Say($value) {
    $json = $value | ConvertTo-Json -Depth 6 -Compress
    [Console]::Out.WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
    [Console]::Out.Flush()
}
function Fail([string]$code) { Say @{ ok = $false; problem = $code }; exit 0 }
function Clip($text, [int]$most) {
    $t = ([string]$text -replace '\s+', ' ').Trim()
    if ($t.Length -gt $most) { return $t.Substring(0, $most) }
    return $t
}
function Iso($when) { try { return ([datetime]$when).ToString('s') } catch { return '' } }
function Day([string]$text) { return [datetime]::Parse($text, [Globalization.CultureInfo]::InvariantCulture) }
function Jet([datetime]$when) { return "'" + $when.ToString('g') + "'" }

if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { Fail 'blocked' }      # (a locked-down PC: COM is not allowed)

try { $ask = ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))) | ConvertFrom-Json }
catch { Fail 'unknown' }
$op = [string]$ask.op
$allowed = @()
if ($ask.allowed) { $allowed = @(@($ask.allowed) | Where-Object { $_ } | ForEach-Object { ([string]$_).ToLower() }) }
if ($op -eq 'ping') { Say @{ ok = $true; pong = $true }; exit 0 }             # (PowerShell answers; Outlook is not touched)

# The Outlook that is open, or Outlook started without a window. It is never closed from here.
$started = $false
try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
catch {
    try { $ol = New-Object -ComObject Outlook.Application; $started = $true }
    catch {
        $code = $_.Exception.HResult
        if ($code -eq -2147221164) { Fail 'no-classic' }            # REGDB_E_CLASSNOTREG: classic Outlook is not installed
        if ($code -eq -2147024891) { Fail 'blocked' }               # E_ACCESSDENIED
        Fail 'start-failed'
    }
}
try { $ns = $ol.GetNamespace('MAPI') } catch { Fail 'start-failed' }

function Addresses($item) {                                      # (its recipients' addresses, the same way before and after sending)
    $out = @()
    foreach ($r in $item.Recipients) {
        $a = ''
        try { if ([string]$r.AddressEntry.Type -eq 'EX') { $u = $r.AddressEntry.GetExchangeUser(); if ($u) { $a = [string]$u.PrimarySmtpAddress } } } catch { }
        if (-not $a) { $a = [string]$r.Address }
        $out += $a.ToLower()
    }
    return (($out | Sort-Object) -join ';')
}
function Sender($m) {
    try {
        if ([string]$m.SenderEmailType -eq 'EX') { $u = $m.Sender.GetExchangeUser(); if ($u) { return [string]$u.PrimarySmtpAddress } }
        return [string]$m.SenderEmailAddress
    } catch { return '' }
}
# Only an account the owner ticked, found by its address, and only in that account's own mail.
function Account([string]$want) {
    $want = $want.ToLower()
    if ($allowed -notcontains $want) { Fail 'not-allowed' }
    foreach ($a in $ns.Accounts) { if (([string]$a.SmtpAddress).ToLower() -eq $want) { return $a } }
    Fail 'no-account'
}
function Folder($account, [string]$name) {
    $kind = switch ($name) { 'sent' { 5 } 'drafts' { 16 } 'calendar' { 9 } default { 6 } }
    return $account.DeliveryStore.GetDefaultFolder($kind)
}

try {
    switch ($op) {
        'status' {
            $rows = @()
            foreach ($a in $ns.Accounts) {
                $address = [string]$a.SmtpAddress
                if ($address) { $rows += @{ address = $address.ToLower(); name = [string]$a.DisplayName } }
            }
            Say @{ ok = $true; version = [string]$ol.Version; started = $started; accounts = $rows }
        }
        'list' {
            $account = Account $ask.account
            $folder = [string]$ask.folder
            $field = switch ($folder) { 'sent' { '[SentOn]' } 'drafts' { '[LastModificationTime]' } default { '[ReceivedTime]' } }
            $items = (Folder $account $folder).Items
            $items.Sort($field, $true)
            $since = if ($ask.since) { Day $ask.since } elseif ($ask.query -or $ask.from_person) { [datetime]::Now.AddDays(-30) } else { $null }
            $parts = @()
            if ($since) { $parts += $field + ' >= ' + (Jet $since) }
            if ($ask.until) { $parts += $field + ' < ' + (Jet (Day $ask.until)) }
            if ($ask.unread) { $parts += '[UnRead] = True' }
            if ($parts.Count) { $items = $items.Restrict($parts -join ' AND '); $items.Sort($field, $true) }
            $words = @()
            if ($ask.query) {
                $q = ([string]$ask.query).Replace("'", "''")
                $words += "(""urn:schemas:httpmail:subject"" LIKE '%$q%' OR ""urn:schemas:httpmail:textdescription"" LIKE '%$q%')"
            }
            if ($ask.from_person) {
                $p = ([string]$ask.from_person).Replace("'", "''")
                $words += "(""urn:schemas:httpmail:fromname"" LIKE '%$p%' OR ""urn:schemas:httpmail:fromemail"" LIKE '%$p%')"
            }
            if ($words.Count) { $items = $items.Restrict('@SQL=' + ($words -join ' AND ')); $items.Sort($field, $true) }
            $most = [Math]::Max(1, [Math]::Min([int]$ask.limit, 25))
            $rows = @(); $looked = 0
            $m = $items.GetFirst()                                       # (GetFirst and GetNext keep the order Sort set)
            while ($null -ne $m -and $rows.Count -lt $most -and $looked -lt 500) {
                $looked++
                if ($m.Class -eq 43) {                                   # (mail only: not meeting requests or delivery reports)
                    $when = switch ($folder) { 'sent' { $m.SentOn } 'drafts' { $m.LastModificationTime } default { $m.ReceivedTime } }
                    $rows += @{ entry = [string]$m.EntryID; store = [string]$m.Parent.StoreID; from = Clip $m.SenderName 120; address = Sender $m
                                subject = Clip $m.Subject 200; when = Iso $when; unread = [bool]$m.UnRead; preview = Clip $m.Body 200 }
                }
                $m = $items.GetNext()
            }
            Say @{ ok = $true; messages = $rows; started = $started }
        }
        'read' {
            $account = Account $ask.account
            $m = $ns.GetItemFromID([string]$ask.entry, [string]$ask.store)
            if ([string]$m.Parent.StoreID -ne [string]$account.DeliveryStore.StoreID) { Fail 'not-allowed' }
            $body = [string]$m.Body
            $cut = $body.Length -gt 12000
            if ($cut) { $body = $body.Substring(0, 12000) }
            $files = @(); foreach ($f in $m.Attachments) { $files += Clip $f.FileName 120 }
            Say @{ ok = $true; from = Clip $m.SenderName 120; address = Sender $m; to = Clip $m.To 600; cc = Clip $m.CC 600
                   subject = Clip $m.Subject 300; when = Iso $m.ReceivedTime; body = $body; cut = $cut; attachments = $files }
        }
        'calendar' {
            $account = Account $ask.account
            $from = Day $ask.from; $to = Day $ask.to
            if (($to - $from).TotalDays -gt 31) { $to = $from.AddDays(31) }
            $items = (Folder $account 'calendar').Items
            $items.Sort('[Start]'); $items.IncludeRecurrences = $true
            $items = $items.Restrict('[Start] < ' + (Jet $to) + ' AND [End] > ' + (Jet $from))
            $rows = @()
            $e = $items.GetFirst()                                       # (with recurrences included, only GetFirst and GetNext are reliable)
            while ($null -ne $e -and $rows.Count -lt 50) {
                $rows += @{ subject = Clip $e.Subject 200; start = Iso $e.Start; end = Iso $e.End; where = Clip $e.Location 120
                            organizer = Clip $e.Organizer 120; all_day = [bool]$e.AllDayEvent }
                $e = $items.GetNext()
            }
            Say @{ ok = $true; events = $rows; started = $started }
        }
        'send' {
            $account = Account $ask.account
            $mail = $ol.CreateItem(0)
            $mail.To = [string]$ask.to
            $mail.Subject = [string]$ask.subject
            $mail.Body = [string]$ask.body
            [void]$mail.GetType().InvokeMember('SendUsingAccount', [Reflection.BindingFlags]::SetProperty, $null, $mail, @($account))
            $going = ''
            try { $going = ([string]$mail.SendUsingAccount.SmtpAddress).ToLower() } catch { $going = '' }
            if ($going -ne ([string]$ask.account).ToLower()) {
                try { $mail.Close(1) } catch { }                           # (olDiscard: the unsent message is dropped, never saved)
                Say @{ ok = $true; sent = $false; problem = 'wrong-account'; other = $going }
                exit 0
            }
            if (-not $mail.Recipients.ResolveAll()) {
                try { $mail.Close(1) } catch { }
                Say @{ ok = $true; sent = $false; problem = 'bad-recipient' }
                exit 0
            }
            $want = Addresses $mail
            $mark = [datetime]::Now.AddSeconds(-15)                      # (the server's clock may be a little behind this PC's)
            Say @{ stage = 'sending' }
            $mail.Send()
            # Sent only once it is in Sent Items: a message still in the Outbox has not gone.
            $deadline = [datetime]::Now.AddSeconds([Math]::Min([int]$ask.wait, 50))
            $places = @((Folder $account 'sent'), $ns.GetDefaultFolder(5))
            $found = $false
            while (-not $found -and [datetime]::Now -lt $deadline) {
                Start-Sleep -Milliseconds 800
                foreach ($place in $places) {
                    foreach ($s in $place.Items.Restrict('[SentOn] >= ' + (Jet $mark.AddMinutes(-1)))) {
                        if ([string]$s.Subject -eq [string]$ask.subject -and $s.SentOn -ge $mark -and (Addresses $s) -eq $want) { $found = $true; break }
                    }
                    if ($found) { break }
                }
            }
            Say @{ ok = $true; sent = $found; from = $going }
        }
        default { Fail 'unknown' }
    }
} catch { Fail 'failed' }
