#include <array>
#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

struct Options {
  fs::path root;
  std::size_t topCount = 12;
  int staleDays = 45;
  fs::path markdownReport;
  fs::path candidateCsv;
  bool exactDuplicateScan = false;
  std::vector<std::string> excludedDirectories;
};

struct FileEntry {
  fs::path path;
  std::uintmax_t size = 0;
  std::string extension;
  std::chrono::system_clock::time_point modifiedAt;
  double ageDays = 0.0;
};

struct ScanSummary {
  std::vector<FileEntry> files;
  std::vector<fs::path> emptyDirectories;
  std::uintmax_t totalBytes = 0;
  std::size_t directoriesVisited = 0;
};

struct CandidateRow {
  std::string reason;
  fs::path path;
  std::uintmax_t size = 0;
  std::string modifiedDate;
};

struct DirectoryFootprint {
  std::string label;
  std::uintmax_t bytes = 0;
  std::size_t fileCount = 0;
};

std::string lowerCopy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
    return static_cast<char>(std::tolower(ch));
  });
  return value;
}

std::chrono::system_clock::time_point toSystemClock(fs::file_time_type fileTime) {
  return std::chrono::time_point_cast<std::chrono::system_clock::duration>(
      fileTime - fs::file_time_type::clock::now() + std::chrono::system_clock::now());
}

std::string formatBytes(std::uintmax_t bytes) {
  static const char* suffixes[] = {"B", "KB", "MB", "GB", "TB"};
  double value = static_cast<double>(bytes);
  std::size_t suffixIndex = 0;
  while (value >= 1024.0 && suffixIndex + 1 < std::size(suffixes)) {
    value /= 1024.0;
    ++suffixIndex;
  }

  std::ostringstream output;
  output << std::fixed << std::setprecision(value >= 100.0 ? 0 : value >= 10.0 ? 1 : 2) << value << " " << suffixes[suffixIndex];
  return output.str();
}

std::string formatDate(const std::chrono::system_clock::time_point& timePoint) {
  const std::time_t raw = std::chrono::system_clock::to_time_t(timePoint);
  std::tm localTime {};
#ifdef _WIN32
  localtime_s(&localTime, &raw);
#else
  localtime_r(&raw, &localTime);
#endif
  std::ostringstream output;
  output << std::put_time(&localTime, "%Y-%m-%d");
  return output.str();
}

std::string csvEscape(const std::string& value) {
  std::string escaped = "\"";
  for (const char ch : value) {
    if (ch == '"') {
      escaped += "\"\"";
    } else {
      escaped.push_back(ch);
    }
  }
  escaped.push_back('"');
  return escaped;
}

void printUsage() {
  std::cout
      << "Folder Triage CLI\n"
      << "Usage:\n"
      << "  folder-triage-cli <root> [--top N] [--stale-days N] [--report path] [--csv path] [--exact-duplicates] [--exclude-dir NAME]\n\n"
      << "Examples:\n"
      << "  folder-triage-cli C:\\Users\\abhim\\Downloads --top 15 --stale-days 60\n"
      << "  folder-triage-cli . --report triage.md --csv candidates.csv --exact-duplicates --exclude-dir node_modules\n";
}

