using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

var options = CaptureOptions.Parse(args);
if (!options.IsValid(out var validationError))
{
    Console.Error.WriteLine(validationError);
    CaptureOptions.PrintUsage();
    return 1;
}

if (!OperatingSystem.IsWindows() && !options.DemoMode)
{
    Console.Error.WriteLine("Live capture currently supports Windows only. Use --demo on other platforms.");
    return 1;
}

var samples = options.DemoMode
    ? DemoScenario.BuildSamples(options)
    : await WindowSampler.CaptureAsync(options);

if (samples.Count == 0)
{
    Console.Error.WriteLine("No foreground samples were collected.");
    return 1;
}

var report = FocusAuditReport.Build(samples, options);
var consoleLines = MarkdownReportWriter.BuildConsoleSummary(report);
foreach (var line in consoleLines)
{
    Console.WriteLine(line);
}

if (!string.IsNullOrWhiteSpace(options.MarkdownOut))
{
    var markdownPath = Path.GetFullPath(options.MarkdownOut);
    Directory.CreateDirectory(Path.GetDirectoryName(markdownPath) ?? Directory.GetCurrentDirectory());
    await File.WriteAllTextAsync(markdownPath, MarkdownReportWriter.BuildMarkdown(report));
    Console.WriteLine($"Markdown report written to {markdownPath}");
}

if (!string.IsNullOrWhiteSpace(options.JsonOut))
{
    var jsonPath = Path.GetFullPath(options.JsonOut);
    Directory.CreateDirectory(Path.GetDirectoryName(jsonPath) ?? Directory.GetCurrentDirectory());
    var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
    await File.WriteAllTextAsync(jsonPath, json);
    Console.WriteLine($"JSON report written to {jsonPath}");
}

return 0;

internal sealed record CaptureOptions(
    int DurationSeconds,
    int IntervalMs,
    int ShortSwitchSeconds,
    bool DemoMode,
    bool IgnoreDesktop,
    string? MarkdownOut,
    string? JsonOut)
{
    public static CaptureOptions Parse(string[] args)
    {
        var values = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index += 1)
        {
            var token = args[index];
            if (!token.StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }

            var key = token[2..];
            if (index + 1 < args.Length && !args[index + 1].StartsWith("--", StringComparison.Ordinal))
            {
                values[key] = args[index + 1];
                index += 1;
            }
            else
            {
                values[key] = "true";
            }
        }

        return new CaptureOptions(
            DurationSeconds: ReadInt(values, "duration-seconds", 180),
            IntervalMs: ReadInt(values, "interval-ms", 1000),
            ShortSwitchSeconds: ReadInt(values, "short-switch-seconds", 15),
            DemoMode: ReadBool(values, "demo"),
            IgnoreDesktop: !values.TryGetValue("include-desktop", out var includeDesktopValue) || !ReadBool(includeDesktopValue),
            MarkdownOut: values.TryGetValue("markdown-out", out var markdownOut) ? markdownOut : null,
            JsonOut: values.TryGetValue("json-out", out var jsonOut) ? jsonOut : null
        );
    }

    public bool IsValid(out string error)
    {
        if (DurationSeconds <= 0)
        {
            error = "--duration-seconds must be positive.";
            return false;
        }

        if (IntervalMs is < 200 or > 10000)
        {
            error = "--interval-ms must be between 200 and 10000.";
            return false;
        }

        if (ShortSwitchSeconds <= 0)
        {
            error = "--short-switch-seconds must be positive.";
            return false;
        }

        error = string.Empty;
        return true;
    }

    public static void PrintUsage()
    {
        Console.WriteLine("""
Usage:
  dotnet run -- --duration-seconds 120 --interval-ms 1000 --markdown-out reports/session.md --json-out reports/session.json
  dotnet run -- --demo --markdown-out reports/demo.md --json-out reports/demo.json

Options:
  --duration-seconds <n>     Capture length for live sampling. Default: 180
  --interval-ms <n>          Sampling interval in milliseconds. Default: 1000
  --short-switch-seconds <n> Threshold for rapid context switches. Default: 15
  --demo                     Use a built-in synthetic session instead of live sampling
  --include-desktop          Keep desktop/empty-title samples instead of filtering them
  --markdown-out <path>      Write a Markdown report
  --json-out <path>          Write a JSON report
""");
    }

    private static int ReadInt(IDictionary<string, string?> values, string key, int fallback) =>
        values.TryGetValue(key, out var raw) && int.TryParse(raw, out var parsed) ? parsed : fallback;

    private static bool ReadBool(IDictionary<string, string?> values, string key) =>
        values.TryGetValue(key, out var raw) && ReadBool(raw);

    private static bool ReadBool(string? raw) =>
        string.Equals(raw, "true", StringComparison.OrdinalIgnoreCase)
        || string.Equals(raw, "1", StringComparison.OrdinalIgnoreCase)
        || string.Equals(raw, "yes", StringComparison.OrdinalIgnoreCase);
}

