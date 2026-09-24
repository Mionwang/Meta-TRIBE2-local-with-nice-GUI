param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$content = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($content)) { throw 'The text is empty.' }
$stream = New-Object -ComObject SAPI.SpFileStream
$stream.Format.Type = 22 # SAFT22kHz16BitMono (22.05 kHz, 16-bit mono PCM)
try {
    $stream.Open($OutputPath, 3)
    $voice = New-Object -ComObject SAPI.SpVoice
    $voice.AudioOutputStream = $stream
    # 16 = SVSFIsNotXML: speak text literally; the default (0) auto-detects
    # SAPI XML, so a pasted script starting with "<" could be misparsed.
    [void]$voice.Speak($content, 16)
} finally {
    $stream.Close()
}
