$ErrorActionPreference = "Stop"
$probe = "F:\_DEV\TeleM\Raporty\NVIDIA_NV2\poc\mf_rotation_probe.cs"
$target = "F:\_DEV\TeleM\Raporty\NVIDIA_NV2\poc\nv2_poc_rot180.mp4"
Add-Type -Path $probe
[MfRotationProbe]::Run($target)
Write-Output "--- source reference ---"
[MfRotationProbe]::Run("F:\_DEV\TeleM\Video\GX020079.MP4")
