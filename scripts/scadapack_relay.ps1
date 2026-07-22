<#
.SYNOPSIS
    Aevus SCADAPack 470 Modbus relay — runs on SHOP-01, the only host that can
    reach the RTU at 172.16.1.200 (via its 172.16.1.100 interface) AND the
    internet. Polls Modbus TCP comms-health and POSTs to the Aevus /ingest API.

.DESCRIPTION
    The edge Pi (192.168.88.x) cannot route to the SCADAPack's 172.16.1.x
    subnet, so SHOP-01 acts as the Modbus relay. This script:

      1. Opens a raw TCP socket BOUND to 172.16.1.100 (forces the right NIC —
         Windows would otherwise mis-route via Wi-Fi).
      2. Sends a Modbus FC3 "read holding registers" request and validates a
         real Modbus response (function code 0x03, not an exception 0x83).
      3. Measures round-trip latency and a rolling comms-success rate.
      4. POSTs an HONEST vitals payload to /api/v1/ingest:
            MODBUS LINK, MODBUS LATENCY, COMM SUCCESS   (on success)
            MODBUS LINK=0 + COMMUNICATION FAULT ALARM   (on failure)
         It does NOT fabricate process values (pressure/battery) — the bench
         unit has no field I/O wired, so only comms-health is real today. When
         real transducers are configured, add their register decodes below.

    NO INSTALLS REQUIRED — pure PowerShell + .NET sockets + Invoke-RestMethod.

.PARAMETER Once
    Single poll + post, print the result, and exit (use to verify before
    installing as a Scheduled Task).

.EXAMPLE
    # Verify a single cycle:
    powershell -ExecutionPolicy Bypass -File scadapack_relay.ps1 -Once

.EXAMPLE
    # Run continuously (Ctrl+C to stop):
    powershell -ExecutionPolicy Bypass -File scadapack_relay.ps1

.NOTES
    READ-ONLY (IL-009 / P-008): this relay only READS Modbus holding registers.
    It never writes to the RTU. No firmware/coil writes — ever.
#>

param(
    [string]$ScadaIp   = '172.16.1.200',
    [string]$SourceIp  = '172.16.1.100',
    [int]   $Port      = 502,
    [int]   $UnitId    = 1,
    [string]$AssetId   = 'RTU-01',
    [string]$IngestUrl = 'https://aevus.intrepidlogic.io/api/v1/ingest',
    # Shared ingest secret (H3): defaults from the AEVUS_INGEST_SECRET env var
    # (set it machine-wide or in the Scheduled Task definition). When set and
    # matching the server's INGEST_SECRET, it is sent as X-Ingest-Key. Empty →
    # no header, which the server accepts until enforcement is flipped on.
    [string]$IngestSecret = $env:AEVUS_INGEST_SECRET,
    [int]   $IntervalSec = 30,
    [int]   $TimeoutMs   = 2500,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$LogFile = Join-Path $env:USERPROFILE 'scadapack_relay.log'

# Rolling comms-success window (last 20 polls)
$script:Window = New-Object System.Collections.Generic.Queue[int]
$WindowSize = 20

function Write-Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'u'), $msg
    Write-Host $line
    try { Add-Content -Path $LogFile -Value $line } catch {}
}

