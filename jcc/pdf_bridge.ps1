# JARVIS's PDF reader on Windows (jcc/doc_inputs.py runs it). Windows itself draws each page of a PDF as a picture
# (Windows.Data.Pdf), so diagrams, charts, photos and scans all come through, and reads the words off each picture
# (Windows.Media.Ocr). Nothing in the PDF is run: Windows only draws it.
# One request comes in on standard input; one answer goes out on standard output. Both are base64 of UTF-8 JSON.
# The request names a folder that JARVIS made; the PDF in it is always called source.pdf, and the pictures are written
# beside it as page-001.png and so on. No file name a person chose is ever on a command line.
$ErrorActionPreference = 'Stop'

function Say($value) {
    $json = $value | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
    [Console]::Out.Flush()
}
function Fail([string]$code) { Say @{ ok = $false; problem = $code }; exit 0 }

if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { Fail 'blocked' }

try { $ask = ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd().Trim()))) | ConvertFrom-Json }
catch { Fail 'unknown' }
$folderPath = [string]$ask.folder
if (-not $folderPath -or -not (Test-Path -LiteralPath (Join-Path $folderPath 'source.pdf'))) { Fail 'unknown' }
$most = [int]$ask.pages; if ($most -lt 1 -or $most -gt 200) { $most = 40 }
$edge = [int]$ask.edge; if ($edge -lt 200 -or $edge -gt 4000) { $edge = 1568 }
$small = [int]$ask.small; if ($small -lt 200 -or $small -gt $edge) { $small = 1100 }
$limit = [long]$ask.bytes; if ($limit -lt 100000) { $limit = 4000000 }

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
    $null = [Windows.Data.Pdf.PdfPageRenderOptions, Windows.Data.Pdf, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapEncoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
} catch { Fail 'no-renderer' }

$ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asOp = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asAction = $ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Wait-Op($op, [Type]$type) {
    $task = $asOp.MakeGenericMethod($type).Invoke($null, @($op))
    if (-not $task.Wait(30000)) { throw 'late' }
    return $task.Result
}
function Wait-Action($op) {
    $task = $asAction.Invoke($null, @($op))
    if (-not $task.Wait(30000)) { throw 'late' }
}
function Inner($err) {
    $e = $err.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    return $e
}

try {
    $folder = Wait-Op ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($folderPath)) ([Windows.Storage.StorageFolder])
    $file = Wait-Op ($folder.GetFileAsync('source.pdf')) ([Windows.Storage.StorageFile])
} catch { Fail 'unknown' }
try { $doc = Wait-Op ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument]) }
catch {
    $e = Inner $_
    if ($e.HResult -eq -2147023573) { Fail 'locked' }          # ERROR_WRONG_PASSWORD: it opens only with a password
    Fail 'damaged'
}
if ($doc.IsPasswordProtected) { Fail 'locked' }
$count = [int]$doc.PageCount
if ($count -lt 1) { Fail 'empty' }

$engine = $null
try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() } catch { $engine = $null }

function Draw($page, [string]$name, [int]$longest) {
    $out = Wait-Op ($folder.CreateFileAsync($name, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
    $stream = Wait-Op ($out.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
        if ($page.Size.Width -ge $page.Size.Height) { $options.DestinationWidth = [uint32]$longest } else { $options.DestinationHeight = [uint32]$longest }
        $options.BitmapEncoderId = [Windows.Graphics.Imaging.BitmapEncoder]::PngEncoderId
        Wait-Action ($page.RenderToStreamAsync($stream, $options))
    } finally { $stream.Dispose() }
    return $out
}

$pages = @()
$read = $false
$shown = [Math]::Min($count, $most)
for ($i = 0; $i -lt $shown; $i++) {
    $name = 'page-{0:D3}.png' -f ($i + 1)
    $page = $doc.GetPage([uint32]$i)
    try {
        $out = Draw $page $name $edge
        $size = (Get-Item -LiteralPath (Join-Path $folderPath $name)).Length
        if ($size -gt $limit) { $out = Draw $page $name $small }
        $text = ''
        if ($engine) {
            try {
                $stream = Wait-Op ($out.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
                try {
                    $decoder = Wait-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
                    $bitmap = Wait-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
                    $result = Wait-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                    $text = (@($result.Lines) | ForEach-Object { $_.Text }) -join "`n"
                    $bitmap.Dispose()
                } finally { $stream.Dispose() }
            } catch { $text = '' }
        }
        if ($text.Trim()) { $read = $true }
        $pages += @{ n = $i + 1; file = $name; text = $text }
    } catch { Fail 'damaged' }
    finally { $page.Dispose() }
}
Say @{ ok = $true; count = $count; ocr = [bool]$engine; read = $read; pages = $pages }
