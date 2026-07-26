#include <algorithm>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct Options {
  fs::path root;
  int staleDays = 21;
  fs::path markdownOut;
  std::set<std::string> excludedDirectories;
};

struct RepoStatus {
  fs::path path;
  std::string branch;
  std::string defaultBranch;
  std::string upstream;
  int ahead = 0;
  int behind = 0;
  int trackedChanges = 0;
  int untrackedChanges = 0;
  int daysSinceCommit = 0;
  std::string lastCommitDate;
  std::string lastCommitSubject;
  std::string statusLabel;
};

std::string trim(const std::string& value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::string lowerCopy(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
    return static_cast<char>(std::tolower(ch));
  });
  return value;
}

std::string quotePath(const fs::path& path) {
  return "\"" + path.string() + "\"";
}

std::string runCommand(const std::string& command) {
#ifdef _WIN32
  FILE* pipe = _popen(command.c_str(), "r");
#else
  FILE* pipe = popen(command.c_str(), "r");
#endif
  if (!pipe) {
    throw std::runtime_error("Unable to execute command: " + command);
  }

  std::string output;
  char buffer[4096];
  while (std::fgets(buffer, sizeof(buffer), pipe) != nullptr) {
    output += buffer;
  }
#ifdef _WIN32
  _pclose(pipe);
#else
  pclose(pipe);
#endif
  return trim(output);
}

bool commandSucceeds(const std::string& command) {
#ifdef _WIN32
  const std::string wrapped = "cmd /c \"" + command + " >nul 2>nul\"";
#else
  const std::string wrapped = command + " >/dev/null 2>/dev/null";
#endif
  const int exitCode = std::system(wrapped.c_str());
  return exitCode == 0;
}

void printUsage() {
  std::cout
      << "Workspace Branch Watch\n"
      << "Usage:\n"
      << "  workspace-branch-watch <root> [--stale-days N] [--markdown-out path] [--exclude-dir NAME]\n";
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

    if (arg == "--stale-days") {
      options.staleDays = std::stoi(requireValue(arg));
    } else if (arg == "--markdown-out") {
      options.markdownOut = fs::path(requireValue(arg));
    } else if (arg == "--exclude-dir") {
      options.excludedDirectories.insert(lowerCopy(requireValue(arg)));
    } else if (arg == "--help" || arg == "-h") {
      printUsage();
      std::exit(0);
    } else {
      throw std::runtime_error("Unknown argument: " + arg);
    }
  }

  if (options.staleDays < 0) {
    throw std::runtime_error("--stale-days cannot be negative.");
  }
  return options;
}

bool shouldSkipDirectory(const Options& options, const fs::path& path) {
  return options.excludedDirectories.count(lowerCopy(path.filename().string())) > 0;
}

std::vector<fs::path> discoverRepos(const Options& options) {
  if (!fs::exists(options.root) || !fs::is_directory(options.root)) {
    throw std::runtime_error("Root must be an existing directory.");
  }

  std::vector<fs::path> repos;
  fs::directory_options dirOptions = fs::directory_options::skip_permission_denied;
  for (fs::recursive_directory_iterator it(options.root, dirOptions), end; it != end; ++it) {
    std::error_code ec;
    if (!it->is_directory(ec)) {
      continue;
    }
    const fs::path current = it->path();
    if (shouldSkipDirectory(options, current)) {
      it.disable_recursion_pending();
      continue;
    }
    if (current.filename() == ".git") {
      repos.push_back(current.parent_path());
      it.disable_recursion_pending();
    }
  }
  std::sort(repos.begin(), repos.end());
  return repos;
}

std::string gitOutput(const fs::path& repo, const std::string& args) {
  return runCommand("git -C " + quotePath(repo) + " " + args + " 2>nul");
}

std::optional<std::string> gitOutputIfOk(const fs::path& repo, const std::string& args) {
  const std::string command = "git -C " + quotePath(repo) + " " + args;
  if (!commandSucceeds(command)) {
    return std::nullopt;
  }
  return runCommand(command + " 2>nul");
}

int countStatusRows(const std::string& porcelain, bool untracked) {
  int count = 0;
  std::istringstream stream(porcelain);
  std::string line;
  while (std::getline(stream, line)) {
    if (line.size() < 2) {
      continue;
    }
    const bool isUntracked = line.rfind("??", 0) == 0;
    if (isUntracked == untracked) {
      ++count;
    }
  }
  return count;
}

int parseDaysSince(const std::string& isoDate) {
  std::tm timeInfo {};
  std::istringstream input(isoDate.substr(0, 10));
  input >> std::get_time(&timeInfo, "%Y-%m-%d");
  if (input.fail()) {
    return 0;
  }
  const std::time_t commitTime = std::mktime(&timeInfo);
  const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
  const double seconds = std::difftime(now, commitTime);
  return static_cast<int>(seconds / 86400.0);
}