function Invoke-ModbusRead {
    <# Returns @{ ok=$bool; latencyMs=$int; regs=@(...) } #>
    $client = $null
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $localIp = [System.Net.IPAddress]::Parse($SourceIp)
        $localEp = New-Object System.Net.IPEndPoint($localIp, 0)
        $client  = New-Object System.Net.Sockets.TcpClient($localEp)
        $client.Connect($ScadaIp, $Port)
        $stream = $client.GetStream()
        $stream.ReadTimeout = $TimeoutMs

        # MBAP + PDU: read 8 holding registers @ addr 0
        $req = [byte[]](0x00,0x01,0x00,0x00,0x00,0x06,$UnitId,0x03,0x00,0x00,0x00,0x08)
        $stream.Write($req, 0, $req.Length)

        $buf = New-Object byte[] 256
        $n = $stream.Read($buf, 0, 256)
        $sw.Stop()

        if ($n -lt 9) { return @{ ok = $false; reason = "short response ($n bytes)" } }
        $fc = $buf[7]
        if ($fc -eq 0x83) { return @{ ok = $false; reason = "modbus exception 0x$('{0:X2}' -f $buf[8])" } }
        if ($fc -ne 0x03) { return @{ ok = $false; reason = "unexpected FC 0x$('{0:X2}' -f $fc)" } }

        # Decode register words (big-endian) for diagnostics
        $byteCount = $buf[8]
        $regs = @()
        for ($i = 0; $i -lt $byteCount; $i += 2) {
            $regs += ([int]$buf[9 + $i] * 256 + [int]$buf[10 + $i])
        }
        return @{ ok = $true; latencyMs = [int]$sw.ElapsedMilliseconds; regs = $regs }
    }
    catch {
        $sw.Stop()
        return @{ ok = $false; reason = $_.Exception.Message }
    }
    finally {
        if ($client) { $client.Dispose() }
    }
}

function Get-CommSuccessPct([bool]$ok) {
    $script:Window.Enqueue([int]$ok)
    while ($script:Window.Count -gt $WindowSize) { [void]$script:Window.Dequeue() }
    $sum = 0; foreach ($v in $script:Window) { $sum += $v }
    return [int]([math]::Round(100.0 * $sum / [math]::Max(1, $script:Window.Count)))
}

function Send-Cycle {
    $r = Invoke-ModbusRead
    $commPct = Get-CommSuccessPct $r.ok

    if ($r.ok) {
        $vitals = @{
            'MODBUS LINK'    = @{ value = 1;            unit = '';   status = 'good' }
            'MODBUS LATENCY' = @{ value = $r.latencyMs; unit = 'ms'; status = 'good' }
            'COMM SUCCESS'   = @{ value = $commPct;     unit = '%';  status = if ($commPct -ge 90) {'good'} elseif ($commPct -ge 60) {'warn'} else {'bad'} }
        }
        Write-Log ("poll OK  latency={0}ms  comm={1}%  regs=[{2}]" -f $r.latencyMs, $commPct, ($r.regs -join ','))
    }
    else {
        $vitals = @{
            'MODBUS LINK'               = @{ value = 0;        unit = ''; status = 'bad' }
            'COMMUNICATION FAULT ALARM' = 'ACTIVE'
            'COMM SUCCESS'              = @{ value = $commPct; unit = '%'; status = 'bad' }
        }
        Write-Log ("poll FAIL ({0})  comm={1}%" -f $r.reason, $commPct)
    }

    $body = @{ asset_id = $AssetId; vitals = $vitals } | ConvertTo-Json -Depth 6
    $headers = @{}
    if ($IngestSecret) { $headers['X-Ingest-Key'] = $IngestSecret }
    try {
        $resp = Invoke-RestMethod -Uri $IngestUrl -Method Post -Body $body -ContentType 'application/json' -Headers $headers -TimeoutSec 15
        Write-Log ("ingest OK  vitals_ingested={0}  historian_written={1}" -f $resp.vitals_ingested, $resp.historian_written)
        return $true
    }
    catch {
        Write-Log ("ingest FAIL: {0}" -f $_.Exception.Message)
        return $false
    }
}

Write-Log ("=== Aevus SCADAPack relay starting === asset={0} target={1}:{2} src={3} -> {4}" -f $AssetId, $ScadaIp, $Port, $SourceIp, $IngestUrl)

if ($Once) {
    Send-Cycle | Out-Null
    Write-Log "=== single-shot complete ==="
    exit 0
}

while ($true) {
    try { Send-Cycle | Out-Null } catch { Write-Log ("cycle error: {0}" -f $_.Exception.Message) }
    Start-Sleep -Seconds $IntervalSec
}
