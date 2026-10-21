param(
    [ValidateSet('list','print','validate')][string]$Mode='list',
    [string]$Printer,
    [string]$ImagePath,
    [ValidateSet('roll_58','roll_80','letter')][string]$PaperSize='roll_80'
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Drawing
if ($Mode -eq 'list') {
    $names=@([System.Drawing.Printing.PrinterSettings]::InstalledPrinters | ForEach-Object { [string]$_ })
    ConvertTo-Json -InputObject $names -Compress
    exit
}
# Data is passed as arguments, never evaluated as PowerShell code.
Add-Type -TypeDefinition @"
using System;
using System.Drawing;
using System.Drawing.Printing;
public static class SqiReceiptPrinter {
    public static void Send(string printer, string path, string paperSize) {
        using (Image image = Image.FromFile(path))
        using (PrintDocument document = new PrintDocument()) {
            document.PrinterSettings.PrinterName = printer;
            if (!document.PrinterSettings.IsValid) throw new Exception("Printer is unavailable.");
            document.PrinterSettings.Copies = 1;
            document.DocumentName = "SQI acknowledgement receipt";
            document.PrintController = new StandardPrintController();
            if (paperSize == "letter") {
                PaperSize letter = null;
                foreach (PaperSize size in document.PrinterSettings.PaperSizes) {
                    if (size.Kind == PaperKind.Letter) { letter = size; break; }
                }
                document.DefaultPageSettings.PaperSize = letter ?? new PaperSize("Letter", 850, 1100);
                document.DefaultPageSettings.Margins = new Margins(50,50,50,50);
            } else {
                int widthMm = paperSize == "roll_58" ? 58 : 80;
                int paperWidth = (int)Math.Round(widthMm / 25.4 * 100);
                int paperHeight = Math.Max(100, Math.Min(1100, (int)Math.Ceiling(image.Height * (paperWidth-16.0) / image.Width) + 16));
                document.DefaultPageSettings.PaperSize = new PaperSize("SQI receipt", paperWidth, paperHeight);
                document.DefaultPageSettings.Margins = new Margins(8,8,8,8);
            }
            float sourceY = 0;
            document.PrintPage += (sender, e) => {
                float y = Math.Max(e.MarginBounds.Top, e.PageSettings.HardMarginY);
                float printableWidth = Math.Min(e.MarginBounds.Width, e.PageSettings.PrintableArea.Width);
                float outputWidth = printableWidth;
                float x = Math.Max(e.MarginBounds.Left, e.PageSettings.HardMarginX);
                if (paperSize == "letter") {
                    outputWidth = Math.Min(printableWidth, (float)(80.0 / 25.4 * 100.0));
                    x = e.MarginBounds.Left + (e.MarginBounds.Width - outputWidth) / 2;
                    x = Math.Max(x, e.PageSettings.HardMarginX);
                }
                float scale = outputWidth / image.Width;
                float sourceHeight = Math.Min(image.Height-sourceY, e.MarginBounds.Height/scale);
                if (sourceHeight <= 0 || scale <= 0) throw new Exception("Invalid printer paper size.");
                e.Graphics.DrawImage(image, new RectangleF(x,y,outputWidth,sourceHeight*scale),
                    new RectangleF(0,sourceY,image.Width,sourceHeight),GraphicsUnit.Pixel);
                sourceY += sourceHeight;
                e.HasMorePages = sourceY < image.Height;
            };
            document.Print();
        }
    }
}
"@ -ReferencedAssemblies System.Drawing
if ($Mode -eq 'validate') { Write-Output 'Windows print adapter compiled; no document was printed.'; exit }
[SqiReceiptPrinter]::Send($Printer,$ImagePath,$PaperSize)
