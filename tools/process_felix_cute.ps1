param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not ("FelixCuteProcessor" -as [type])) {
  Add-Type -ReferencedAssemblies "System.Drawing.dll" -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class FelixCuteProcessor
{
    private const int Canvas = 362;
    private const int Baseline = 326;
    private const int MaxWidth = 334;

    private static bool IsChroma(Color c)
    {
        return c.R > 50 && c.B > 50
            && c.R - c.G > 20 && c.B - c.G > 20;
    }

    public static void WriteCell(string input, string output, int column, int row,
                                 int visibleHeight)
    {
        using (var source = new Bitmap(input))
        {
            int cellWidth = source.Width / 3;
            int cellHeight = source.Height / 2;
            int sourceX = column * cellWidth;
            int sourceY = row * cellHeight;
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

$source = Join-Path $RepoRoot "Personal assistant app mascot\felix-v2\felix-cute-v4-source.png"
$shipping = Join-Path $RepoRoot "web\public\mascot\felix-v2"
$frames = @(
  @("felix-cute-idle.png",       0, 0, 300),
  @("felix-cute-surprise-a.png", 1, 0, 320),
  @("felix-cute-surprise-b.png", 2, 0, 320),
  @("felix-cute-walk-a.png",     0, 1, 300),
  @("felix-cute-walk-b.png",     1, 1, 300),
  @("felix-cute-success.png",    2, 1, 300)
)

foreach ($frame in $frames) {
  [FelixCuteProcessor]::WriteCell(
    $source, (Join-Path $shipping $frame[0]),
    [int]$frame[1], [int]$frame[2], [int]$frame[3])
}

Write-Output "Wrote six cute Felix v4 frames."
