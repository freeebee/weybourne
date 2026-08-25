param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not ("FelixV5Processor" -as [type])) {
  Add-Type -ReferencedAssemblies "System.Drawing.dll" -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class FelixV5Processor
{
    private const int Canvas = 362;
    private const int Baseline = 326;
    private const int MaxWidth = 346;

    private static bool IsChroma(Color c)
    {
        return c.R > 50 && c.B > 50
            && c.R - c.G > 20 && c.B - c.G > 20;
    }

    public static void WriteCell(string input, string output, int columns,
                                 int rows, int column, int row,
                                 int visibleHeight)
    {
        using (var source = new Bitmap(input))
        {
            // Generated sheets are not always evenly divisible by their grid.
            // Rounded proportional edges preserve every pixel without letting
            // one cell bleed into its neighbour.
            int sourceX = (int)Math.Round(column * source.Width / (double)columns);
            int sourceY = (int)Math.Round(row * source.Height / (double)rows);
            int sourceRight = (int)Math.Round((column + 1) * source.Width / (double)columns);
            int sourceBottom = (int)Math.Round((row + 1) * source.Height / (double)rows);
            int cellWidth = sourceRight - sourceX;
            int cellHeight = sourceBottom - sourceY;

            using (var keyed = new Bitmap(cellWidth, cellHeight,
                                          PixelFormat.Format32bppArgb))
            {
                int minX = cellWidth, minY = cellHeight, maxX = -1, maxY = -1;
                for (int y = 0; y < cellHeight; y++)
                {
                    for (int x = 0; x < cellWidth; x++)
                    {
                        Color pixel = source.GetPixel(sourceX + x, sourceY + y);
                        if (IsChroma(pixel))
                        {
                            keyed.SetPixel(x, y, Color.Transparent);
                            continue;
                        }

                        keyed.SetPixel(x, y, Color.FromArgb(255, pixel.R, pixel.G, pixel.B));
                        minX = Math.Min(minX, x);
                        minY = Math.Min(minY, y);
                        maxX = Math.Max(maxX, x);
                        maxY = Math.Max(maxY, y);
                    }
                }

                if (maxX < minX || maxY < minY)
                    throw new InvalidOperationException("No sprite pixels found in " + output);

                var crop = Rectangle.FromLTRB(minX, minY, maxX + 1, maxY + 1);
                double scale = Math.Min((double)visibleHeight / crop.Height,
                                        (double)MaxWidth / crop.Width);
                int width = Math.Max(1, (int)Math.Round(crop.Width * scale));
                int height = Math.Max(1, (int)Math.Round(crop.Height * scale));
                int left = (Canvas - width) / 2;
                int top = Baseline - height;

                using (var result = new Bitmap(Canvas, Canvas, PixelFormat.Format32bppArgb))
                using (Graphics graphics = Graphics.FromImage(result))
                {
                    graphics.Clear(Color.Transparent);
                    graphics.CompositingMode = CompositingMode.SourceCopy;
                    graphics.InterpolationMode = InterpolationMode.NearestNeighbor;
                    graphics.PixelOffsetMode = PixelOffsetMode.Half;
                    graphics.SmoothingMode = SmoothingMode.None;
                    graphics.DrawImage(keyed, new Rectangle(left, top, width, height),
                                       crop, GraphicsUnit.Pixel);
                    result.Save(output, ImageFormat.Png);
                }
            }
        }
    }
}
'@
}

$sourceDir = Join-Path $RepoRoot "Personal assistant app mascot\felix-v2"
$shipping = Join-Path $RepoRoot "web\public\mascot\felix-v2"

$workSource = Join-Path $sourceDir "felix-cute-work-v5-source.png"
$workFrames = @(
  @("felix-cute-repair-a.png",   0, 0, 294),
  @("felix-cute-repair-b.png",   1, 0, 294),
  @("felix-cute-contacts-a.png", 2, 0, 316),
  @("felix-cute-contacts-b.png", 3, 0, 316),
  @("felix-cute-notes-a.png",    0, 1, 286),
  @("felix-cute-notes-b.png",    1, 1, 286),
  @("felix-cute-research-a.png", 2, 1, 286),
  @("felix-cute-research-b.png", 3, 1, 286)
)

foreach ($frame in $workFrames) {
  [FelixV5Processor]::WriteCell(
    $workSource, (Join-Path $shipping $frame[0]), 4, 2,
    [int]$frame[1], [int]$frame[2], [int]$frame[3])
}

$noticeSource = Join-Path $sourceDir "felix-cute-notice-v5-source.png"
$noticeFrames = @(
  @("felix-cute-notice-a.png", 0, 0, 300),
  @("felix-cute-notice-b.png", 1, 0, 300)
)

foreach ($frame in $noticeFrames) {
  [FelixV5Processor]::WriteCell(
    $noticeSource, (Join-Path $shipping $frame[0]), 2, 1,
    [int]$frame[1], [int]$frame[2], [int]$frame[3])
}

Write-Output "Wrote ten cute Felix v5 frames."
