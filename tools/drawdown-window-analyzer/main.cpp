#include <algorithm>
#include <cmath>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Sample {
  std::string date;
  double value = 0.0;
  long long epochDays = 0;
};

struct DrawdownWindow {
  std::string peakDate;
  std::string troughDate;
  std::string recoveryDate;
  double peakValue = 0.0;
  double troughValue = 0.0;
  double drawdownPct = 0.0;
  long long daysToTrough = 0;
  long long recoveryDays = 0;
  long long underwaterDays = 0;
  bool recovered = false;
};

struct Summary {
  std::size_t rows = 0;
  double avgDailyReturnPct = 0.0;
  double realizedVolPct = 0.0;
  DrawdownWindow worst;
  DrawdownWindow longest;
  std::vector<DrawdownWindow> topWindows;
};

struct Options {
  std::string inputPath;
  std::string markdownOut;
  std::string jsonOut;
  int topCount = 3;
  bool selfTest = false;
};

std::string trim(const std::string& value) {
  const auto start = value.find_first_not_of(" \t\r\n");
  if (start == std::string::npos) return "";
  const auto end = value.find_last_not_of(" \t\r\n");
  return value.substr(start, end - start + 1);
}

std::vector<std::string> splitCsvRow(const std::string& line) {
  std::vector<std::string> cells;
  std::string current;
  bool inQuotes = false;

  for (std::size_t index = 0; index < line.size(); index += 1) {
    const char ch = line[index];
    const char next = index + 1 < line.size() ? line[index + 1] : '\0';

    if (ch == '"') {
      if (inQuotes && next == '"') {
        current.push_back('"');
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (ch == ',' && !inQuotes) {
      cells.push_back(trim(current));
      current.clear();
      continue;
    }

    current.push_back(ch);
  }

  cells.push_back(trim(current));
  return cells;
}

long long parseEpochDays(const std::string& date) {
  if (date.size() != 10 || date[4] != '-' || date[7] != '-') {
    throw std::runtime_error("Expected ISO date YYYY-MM-DD: " + date);
  }

  std::tm tm = {};
  tm.tm_year = std::stoi(date.substr(0, 4)) - 1900;
  tm.tm_mon = std::stoi(date.substr(5, 2)) - 1;
  tm.tm_mday = std::stoi(date.substr(8, 2));
  tm.tm_hour = 12;
  const std::time_t time = std::mktime(&tm);
  if (time == -1) {
    throw std::runtime_error("Could not parse date: " + date);
  }
  return static_cast<long long>(time / 86400);
}

std::vector<Sample> readSamples(const std::string& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("Could not open input file: " + path);
  }

  std::string line;
  if (!std::getline(input, line)) {
    throw std::runtime_error("CSV is empty.");
  }

  const auto headers = splitCsvRow(line);
  int dateIndex = -1;
  int valueIndex = -1;
  for (std::size_t index = 0; index < headers.size(); index += 1) {
    const std::string lower = headers[index] == "date" ? "date" : headers[index] == "value" ? "value" : headers[index];
    if (lower == "date") dateIndex = static_cast<int>(index);
    if (lower == "value") valueIndex = static_cast<int>(index);
  }
  if (dateIndex == -1 || valueIndex == -1) {
    throw std::runtime_error("CSV header must include date,value.");
  }

  std::vector<Sample> samples;
  while (std::getline(input, line)) {
    const auto trimmed = trim(line);
    if (trimmed.empty()) continue;
    const auto cells = splitCsvRow(trimmed);
    if (dateIndex >= static_cast<int>(cells.size()) || valueIndex >= static_cast<int>(cells.size())) {
      continue;
    }

    Sample sample;
    sample.date = trim(cells[dateIndex]);
    sample.value = std::stod(trim(cells[valueIndex]));
    sample.epochDays = parseEpochDays(sample.date);
    samples.push_back(sample);
  }

  if (samples.size() < 2) {
    throw std::runtime_error("Need at least two rows to compute drawdown.");
  }

  std::sort(samples.begin(), samples.end(), [](const Sample& left, const Sample& right) {
    return left.epochDays < right.epochDays;
  });
  return samples;
}

std::vector<double> computeDailyReturns(const std::vector<Sample>& samples) {
  std::vector<double> returns;
  for (std::size_t index = 1; index < samples.size(); index += 1) {
    returns.push_back((samples[index].value / samples[index - 1].value) - 1.0);
  }
  return returns;
}

double mean(const std::vector<double>& values) {
  double total = 0.0;
  for (double value : values) total += value;
  return values.empty() ? 0.0 : total / static_cast<double>(values.size());
}

double stddev(const std::vector<double>& values) {
  if (values.size() < 2) return 0.0;
  const double avg = mean(values);
  double total = 0.0;
  for (double value : values) {
    const double delta = value - avg;
    total += delta * delta;
  }
  return std::sqrt(total / static_cast<double>(values.size() - 1));
}

Summary analyze(const std::vector<Sample>& samples, int topCount) {
  Summary summary;
  summary.rows = samples.size();

  const auto returns = computeDailyReturns(samples);
  summary.avgDailyReturnPct = mean(returns) * 100.0;
  summary.realizedVolPct = stddev(returns) * 100.0;

  double runningPeakValue = samples.front().value;
  std::string runningPeakDate = samples.front().date;
  long long runningPeakEpoch = samples.front().epochDays;
  bool underwater = false;
  DrawdownWindow currentWindow;
  std::vector<DrawdownWindow> windows;
  double worstDrawdown = 0.0;
  long long longestUnderwater = -1;

  for (const auto& sample : samples) {
    if (sample.value >= runningPeakValue) {
      if (underwater) {
        currentWindow.recoveryDate = sample.date;
        currentWindow.recovered = true;
        currentWindow.recoveryDays = sample.epochDays - parseEpochDays(currentWindow.troughDate);
        currentWindow.underwaterDays = sample.epochDays - runningPeakEpoch;
        windows.push_back(currentWindow);
        if (summary.worst.peakDate.empty() || currentWindow.drawdownPct <= summary.worst.drawdownPct + 1e-9) {
          summary.worst = currentWindow;
        }
        if (currentWindow.underwaterDays > longestUnderwater) {
          longestUnderwater = currentWindow.underwaterDays;
          summary.longest = currentWindow;
        }
        underwater = false;
      }

      runningPeakValue = sample.value;
      runningPeakDate = sample.date;
      runningPeakEpoch = sample.epochDays;
      continue;
    }

    const double drawdownPct = ((sample.value / runningPeakValue) - 1.0) * 100.0;
    if (!underwater) {
      underwater = true;
      currentWindow = {
        runningPeakDate,
        sample.date,
        "",
        runningPeakValue,
        sample.value,
        drawdownPct,
        sample.epochDays - runningPeakEpoch,
        0,
        0,
        false,
      };
    }

    if (drawdownPct < currentWindow.drawdownPct) {
      currentWindow.troughDate = sample.date;
      currentWindow.troughValue = sample.value;
      currentWindow.drawdownPct = drawdownPct;
      currentWindow.daysToTrough = sample.epochDays - runningPeakEpoch;
    }

    if (drawdownPct < worstDrawdown) {
      worstDrawdown = drawdownPct;
      summary.worst = currentWindow;
    }

    const long long currentDays = sample.epochDays - runningPeakEpoch;
    if (currentDays > longestUnderwater) {
      longestUnderwater = currentDays;
      DrawdownWindow inFlight = currentWindow;
      inFlight.underwaterDays = currentDays;
      summary.longest = inFlight;
    }
  }

  if (underwater) {
    currentWindow.daysToTrough = parseEpochDays(currentWindow.troughDate) - runningPeakEpoch;
    currentWindow.underwaterDays = samples.back().epochDays - runningPeakEpoch;
    windows.push_back(currentWindow);
    if (currentWindow.drawdownPct < worstDrawdown || summary.worst.peakDate.empty()) {
      summary.worst = currentWindow;
    }
    if (currentWindow.underwaterDays > longestUnderwater) {
      summary.longest = currentWindow;
    }
  }

  std::sort(windows.begin(), windows.end(), [](const DrawdownWindow& left, const DrawdownWindow& right) {
    if (left.drawdownPct != right.drawdownPct) return left.drawdownPct < right.drawdownPct;
    return left.underwaterDays > right.underwaterDays;
  });
  if (topCount < 1) topCount = 1;
  if (windows.size() > static_cast<std::size_t>(topCount)) {
    windows.resize(static_cast<std::size_t>(topCount));
  }
  summary.topWindows = windows;
  if (summary.worst.peakDate.empty() && !summary.topWindows.empty()) summary.worst = summary.topWindows.front();
  if (summary.longest.peakDate.empty() && !summary.topWindows.empty()) summary.longest = summary.topWindows.front();
  return summary;
}

std::string formatPct(double value) {
  std::ostringstream output;
  output << std::fixed << std::setprecision(2) << value << '%';
  return output.str();
}

std::string buildConsoleSummary(const Summary& summary) {
  std::ostringstream output;
  output << "Drawdown Window Analyzer\n";
  output << "Rows: " << summary.rows
         << " | Worst drawdown: " << formatPct(summary.worst.drawdownPct)
         << " | Longest underwater: " << summary.longest.underwaterDays << " days"
         << " | Volatility: " << formatPct(summary.realizedVolPct);
  return output.str();
}

std::string buildMarkdownReport(const Summary& summary, const std::string& inputPath) {
  std::ostringstream output;
  output << "# Drawdown Window Analyzer Report\n\n";
  output << "- Input: `" << inputPath << "`\n";
  output << "- Rows: " << summary.rows << "\n";
  output << "- Average daily return: " << formatPct(summary.avgDailyReturnPct) << "\n";
  output << "- Realized volatility: " << formatPct(summary.realizedVolPct) << "\n";
  output << "- Worst drawdown: " << formatPct(summary.worst.drawdownPct) << " from " << summary.worst.peakDate << " to " << summary.worst.troughDate << "\n";
  output << "- Days to trough in worst window: " << summary.worst.daysToTrough << "\n";
  output << "- Recovery lag in worst window: " << (summary.worst.recovered ? std::to_string(summary.worst.recoveryDays) + " days" : "Open") << "\n";
  output << "- Longest underwater stretch: " << summary.longest.underwaterDays << " days starting at " << summary.longest.peakDate << "\n\n";
  output << "## Top Drawdown Windows\n\n";
  output << "| # | Peak | Trough | Recovery | Drawdown | Days to trough | Recovery days | Underwater days |\n";
  output << "| --- | --- | --- | --- | --- | --- | --- | --- |\n";
  for (std::size_t index = 0; index < summary.topWindows.size(); index += 1) {
    const auto& row = summary.topWindows[index];
    output << "| " << index + 1
           << " | " << row.peakDate
           << " | " << row.troughDate
           << " | " << (row.recovered ? row.recoveryDate : "Open")
           << " | " << formatPct(row.drawdownPct)
           << " | " << row.daysToTrough
           << " | " << (row.recovered ? std::to_string(row.recoveryDays) : "Open")
           << " | " << row.underwaterDays
           << " |\n";
  }
  return output.str();
}

std::string buildJsonReport(const Summary& summary, const std::string& inputPath) {
  auto drawdownToJson = [](const DrawdownWindow& row) {
    std::ostringstream output;
    output << "{"
           << "\"peakDate\":\"" << row.peakDate << "\","
           << "\"troughDate\":\"" << row.troughDate << "\","
           << "\"recoveryDate\":\"" << row.recoveryDate << "\","
           << "\"peakValue\":" << std::fixed << std::setprecision(2) << row.peakValue << ","
           << "\"troughValue\":" << std::fixed << std::setprecision(2) << row.troughValue << ","
           << "\"drawdownPct\":" << std::fixed << std::setprecision(2) << row.drawdownPct << ","
           << "\"daysToTrough\":" << row.daysToTrough << ","
           << "\"recoveryDays\":" << row.recoveryDays << ","
           << "\"underwaterDays\":" << row.underwaterDays << ","
           << "\"recovered\":" << (row.recovered ? "true" : "false")
           << "}";
    return output.str();
  };

  std::ostringstream output;
  output << "{\n"
         << "  \"input\": \"" << inputPath << "\",\n"
         << "  \"rows\": " << summary.rows << ",\n"
         << "  \"avgDailyReturnPct\": " << std::fixed << std::setprecision(4) << summary.avgDailyReturnPct << ",\n"
         << "  \"realizedVolPct\": " << std::fixed << std::setprecision(4) << summary.realizedVolPct << ",\n"
         << "  \"worst\": " << drawdownToJson(summary.worst) << ",\n"
         << "  \"longest\": " << drawdownToJson(summary.longest) << ",\n"
         << "  \"topWindows\": [\n";
  for (std::size_t index = 0; index < summary.topWindows.size(); index += 1) {
    output << "    " << drawdownToJson(summary.topWindows[index]);
    if (index + 1 < summary.topWindows.size()) output << ",";
    output << "\n";
  }
  output << "  ]\n}\n";
  return output.str();
}

void writeTextFile(const std::string& path, const std::string& contents) {
  std::ofstream output(path);
  if (!output) {
    throw std::runtime_error("Could not write output file: " + path);
  }
  output << contents;
}

void printHelp() {
  std::cout
    << "Drawdown Window Analyzer\n"
    << "Usage:\n"
    << "  drawdown-window-analyzer --input <file.csv> [--top N] [--markdown-out file] [--json-out file]\n"
    << "  drawdown-window-analyzer --self-test\n";
}

Options parseArgs(int argc, char* argv[]) {
  Options options;
  for (int index = 1; index < argc; index += 1) {
    const std::string arg = argv[index];
    auto requireValue = [&](const std::string& flag) -> std::string {
      if (index + 1 >= argc) throw std::runtime_error("Missing value for " + flag);
      index += 1;
      return argv[index];
    };

    if (arg == "--input") {
      options.inputPath = requireValue(arg);
    } else if (arg == "--markdown-out") {
      options.markdownOut = requireValue(arg);
    } else if (arg == "--json-out") {
      options.jsonOut = requireValue(arg);
    } else if (arg == "--top") {
      options.topCount = std::stoi(requireValue(arg));
    } else if (arg == "--self-test") {
      options.selfTest = true;
    } else if (arg == "--help" || arg == "-h") {
      printHelp();
      std::exit(0);
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }
  return options;
}

void runSelfTest() {
  const std::vector<Sample> samples = {
    {"2026-01-01", 100.0, parseEpochDays("2026-01-01")},
    {"2026-01-02", 120.0, parseEpochDays("2026-01-02")},
    {"2026-01-03", 90.0, parseEpochDays("2026-01-03")},
    {"2026-01-04", 80.0, parseEpochDays("2026-01-04")},
    {"2026-01-05", 130.0, parseEpochDays("2026-01-05")},
  };
  const Summary summary = analyze(samples, 3);
  if (std::abs(summary.worst.drawdownPct - (-33.3333333)) > 0.05) {
    throw std::runtime_error("Self-test failed: worst drawdown mismatch.");
  }
  if (!summary.worst.recovered || summary.worst.recoveryDate != "2026-01-05") {
    throw std::runtime_error("Self-test failed: recovery detection mismatch.");
  }
  if (summary.worst.daysToTrough != 2 || summary.worst.recoveryDays != 1) {
    throw std::runtime_error("Self-test failed: timing metrics mismatch.");
  }
  std::cout << "Self-test passed.\n";
}

int main(int argc, char* argv[]) {
  try {
    const Options options = parseArgs(argc, argv);
    if (options.selfTest) {
      runSelfTest();
      return 0;
    }

    if (options.inputPath.empty()) {
      printHelp();
      return 1;
    }

    const auto samples = readSamples(options.inputPath);
    const Summary summary = analyze(samples, options.topCount);
    std::cout << buildConsoleSummary(summary) << '\n';

    if (!options.markdownOut.empty()) {
      writeTextFile(options.markdownOut, buildMarkdownReport(summary, options.inputPath));
    }
    if (!options.jsonOut.empty()) {
      writeTextFile(options.jsonOut, buildJsonReport(summary, options.inputPath));
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Error: " << error.what() << '\n';
    return 1;
  }
}