internal sealed record WindowSample(
    DateTime TimestampUtc,
    string ProcessName,
    string WindowTitle,
    string ExecutablePath,
    int DurationMs);

internal sealed record FocusSegment(
    DateTime StartedAtUtc,
    DateTime EndedAtUtc,
    string ProcessName,
    string WindowTitle,
    string ExecutablePath,
    int DurationMs)
{
    public double DurationSeconds => DurationMs / 1000.0;
}

internal sealed record DurationShare(string Name, int DurationMs, double SharePct);

internal sealed record RapidSwitch(DateTime StartedAtUtc, string ProcessName, string WindowTitle, double DurationSeconds);

internal sealed record FocusAuditSummary(
    string CaptureMode,
    DateTime StartedAtUtc,
    DateTime EndedAtUtc,
    double TotalMinutes,
    int SampleCount,
    int SegmentCount,
    int ContextSwitches,
    int UniqueProcesses,
    int UniqueWindows,
    double LongestFocusSeconds,
    double AverageSegmentSeconds,
    double SwitchesPerHour,
    string FocusVerdict,
    string FocusCue);

internal sealed record FocusAuditReport(
    FocusAuditSummary Summary,
    IReadOnlyList<DurationShare> TopProcesses,
    IReadOnlyList<DurationShare> TopWindows,
    IReadOnlyList<RapidSwitch> RapidSwitches,
    IReadOnlyList<FocusSegment> Segments)
{
    public static FocusAuditReport Build(IReadOnlyList<WindowSample> samples, CaptureOptions options)
    {
        var ordered = samples.OrderBy(sample => sample.TimestampUtc).ToList();
        var segments = SegmentBuilder.Build(ordered);
        var totalDurationMs = Math.Max(segments.Sum(segment => segment.DurationMs), options.IntervalMs);
        var totalMinutes = totalDurationMs / 60000.0;
        var contextSwitches = Math.Max(0, segments.Count - 1);
        var longestFocusSeconds = segments.Count == 0 ? 0 : segments.Max(segment => segment.DurationSeconds);
        var averageSegmentSeconds = segments.Count == 0 ? 0 : segments.Average(segment => segment.DurationSeconds);
        var switchesPerHour = totalDurationMs == 0 ? 0 : contextSwitches / (totalDurationMs / 3600000.0);
        var rapidSwitches = segments
            .Where(segment => segment.DurationSeconds <= options.ShortSwitchSeconds)
            .Select(segment => new RapidSwitch(segment.StartedAtUtc, segment.ProcessName, segment.WindowTitle, Math.Round(segment.DurationSeconds, 1)))
            .Take(8)
            .ToList();

        var summary = new FocusAuditSummary(
            CaptureMode: options.DemoMode ? "demo" : "live",
            StartedAtUtc: ordered.First().TimestampUtc,
            EndedAtUtc: ordered.Last().TimestampUtc.AddMilliseconds(options.IntervalMs),
            TotalMinutes: Math.Round(totalMinutes, 2),
            SampleCount: ordered.Count,
            SegmentCount: segments.Count,
            ContextSwitches: contextSwitches,
            UniqueProcesses: ordered.Select(sample => sample.ProcessName).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            UniqueWindows: ordered.Select(sample => $"{sample.ProcessName}|{sample.WindowTitle}").Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            LongestFocusSeconds: Math.Round(longestFocusSeconds, 1),
            AverageSegmentSeconds: Math.Round(averageSegmentSeconds, 1),
            SwitchesPerHour: Math.Round(switchesPerHour, 1),
            FocusVerdict: FocusVerdict(averageSegmentSeconds, switchesPerHour, rapidSwitches.Count),
            FocusCue: FocusCue(segments, rapidSwitches)
        );

        return new FocusAuditReport(
            summary,
            TopProcesses: Summaries.TopShares(segments, segment => segment.ProcessName, totalDurationMs, 6),
            TopWindows: Summaries.TopShares(segments, segment => $"{segment.ProcessName} | {segment.WindowTitle}", totalDurationMs, 8),
            RapidSwitches: rapidSwitches,
            Segments: segments
        );
    }

    private static string FocusVerdict(double averageSegmentSeconds, double switchesPerHour, int rapidSwitchCount)
    {
        if (averageSegmentSeconds >= 600 && switchesPerHour <= 8)
        {
            return "Deep-work friendly";
        }

        if (rapidSwitchCount >= 6 || switchesPerHour >= 20)
        {
            return "Highly fragmented";
        }

        return "Mixed posture";
    }

    private static string FocusCue(IReadOnlyList<FocusSegment> segments, IReadOnlyList<RapidSwitch> rapidSwitches)
    {
        var topSegment = segments.OrderByDescending(segment => segment.DurationMs).FirstOrDefault();
        if (topSegment is null)
        {
            return "No dominant work block was captured.";
        }

        if (rapidSwitches.Count >= 4)
        {
            return $"Short-switch churn is high. Protect the {topSegment.ProcessName} block by batching quick detours before or after it.";
        }

        return $"The strongest uninterrupted block was {topSegment.DurationSeconds:F1}s in {topSegment.ProcessName}. Use that window shape as the template for future focused sessions.";
    }
}