Options parseArgs(int argc, char** argv) {
  if (argc < 2) {
    printUsage();
    throw std::runtime_error("Missing required root path.");
  }

  Options options;
  options.root = fs::path(argv[1]);

  for (int index = 2; index < argc; ++index) {
    const std::string arg = argv[index];
    auto requireValue = [&](const std::string& flag) -> std::string {
      if (index + 1 >= argc) {
        throw std::runtime_error("Missing value for " + flag);
      }
      return argv[++index];
    };

    if (arg == "--top") {
      options.topCount = static_cast<std::size_t>(std::stoul(requireValue(arg)));
    } else if (arg == "--stale-days") {
      options.staleDays = std::stoi(requireValue(arg));
    } else if (arg == "--report") {
      options.markdownReport = fs::path(requireValue(arg));
    } else if (arg == "--csv") {
      options.candidateCsv = fs::path(requireValue(arg));
    } else if (arg == "--exact-duplicates") {
      options.exactDuplicateScan = true;
    } else if (arg == "--exclude-dir") {
      options.excludedDirectories.push_back(lowerCopy(requireValue(arg)));
    } else if (arg == "--help" || arg == "-h") {
      printUsage();
      std::exit(0);
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }

  if (options.topCount == 0) {
    throw std::runtime_error("--top must be at least 1.");
  }
  if (options.staleDays < 0) {
    throw std::runtime_error("--stale-days cannot be negative.");
  }

  return options;
}

bool shouldExcludeDirectory(const Options& options, const fs::path& path) {
  const std::string name = lowerCopy(path.filename().string());
  for (const auto& excluded : options.excludedDirectories) {
    if (name == excluded) {
      return true;
    }
  }
  return false;
}

ScanSummary scanTree(const Options& options) {
  if (!fs::exists(options.root)) {
    throw std::runtime_error("Root path does not exist: " + options.root.string());
  }
  if (!fs::is_directory(options.root)) {
    throw std::runtime_error("Root path must be a directory: " + options.root.string());
  }

  ScanSummary summary;
  const auto now = std::chrono::system_clock::now();
  const fs::directory_options dirOptions = fs::directory_options::skip_permission_denied;

  for (fs::recursive_directory_iterator iterator(options.root, dirOptions), end; iterator != end; ++iterator) {
    const auto& entry = *iterator;
    std::error_code ec;
    if (entry.is_directory(ec)) {
      if (shouldExcludeDirectory(options, entry.path())) {
        iterator.disable_recursion_pending();
        continue;
      }
      ++summary.directoriesVisited;
      const auto begin = fs::directory_iterator(entry.path(), dirOptions, ec);
      if (!ec && begin == fs::directory_iterator()) {
        summary.emptyDirectories.push_back(entry.path());
      }
      continue;
    }
    if (!entry.is_regular_file(ec)) {
      continue;
    }

    FileEntry file;
    file.path = entry.path();
    file.size = entry.file_size(ec);
    if (ec) {
      file.size = 0;
    }
    file.extension = lowerCopy(entry.path().extension().string());
    if (file.extension.empty()) {
      file.extension = "[no extension]";
    }
    file.modifiedAt = toSystemClock(entry.last_write_time(ec));
    file.ageDays = std::chrono::duration<double, std::ratio<86400>>(now - file.modifiedAt).count();

    summary.totalBytes += file.size;
    summary.files.push_back(std::move(file));
  }

  return summary;
}

std::vector<FileEntry> topLargest(const std::vector<FileEntry>& files, std::size_t limit) {
  std::vector<FileEntry> ranked = files;
  std::sort(ranked.begin(), ranked.end(), [](const FileEntry& left, const FileEntry& right) {
    return left.size > right.size;
  });
  if (ranked.size() > limit) {
    ranked.resize(limit);
  }
  return ranked;
}

std::string fingerprintFile(const fs::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    return "";
  }

  constexpr std::uint64_t offsetBasis = 14695981039346656037ull;
  constexpr std::uint64_t prime = 1099511628211ull;
  std::uint64_t hash = offsetBasis;
  std::array<char, 8192> buffer {};

  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = input.gcount();
    for (std::streamsize index = 0; index < count; ++index) {
      hash ^= static_cast<unsigned char>(buffer[static_cast<std::size_t>(index)]);
      hash *= prime;
    }
  }

  std::ostringstream output;
  output << std::hex << std::setw(16) << std::setfill('0') << hash;
  return output.str();
}

std::vector<FileEntry> staleFiles(const std::vector<FileEntry>& files, int staleDays, std::size_t limit) {
  std::vector<FileEntry> ranked;
  for (const auto& file : files) {
    if (file.ageDays >= staleDays) {
      ranked.push_back(file);
    }
  }
  std::sort(ranked.begin(), ranked.end(), [](const FileEntry& left, const FileEntry& right) {
    if (left.ageDays != right.ageDays) {
      return left.ageDays > right.ageDays;
    }
    return left.size > right.size;
  });
  if (ranked.size() > limit) {
    ranked.resize(limit);
  }
  return ranked;
}

std::vector<std::pair<std::string, std::vector<FileEntry>>> probableDuplicateGroups(
    const std::vector<FileEntry>& files,
    std::size_t limit) {
  std::unordered_map<std::string, std::vector<FileEntry>> grouped;
  for (const auto& file : files) {
    const std::string filename = lowerCopy(file.path.filename().string());
    const std::string key = filename + "|" + std::to_string(file.size);
    grouped[key].push_back(file);
  }

  std::vector<std::pair<std::string, std::vector<FileEntry>>> duplicates;
  for (auto& pair : grouped) {
    if (pair.second.size() > 1) {
      std::sort(pair.second.begin(), pair.second.end(), [](const FileEntry& left, const FileEntry& right) {
        return left.ageDays > right.ageDays;
      });
      duplicates.push_back({pair.first, pair.second});
    }
  }

  std::sort(duplicates.begin(), duplicates.end(), [](const auto& left, const auto& right) {
    if (left.second.size() != right.second.size()) {
      return left.second.size() > right.second.size();
    }
    return left.second.front().size > right.second.front().size;
  });
  if (duplicates.size() > limit) {
    duplicates.resize(limit);
  }
  return duplicates;
}

