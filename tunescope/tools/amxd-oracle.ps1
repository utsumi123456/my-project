# amxd ロード判定オラクル: スタンドアロン Max で開き、ファイル名を含むウィンドウが出れば LOAD_OK
param([Parameter(Mandatory=$true)][string]$File, [int]$TimeoutSec = 50)

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WinEnum {
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder sb, int max);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    delegate bool EnumWindowsProc(IntPtr h, IntPtr lp);
    public static List<string> TitlesForPid(uint target) {
        var list = new List<string>();
        EnumWindows((h, lp) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == target && IsWindowVisible(h)) {
                var sb = new StringBuilder(512);
                GetWindowText(h, sb, 512);
                if (sb.Length > 0) list.Add(sb.ToString());
            }
            return true;
        }, IntPtr.Zero);
        return list;
    }
}
"@

Stop-Process -Name Max -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$proc = Start-Process "C:\Program Files\Cycling '74\Max 9\Max.exe" -ArgumentList "`"$File`"" -PassThru
$base = [IO.Path]::GetFileNameWithoutExtension($File)
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$result = "NO_WINDOW"
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $titles = [WinEnum]::TitlesForPid([uint32]$proc.Id)
    if ($titles | Where-Object { $_ -like "*$base*" }) { $result = "LOAD_OK"; break }
}
$titles = [WinEnum]::TitlesForPid([uint32]$proc.Id)
Write-Host "RESULT: $result  titles=[$($titles -join ' | ')]"
Stop-Process -Name Max -Force -ErrorAction SilentlyContinue
exit ($(if ($result -eq "LOAD_OK") { 0 } else { 1 }))