internal static class SegmentBuilder
{
    public static List<FocusSegment> Build(IReadOnlyList<WindowSample> orderedSamples)
    {
        var segments = new List<FocusSegment>();
        if (orderedSamples.Count == 0)
        {
            return segments;
        }

        var first = orderedSamples[0];
        var currentStart = first.TimestampUtc;
        var currentDuration = first.DurationMs;
        var currentProcess = first.ProcessName;
        var currentTitle = first.WindowTitle;
        var currentPath = first.ExecutablePath;

        for (var index = 1; index < orderedSamples.Count; index += 1)
        {
            var sample = orderedSamples[index];
            var sameWindow =
                string.Equals(sample.ProcessName, currentProcess, StringComparison.OrdinalIgnoreCase)
                && string.Equals(sample.WindowTitle, currentTitle, StringComparison.Ordinal)
                && string.Equals(sample.ExecutablePath, currentPath, StringComparison.OrdinalIgnoreCase);

            if (sameWindow)
            {
                currentDuration += sample.DurationMs;
                continue;
            }

            segments.Add(new FocusSegment(
                currentStart,
                currentStart.AddMilliseconds(currentDuration),
                currentProcess,
                currentTitle,
                currentPath,
                currentDuration));

            currentStart = sample.TimestampUtc;
            currentDuration = sample.DurationMs;
            currentProcess = sample.ProcessName;
            currentTitle = sample.WindowTitle;
            currentPath = sample.ExecutablePath;
        }

        segments.Add(new FocusSegment(
            currentStart,
            currentStart.AddMilliseconds(currentDuration),
            currentProcess,
            currentTitle,
            currentPath,
            currentDuration));

        return segments;
    }
}