std::vector<std::pair<std::string, std::vector<FileEntry>>> exactDuplicateGroups(
    const std::vector<FileEntry>& files,
    std::size_t limit) {
  std::unordered_map<std::uintmax_t, std::vector<FileEntry>> bySize;
  for (const auto& file : files) {
    bySize[file.size].push_back(file);
  }

  std::vector<std::pair<std::string, std::vector<FileEntry>>> duplicates;
  for (const auto& sizeGroup : bySize) {
    if (sizeGroup.second.size() < 2 || sizeGroup.first == 0) {
      continue;
    }

    std::unordered_map<std::string, std::vector<FileEntry>> byFingerprint;
    for (const auto& file : sizeGroup.second) {
      const std::string fingerprint = fingerprintFile(file.path);
      if (fingerprint.empty()) {
        continue;
      }
      byFingerprint[fingerprint].push_back(file);
    }

    for (auto& entry : byFingerprint) {
      if (entry.second.size() < 2) {
        continue;
      }
      std::sort(entry.second.begin(), entry.second.end(), [](const FileEntry& left, const FileEntry& right) {
        if (left.size != right.size) {
          return left.size > right.size;
        }
        return left.ageDays > right.ageDays;
      });
      duplicates.push_back({entry.first, entry.second});
    }
  }

  std::sort(duplicates.begin(), duplicates.end(), [](const auto& left, const auto& right) {
    if (left.second.size() != right.second.size()) {
      return left.second.size() > right.second.size();
    }
    return left.second.front().size > right.second.front().size;
  });
  if (duplicates.size() > limit) {
    duplicates.resize(limit);
  }
  return duplicates;
}

std::vector<std::pair<std::string, std::uintmax_t>> extensionBreakdown(const std::vector<FileEntry>& files, std::size_t limit) {
  std::map<std::string, std::uintmax_t> bytesByExtension;
  for (const auto& file : files) {
    bytesByExtension[file.extension] += file.size;
  }

  std::vector<std::pair<std::string, std::uintmax_t>> rows(bytesByExtension.begin(), bytesByExtension.end());
  std::sort(rows.begin(), rows.end(), [](const auto& left, const auto& right) {
    return left.second > right.second;
  });
  if (rows.size() > limit) {
    rows.resize(limit);
  }
  return rows;
}

std::vector<DirectoryFootprint> directoryHotspots(
    const std::vector<FileEntry>& files,
    const fs::path& root,
    std::size_t limit) {
  std::map<std::string, DirectoryFootprint> grouped;
  for (const auto& file : files) {
    std::error_code ec;
    fs::path relative = fs::relative(file.path, root, ec);
    std::string label = "[root files]";
    if (!ec && !relative.empty()) {
      if (relative.has_parent_path()) {
        const fs::path parent = *relative.begin();
        if (!parent.empty() && parent != ".") {
          label = parent.string();
        }
      }
    }

    auto& bucket = grouped[label];
    bucket.label = label;
    bucket.bytes += file.size;
    ++bucket.fileCount;
  }

  std::vector<DirectoryFootprint> rows;
  for (const auto& entry : grouped) {
    rows.push_back(entry.second);
  }
  std::sort(rows.begin(), rows.end(), [](const DirectoryFootprint& left, const DirectoryFootprint& right) {
    if (left.bytes != right.bytes) {
      return left.bytes > right.bytes;
    }
    return left.fileCount > right.fileCount;
  });
  if (rows.size() > limit) {
    rows.resize(limit);
  }
  return rows;
}

std::vector<CandidateRow> buildCandidateRows(
    const std::vector<FileEntry>& stale,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& duplicateGroups,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& exactDuplicateGroups) {
  std::vector<CandidateRow> rows;
  for (const auto& file : stale) {
    rows.push_back({"stale-file", file.path, file.size, formatDate(file.modifiedAt)});
  }

  for (const auto& group : duplicateGroups) {
    for (const auto& file : group.second) {
      rows.push_back({"probable-duplicate-name-size", file.path, file.size, formatDate(file.modifiedAt)});
    }
  }
  for (const auto& group : exactDuplicateGroups) {
    for (const auto& file : group.second) {
      rows.push_back({"exact-duplicate-content", file.path, file.size, formatDate(file.modifiedAt)});
    }
  }
  return rows;
}

