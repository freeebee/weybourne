param(
  [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not ("FelixSpriteProcessor" -as [type])) {
  Add-Type -ReferencedAssemblies "System.Drawing.dll" -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class FelixSpriteProcessor
{
    private const int Canvas = 362;
    private const int Baseline = 326;
    private const int MaxWidth = 334;

    private static bool IsChroma(Color c)
    {
        // Generated pixel sheets use magenta as a removable key. Include the
        // darker edge blends as well as the flat field so no pink halo ships.
        return c.R > 50 && c.B > 50
            && c.R - c.G > 20 && c.B - c.G > 20;
    }

    public static void WritePair(string input, string outputA, string outputB,
                                 int visibleHeight)
    {
        using (var source = new Bitmap(input))
        {
            int cellWidth = source.Width / 2;
            WriteCell(source, 0, cellWidth, outputA, visibleHeight);
            WriteCell(source, cellWidth, source.Width - cellWidth,
                      outputB, visibleHeight);
        }
    }

    private static void WriteCell(Bitmap source, int sourceX, int cellWidth,
                                  string output, int visibleHeight)
    {
        using (var keyed = new Bitmap(cellWidth, source.Height,
                                      PixelFormat.Format32bppArgb))
        {
            int minX = cellWidth, minY = source.Height, maxX = -1, maxY = -1;
            for (int y = 0; y < source.Height; y++)
            {
                for (int x = 0; x < cellWidth; x++)
                {
                    Color pixel = source.GetPixel(sourceX + x, y);
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
                throw new InvalidOperationException("No sprite pixels found in " + inputName(output));

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

    private static string inputName(string path)
    {
        return System.IO.Path.GetFileName(path);
    }
}
'@
}

$master = Join-Path $RepoRoot "Personal assistant app mascot\felix-v2"
$shipping = Join-Path $RepoRoot "web\public\mascot\felix-v2"

[FelixSpriteProcessor]::WritePair(
  (Join-Path $master "felix-contacts-v3-source.png"),
  (Join-Path $shipping "felix-contacts-v3-a.png"),
  (Join-Path $shipping "felix-contacts-v3-b.png"), 330)

[FelixSpriteProcessor]::WritePair(
  (Join-Path $master "felix-notes-v3-source.png"),
  (Join-Path $shipping "felix-notes-v3-a.png"),
  (Join-Path $shipping "felix-notes-v3-b.png"), 300)

[FelixSpriteProcessor]::WritePair(
  (Join-Path $master "felix-research-v3-source.png"),
  (Join-Path $shipping "felix-research-v3-a.png"),
  (Join-Path $shipping "felix-research-v3-b.png"), 300)

Write-Output "Wrote six Felix v3 action frames."