RepoStatus inspectRepo(const fs::path& repo, int staleDays) {
  RepoStatus status;
  status.path = repo;
  status.branch = gitOutput(repo, "rev-parse --abbrev-ref HEAD");
  status.defaultBranch = gitOutputIfOk(repo, "symbolic-ref --short refs/remotes/origin/HEAD")
      .value_or("origin/HEAD-unavailable");
  if (status.defaultBranch.rfind("origin/", 0) == 0) {
    status.defaultBranch = status.defaultBranch.substr(7);
  }
  status.upstream = gitOutputIfOk(repo, "rev-parse --abbrev-ref --symbolic-full-name @{upstream}")
      .value_or("none");

  const std::string porcelain = gitOutput(repo, "status --porcelain");
  status.trackedChanges = countStatusRows(porcelain, false);
  status.untrackedChanges = countStatusRows(porcelain, true);

  if (status.upstream != "none") {
    const std::string divergence = gitOutput(repo, "rev-list --left-right --count HEAD...@{upstream}");
    std::istringstream divergenceStream(divergence);
    divergenceStream >> status.ahead >> status.behind;
  }

  status.lastCommitDate = gitOutput(repo, "log -1 --format=%cI");
  status.lastCommitSubject = gitOutput(repo, "log -1 --format=%s");
  status.daysSinceCommit = parseDaysSince(status.lastCommitDate);

  if (status.trackedChanges > 0 || status.untrackedChanges > 0) {
    status.statusLabel = "dirty";
  } else if (status.ahead > 0 || status.behind > 0) {
    status.statusLabel = "drifted";
  } else if (status.daysSinceCommit >= staleDays) {
    status.statusLabel = "stale";
  } else {
    status.statusLabel = "ready";
  }

  return status;
}

std::string relativeLabel(const fs::path& root, const fs::path& path) {
  std::error_code ec;
  const fs::path relative = fs::relative(path, root, ec);
  return ec ? path.string() : relative.string();
}

std::string renderMarkdown(const Options& options, const std::vector<RepoStatus>& repos) {
  int dirty = 0;
  int drifted = 0;
  int stale = 0;
  for (const auto& repo : repos) {
    dirty += repo.statusLabel == "dirty";
    drifted += repo.statusLabel == "drifted";
    stale += repo.statusLabel == "stale";
  }

  std::ostringstream output;
  output << "# Workspace Branch Watch\n\n";
  output << "- Root: `" << options.root.string() << "`\n";
  output << "- Repositories scanned: " << repos.size() << "\n";
  output << "- Dirty: " << dirty << "\n";
  output << "- Drifted: " << drifted << "\n";
  output << "- Stale: " << stale << "\n\n";
  output << "## Repositories\n";
  for (const auto& repo : repos) {
    output << "- `" << relativeLabel(options.root, repo.path) << "` | " << repo.statusLabel
           << " | branch `" << repo.branch << "`";
    if (repo.upstream != "none") {
      output << " | upstream `" << repo.upstream << "` | ahead " << repo.ahead << " | behind " << repo.behind;
    }
    output << " | tracked " << repo.trackedChanges << " | untracked " << repo.untrackedChanges
           << " | last commit " << repo.lastCommitDate.substr(0, 10)
           << " (" << repo.daysSinceCommit << " days)\n";
    output << "  - Last commit: " << repo.lastCommitSubject << "\n";
  }
  return output.str();
}

int main(int argc, char** argv) {
  try {
    const Options options = parseArgs(argc, argv);
    const auto repos = discoverRepos(options);
    std::vector<RepoStatus> statuses;
    statuses.reserve(repos.size());
    for (const auto& repo : repos) {
      statuses.push_back(inspectRepo(repo, options.staleDays));
    }
    std::sort(statuses.begin(), statuses.end(), [&](const RepoStatus& left, const RepoStatus& right) {
      const auto rank = [](const std::string& label) {
        if (label == "dirty") return 0;
        if (label == "drifted") return 1;
        if (label == "stale") return 2;
        return 3;
      };
      if (rank(left.statusLabel) != rank(right.statusLabel)) {
        return rank(left.statusLabel) < rank(right.statusLabel);
      }
      return relativeLabel(options.root, left.path) < relativeLabel(options.root, right.path);
    });

    int dirty = 0;
    int drifted = 0;
    int stale = 0;
    for (const auto& repo : statuses) {
      dirty += repo.statusLabel == "dirty";
      drifted += repo.statusLabel == "drifted";
      stale += repo.statusLabel == "stale";
    }

    std::cout << "Workspace Branch Watch\n";
    std::cout << "Root: " << options.root.string() << "\n";
    std::cout << "Repositories scanned: " << statuses.size() << "\n";
    std::cout << "Dirty: " << dirty << " | Drifted: " << drifted << " | Stale: " << stale << "\n\n";
    for (const auto& repo : statuses) {
      std::cout << std::setw(8) << std::left << repo.statusLabel
                << " tracked " << std::setw(3) << repo.trackedChanges
                << " | untracked " << std::setw(3) << repo.untrackedChanges
                << " | ahead " << std::setw(3) << repo.ahead
                << " | behind " << std::setw(3) << repo.behind
                << " | " << repo.branch
                << " | " << relativeLabel(options.root, repo.path) << "\n";
    }

    if (!options.markdownOut.empty()) {
      if (options.markdownOut.has_parent_path()) {
        fs::create_directories(options.markdownOut.parent_path());
      }
      std::ofstream output(options.markdownOut);
      if (!output) {
        throw std::runtime_error("Unable to write report: " + options.markdownOut.string());
      }
      output << renderMarkdown(options, statuses);
      std::cout << "\nWrote Markdown report: " << options.markdownOut.string() << "\n";
    }
  } catch (const std::exception& error) {
    std::cerr << "Error: " << error.what() << "\n";
    return 1;
  }

  return 0;
}
