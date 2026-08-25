param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not ("Felix8BitV7Processor" -as [type])) {
  Add-Type -ReferencedAssemblies "System.Drawing.dll" -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class Felix8BitV7Processor
{
    private const int Canvas = 362;
    private const int Baseline = 326;
    private const int MaxWidth = 346;

    private static bool IsChroma(Color c)
    {
        // Include the dark magenta edge pixels produced where the generated
        // chroma plate met Felix's black outline. Felix's palette has no
        // purple, so a low threshold removes that fringe without touching
        // the navy uniform, brown hair, skin, or grey tools.
        return c.R > 15 && c.B > 15
            && c.R - c.G > 8 && c.B - c.G > 8;
    }

    public static void WriteCell(string input, string output, int columns,
                                 int rows, int column, int row,
                                 int visibleHeight)
    {
        using (var source = new Bitmap(input))
        {
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

$movementSource = Join-Path $sourceDir "felix-8bit-v7-movement-source.png"
$movementFrames = @(
  @("felix-8bit-v7-idle.png",       0, 0, 300),
  @("felix-8bit-v7-notice-a.png",   1, 0, 300),
  @("felix-8bit-v7-notice-b.png",   2, 0, 300),
  @("felix-8bit-v7-walk-a.png",     0, 1, 300),
  @("felix-8bit-v7-walk-b.png",     1, 1, 300),
  @("felix-8bit-v7-success.png",    2, 1, 300)
)

foreach ($frame in $movementFrames) {
  [Felix8BitV7Processor]::WriteCell(
    $movementSource, (Join-Path $shipping $frame[0]), 3, 2,
    [int]$frame[1], [int]$frame[2], [int]$frame[3])
}

$workSource = Join-Path $sourceDir "felix-8bit-v7-work-source.png"
$workFrames = @(
  @("felix-8bit-v7-repair-a.png",   0, 0, 294),
  @("felix-8bit-v7-repair-b.png",   1, 0, 294),
  @("felix-8bit-v7-contacts-a.png", 2, 0, 316),
  @("felix-8bit-v7-contacts-b.png", 3, 0, 316),
  @("felix-8bit-v7-notes-a.png",    0, 1, 286),
  @("felix-8bit-v7-notes-b.png",    1, 1, 286),
  @("felix-8bit-v7-research-a.png", 2, 1, 286),
  @("felix-8bit-v7-research-b.png", 3, 1, 286)
)

foreach ($frame in $workFrames) {
  [Felix8BitV7Processor]::WriteCell(
    $workSource, (Join-Path $shipping $frame[0]), 4, 2,
    [int]$frame[1], [int]$frame[2], [int]$frame[3])
}

Write-Output "Wrote fourteen Felix 8-bit v7 frames."
