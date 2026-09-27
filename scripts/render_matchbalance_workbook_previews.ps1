param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbookPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$excel = $null
$workbook = $null

try {
    $workbookPath = [System.IO.Path]::GetFullPath($WorkbookPath)
    $outputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
    [System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $workbook = $excel.Workbooks.Open($workbookPath, 0, $true)

    $previews = @(
        @{ Sheet = "U10 Boys"; File = "u10-boys.pdf" },
        @{ Sheet = "U12 Girls"; File = "u12-girls.pdf" }
    )
    foreach ($preview in $previews) {
        $sheet = $workbook.Worksheets.Item($preview.Sheet)
        $output = Join-Path $outputDirectory $preview.File
        # 0 = PDF, 0 = standard quality. Export page one of the sheet's fixed
        # print area; the production workbook renderer owns the page layout.
        $sheet.ExportAsFixedFormat(0, $output, 0, $true, $false, 1, 1, $false)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
    }
}
finally {
    if ($null -ne $workbook) {
        $workbook.Close($false)
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
    }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