void writeCandidateCsv(const fs::path& path, const std::vector<CandidateRow>& rows) {
  if (path.has_parent_path()) {
    fs::create_directories(path.parent_path());
  }
  std::ofstream output(path.string(), std::ios::out | std::ios::trunc);
  if (!output) {
    throw std::runtime_error("Unable to write CSV: " + path.string());
  }

  output << "reason,path,size_bytes,modified_date\n";
  for (const auto& row : rows) {
    output << csvEscape(row.reason) << ","
           << csvEscape(row.path.string()) << ","
           << row.size << ","
           << csvEscape(row.modifiedDate) << "\n";
  }
}

std::string buildMarkdownReport(
    const Options& options,
    const ScanSummary& summary,
    const std::vector<FileEntry>& largest,
    const std::vector<FileEntry>& stale,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& duplicates,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& exactDuplicates,
    const std::vector<std::pair<std::string, std::uintmax_t>>& extensions,
    const std::vector<DirectoryFootprint>& hotspots) {
  std::ostringstream output;
  output << "# Folder Triage Report\n\n";
  output << "- Root: `" << options.root.string() << "`\n";
  output << "- Files scanned: " << summary.files.size() << "\n";
  output << "- Directories visited: " << summary.directoriesVisited << "\n";
  output << "- Total size: " << formatBytes(summary.totalBytes) << "\n";
  output << "- Stale threshold: " << options.staleDays << " days\n\n";
  output << "- Exact duplicate scan: " << (options.exactDuplicateScan ? "enabled" : "disabled") << "\n\n";
  if (!options.excludedDirectories.empty()) {
    output << "- Excluded directories: ";
    for (std::size_t index = 0; index < options.excludedDirectories.size(); ++index) {
      if (index > 0) {
        output << ", ";
      }
      output << "`" << options.excludedDirectories[index] << "`";
    }
    output << "\n\n";
  }

  output << "## Extension footprint\n";
  for (const auto& row : extensions) {
    output << "- " << row.first << ": " << formatBytes(row.second) << "\n";
  }

  output << "\n## Directory hotspots\n";
  if (hotspots.empty()) {
    output << "- None detected.\n";
  } else {
    for (const auto& hotspot : hotspots) {
      output << "- `" << hotspot.label << "`: " << formatBytes(hotspot.bytes)
             << " across " << hotspot.fileCount << " files\n";
    }
  }

  output << "\n## Largest files\n";
  for (const auto& file : largest) {
    output << "- `" << file.path.string() << "` | " << formatBytes(file.size)
           << " | modified " << formatDate(file.modifiedAt) << "\n";
  }

  output << "\n## Stale candidates\n";
  if (stale.empty()) {
    output << "- None at the current threshold.\n";
  } else {
    for (const auto& file : stale) {
      output << "- `" << file.path.string() << "` | " << formatBytes(file.size)
             << " | age " << std::fixed << std::setprecision(1) << file.ageDays << " days\n";
    }
  }

  output << "\n## Probable duplicate filename+size groups\n";
  if (duplicates.empty()) {
    output << "- None detected.\n";
  } else {
    for (const auto& group : duplicates) {
      output << "- Group: `" << group.second.front().path.filename().string() << "` | "
             << formatBytes(group.second.front().size) << " | copies " << group.second.size() << "\n";
      for (const auto& file : group.second) {
        output << "  - `" << file.path.string() << "`\n";
      }
    }
  }

  output << "\n## Exact duplicate content groups\n";
  if (exactDuplicates.empty()) {
    output << "- None detected.\n";
  } else {
    for (const auto& group : exactDuplicates) {
      output << "- Fingerprint `" << group.first << "` | "
             << formatBytes(group.second.front().size) << " | copies " << group.second.size() << "\n";
      for (const auto& file : group.second) {
        output << "  - `" << file.path.string() << "`\n";
      }
    }
  }

  output << "\n## Empty directories\n";
  if (summary.emptyDirectories.empty()) {
    output << "- None detected.\n";
  } else {
    for (const auto& dir : summary.emptyDirectories) {
      output << "- `" << dir.string() << "`\n";
    }
  }

  return output.str();
}