internal static class Summaries
{
    public static IReadOnlyList<DurationShare> TopShares(
        IReadOnlyList<FocusSegment> segments,
        Func<FocusSegment, string> selector,
        int totalDurationMs,
        int take)
    {
        return segments
            .GroupBy(selector, StringComparer.OrdinalIgnoreCase)
            .Select(group => new DurationShare(
                group.Key,
                group.Sum(segment => segment.DurationMs),
                Math.Round(group.Sum(segment => segment.DurationMs) * 100.0 / Math.Max(totalDurationMs, 1), 1)))
            .OrderByDescending(item => item.DurationMs)
            .Take(take)
            .ToList();
    }
}

internal static class DemoScenario
{
    public static List<WindowSample> BuildSamples(CaptureOptions options)
    {
        var start = DateTime.UtcNow.Date.AddHours(14);
        var plan = new (string Process, string Title, string Path, int Seconds)[]
        {
            ("Code", "feature-import-validation - Data Structures Visualizer", @"C:\Apps\Code.exe", 900),
            ("chrome", "Stack Overflow - import clipboard react", @"C:\Apps\chrome.exe", 45),
            ("Code", "feature-import-validation - Data Structures Visualizer", @"C:\Apps\Code.exe", 660),
            ("Discord", "OpenAI server thread", @"C:\Apps\Discord.exe", 25),
            ("Code", "focus-window-audit - Program.cs", @"C:\Apps\Code.exe", 780),
            ("chrome", "GitHub - abhikhur27/abhikhur27.github.io", @"C:\Apps\chrome.exe", 85),
            ("WindowsTerminal", "PowerShell - dotnet build", @"C:\Apps\wt.exe", 210),
            ("Code", "focus-window-audit - README.md", @"C:\Apps\Code.exe", 720),
        };

        var samples = new List<WindowSample>();
        foreach (var block in plan)
        {
            var ticks = Math.Max(1, (block.Seconds * 1000) / options.IntervalMs);
            for (var index = 0; index < ticks; index += 1)
            {
                samples.Add(new WindowSample(start, block.Process, block.Title, block.Path, options.IntervalMs));
                start = start.AddMilliseconds(options.IntervalMs);
            }
        }

        return samples;
    }
}

internal static class WindowSampler
{
    public static async Task<List<WindowSample>> CaptureAsync(CaptureOptions options)
    {
        var samples = new List<WindowSample>();
        using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(options.IntervalMs));
        var startedAt = DateTime.UtcNow;
        var endsAt = startedAt.AddSeconds(options.DurationSeconds);

        while (DateTime.UtcNow < endsAt)
        {
            var sample = TryReadForegroundWindow(options.IntervalMs);
            if (sample is not null && (!options.IgnoreDesktop || !IsDesktopLike(sample)))
            {
                samples.Add(sample);
            }

            if (!await timer.WaitForNextTickAsync())
            {
                break;
            }
        }

        return samples;
    }

    private static bool IsDesktopLike(WindowSample sample) =>
        string.IsNullOrWhiteSpace(sample.WindowTitle)
        || string.Equals(sample.ProcessName, "explorer", StringComparison.OrdinalIgnoreCase) && sample.WindowTitle == "Program Manager";

    private static WindowSample? TryReadForegroundWindow(int intervalMs)
    {
        var handle = NativeMethods.GetForegroundWindow();
        if (handle == IntPtr.Zero || !NativeMethods.IsWindowVisible(handle))
        {
            return null;
        }

        var title = NativeMethods.ReadWindowTitle(handle);
        NativeMethods.GetWindowThreadProcessId(handle, out var processId);
        if (processId == 0)
        {
            return null;
        }

        try
        {
            using var process = Process.GetProcessById((int)processId);
            var processName = process.ProcessName;
            var executablePath = SafeProcessPath(process);
            var normalizedTitle = string.IsNullOrWhiteSpace(title) ? "(untitled window)" : title.Trim();
            return new WindowSample(DateTime.UtcNow, processName, normalizedTitle, executablePath, intervalMs);
        }
        catch
        {
            return null;
        }
    }

    private static string SafeProcessPath(Process process)
    {
        try
        {
            return process.MainModule?.FileName ?? process.ProcessName;
        }
        catch
        {
            return process.ProcessName;
        }
    }
}

internal static class MarkdownReportWriter
{
    public static IReadOnlyList<string> BuildConsoleSummary(FocusAuditReport report)
    {
        return new[]
        {
            "Focus Window Audit",
            $"Mode: {report.Summary.CaptureMode}",
            $"Verdict: {report.Summary.FocusVerdict}",
            $"Window span: {report.Summary.TotalMinutes:F2} minutes",
            $"Context switches: {report.Summary.ContextSwitches} ({report.Summary.SwitchesPerHour:F1}/hr)",
            $"Longest uninterrupted block: {report.Summary.LongestFocusSeconds:F1}s",
            $"Cue: {report.Summary.FocusCue}",
            $"Top process: {report.TopProcesses.FirstOrDefault()?.Name ?? "n/a"}",
        };
    }

    public static string BuildMarkdown(FocusAuditReport report)
    {
        var lines = new List<string>
        {
            "# Focus Window Audit",
            "",
            $"- Mode: {report.Summary.CaptureMode}",
            $"- Started (UTC): {report.Summary.StartedAtUtc:O}",
            $"- Ended (UTC): {report.Summary.EndedAtUtc:O}",
            $"- Total minutes: {report.Summary.TotalMinutes:F2}",
            $"- Samples: {report.Summary.SampleCount}",
            $"- Segments: {report.Summary.SegmentCount}",
            $"- Context switches: {report.Summary.ContextSwitches}",
            $"- Unique processes: {report.Summary.UniqueProcesses}",
            $"- Unique windows: {report.Summary.UniqueWindows}",
            $"- Longest focus block: {report.Summary.LongestFocusSeconds:F1}s",
            $"- Average segment: {report.Summary.AverageSegmentSeconds:F1}s",
            $"- Switches per hour: {report.Summary.SwitchesPerHour:F1}",
            $"- Verdict: {report.Summary.FocusVerdict}",
            "",
            "## Focus Cue",
            "",
            report.Summary.FocusCue,
            "",
            "## Top Processes",
            "",
        };

        lines.AddRange(report.TopProcesses.Select(item =>
            $"- {item.Name}: {FormatDuration(item.DurationMs)} ({item.SharePct:F1}%)"));

        lines.Add("");
        lines.Add("## Top Windows");
        lines.Add("");
        lines.AddRange(report.TopWindows.Select(item =>
            $"- {item.Name}: {FormatDuration(item.DurationMs)} ({item.SharePct:F1}%)"));

        lines.Add("");
        lines.Add("## Rapid Switches");
        lines.Add("");
        if (report.RapidSwitches.Count == 0)
        {
            lines.Add("- No rapid context switches crossed the configured threshold.");
        }
        else
        {
            lines.AddRange(report.RapidSwitches.Select(item =>
                $"- {item.StartedAtUtc:HH:mm:ss} UTC | {item.ProcessName} | {item.WindowTitle} | {item.DurationSeconds:F1}s"));
        }

        lines.Add("");
        lines.Add("## Focus Segments");
        lines.Add("");
        lines.AddRange(report.Segments.Select(segment =>
            $"- {segment.StartedAtUtc:HH:mm:ss} -> {segment.EndedAtUtc:HH:mm:ss} UTC | {segment.ProcessName} | {segment.WindowTitle} | {FormatDuration(segment.DurationMs)}"));

        return string.Join(Environment.NewLine, lines) + Environment.NewLine;
    }

    private static string FormatDuration(int durationMs)
    {
        var span = TimeSpan.FromMilliseconds(durationMs);
        if (span.TotalMinutes >= 1)
        {
            return $"{span.Minutes:D2}m {span.Seconds:D2}s";
        }

        return $"{span.Seconds:D2}s";
    }
}

internal static partial class NativeMethods
{
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetWindowTextLengthW(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    public static string ReadWindowTitle(IntPtr hWnd)
    {
        var length = GetWindowTextLengthW(hWnd);
        if (length <= 0)
        {
            return string.Empty;
        }

        var builder = new StringBuilder(length + 1);
        _ = GetWindowTextW(hWnd, builder, builder.Capacity);
        return builder.ToString();
    }
}