void printConsoleSummary(
    const Options& options,
    const ScanSummary& summary,
    const std::vector<FileEntry>& largest,
    const std::vector<FileEntry>& stale,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& duplicates,
    const std::vector<std::pair<std::string, std::vector<FileEntry>>>& exactDuplicates,
    const std::vector<std::pair<std::string, std::uintmax_t>>& extensions,
    const std::vector<DirectoryFootprint>& hotspots) {
  std::cout << "Folder Triage CLI\n";
  std::cout << "Root:                " << options.root.string() << "\n";
  std::cout << "Files scanned:       " << summary.files.size() << "\n";
  std::cout << "Directories visited: " << summary.directoriesVisited << "\n";
  std::cout << "Total size:          " << formatBytes(summary.totalBytes) << "\n";
  std::cout << "Empty directories:   " << summary.emptyDirectories.size() << "\n";
  std::cout << "Stale threshold:     " << options.staleDays << " days\n";
  if (!options.excludedDirectories.empty()) {
    std::cout << "Excluded directories: ";
    for (std::size_t index = 0; index < options.excludedDirectories.size(); ++index) {
      if (index > 0) {
        std::cout << ", ";
      }
      std::cout << options.excludedDirectories[index];
    }
    std::cout << "\n";
  }
  std::cout << "Probable duplicate groups: " << duplicates.size() << "\n\n";
  if (options.exactDuplicateScan) {
    std::cout << "Exact duplicate groups:    " << exactDuplicates.size() << "\n\n";
  }

  std::cout << "Top extensions by size:\n";
  for (const auto& row : extensions) {
    std::cout << "  " << std::setw(16) << std::left << row.first << " " << formatBytes(row.second) << "\n";
  }

  std::cout << "\nDirectory hotspots:\n";
  for (const auto& hotspot : hotspots) {
    std::cout << "  " << std::setw(20) << std::left << hotspot.label
              << " " << formatBytes(hotspot.bytes)
              << " across " << hotspot.fileCount << " files\n";
  }

  std::cout << "\nLargest files:\n";
  for (const auto& file : largest) {
    std::cout << "  " << formatBytes(file.size) << " | " << formatDate(file.modifiedAt)
              << " | " << file.path.string() << "\n";
  }

  std::cout << "\nStale candidates:\n";
  if (stale.empty()) {
    std::cout << "  None at the current threshold.\n";
  } else {
    for (const auto& file : stale) {
      std::cout << "  " << std::fixed << std::setprecision(1) << file.ageDays << " days | "
                << formatBytes(file.size) << " | " << file.path.string() << "\n";
    }
  }
}

int main(int argc, char** argv) {
  try {
    const Options options = parseArgs(argc, argv);
    const ScanSummary summary = scanTree(options);
    const auto largest = topLargest(summary.files, options.topCount);
    const auto stale = staleFiles(summary.files, options.staleDays, options.topCount);
    const auto duplicates = probableDuplicateGroups(summary.files, options.topCount);
    const auto exactDuplicates = options.exactDuplicateScan
      ? exactDuplicateGroups(summary.files, options.topCount)
      : std::vector<std::pair<std::string, std::vector<FileEntry>>>{};
    const auto extensions = extensionBreakdown(summary.files, 8);
    const auto hotspots = directoryHotspots(summary.files, options.root, options.topCount);
    const auto candidates = buildCandidateRows(stale, duplicates, exactDuplicates);

    printConsoleSummary(options, summary, largest, stale, duplicates, exactDuplicates, extensions, hotspots);

    if (!options.markdownReport.empty()) {
      if (options.markdownReport.has_parent_path()) {
        fs::create_directories(options.markdownReport.parent_path());
      }
      std::ofstream output(options.markdownReport.string(), std::ios::out | std::ios::trunc);
      if (!output) {
        throw std::runtime_error("Unable to write report: " + options.markdownReport.string());
      }
      output << buildMarkdownReport(options, summary, largest, stale, duplicates, exactDuplicates, extensions, hotspots);
      std::cout << "\nWrote Markdown report: " << options.markdownReport.string() << "\n";
    }

    if (!options.candidateCsv.empty()) {
      writeCandidateCsv(options.candidateCsv, candidates);
      std::cout << "Wrote candidate CSV:    " << options.candidateCsv.string() << "\n";
    }
  } catch (const std::exception& error) {
    std::cerr << "Error: " << error.what() << "\n";
    return 1;
  }

  return 0;
}
