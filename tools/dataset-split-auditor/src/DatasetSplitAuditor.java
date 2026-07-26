import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

public final class DatasetSplitAuditor {
    private DatasetSplitAuditor() {
    }

    public static void main(String[] args) throws Exception {
        Config config = Config.parse(args);
        AuditReport report = audit(config);

        System.out.println(report.toConsoleString());

        if (config.markdownOut != null) {
            writeText(config.markdownOut, report.toMarkdown());
            System.out.println("Wrote markdown report to " + config.markdownOut.toAbsolutePath());
        }
        if (config.jsonOut != null) {
            writeText(config.jsonOut, report.toJson());
            System.out.println("Wrote JSON report to " + config.jsonOut.toAbsolutePath());
        }
    }

    private static AuditReport audit(Config config) throws IOException {
        Map<String, SplitData> splits = new LinkedHashMap<>();
        splits.put("train", readSplit("train", config.train));
        splits.put("test", readSplit("test", config.test));
        if (config.validation != null) {
            splits.put("validation", readSplit("validation", config.validation));
        }

        List<SplitSummary> summaries = new ArrayList<>();
        for (SplitData split : splits.values()) {
            summaries.add(buildSummary(split, config));
        }

        List<OverlapSummary> overlaps = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        List<String> splitNames = new ArrayList<>(splits.keySet());
        for (int i = 0; i < splitNames.size(); i += 1) {
            for (int j = i + 1; j < splitNames.size(); j += 1) {
                SplitData left = splits.get(splitNames.get(i));
                SplitData right = splits.get(splitNames.get(j));
                OverlapSummary overlap = buildOverlap(left, right, config);
                overlaps.add(overlap);
                if (overlap.fingerprintOverlapCount > 0) {
                    warnings.add(
                        String.format(
                            Locale.US,
                            "%s/%s share %d exact row fingerprint(s).",
                            left.name,
                            right.name,
                            overlap.fingerprintOverlapCount
                        )
                    );
                }
                if (overlap.idOverlapCount > 0) {
                    warnings.add(
                        String.format(
                            Locale.US,
                            "%s/%s share %d duplicate id value(s).",
                            left.name,
                            right.name,
                            overlap.idOverlapCount
                        )
                    );
                }
                if (overlap.temporalLeakage) {
                    warnings.add(
                        String.format(
                            Locale.US,
                            "%s max date %s reaches past %s min date %s.",
                            left.name,
                            overlap.leftMaxDate,
                            right.name,
                            overlap.rightMinDate
                        )
                    );
                }
            }
        }

        for (SplitSummary summary : summaries) {
            if (!summary.duplicateIds.isEmpty()) {
                warnings.add(
                    String.format(
                        Locale.US,
                        "%s contains %d duplicate id value(s) within the split.",
                        summary.name,
                        summary.duplicateIds.size()
                    )
                );
            }
            for (Map.Entry<String, Integer> entry : summary.missingValueCounts.entrySet()) {
                if (entry.getValue() > 0) {
                    warnings.add(
                        String.format(
                            Locale.US,
                            "%s is missing %d value(s) in column %s.",
                            summary.name,
                            entry.getValue(),
                            entry.getKey()
                        )
                    );
                }
            }
            if (summary.invalidDateCount > 0) {
                warnings.add(
                    String.format(
                        Locale.US,
                        "%s contains %d nonblank value(s) in column %s that could not be parsed as dates.",
                        summary.name,
                        summary.invalidDateCount,
                        config.dateColumn
                    )
                );
            }
        }

        warnings.addAll(buildLabelCoverageWarnings(summaries));

        if (warnings.isEmpty()) {
            warnings.add("No exact row overlap, duplicate id overlap, or temporal leakage was detected.");
        }

        return new AuditReport(config, summaries, overlaps, warnings);
    }

    private static SplitSummary buildSummary(SplitData split, Config config) {
        Map<String, Integer> labelCounts = new LinkedHashMap<>();
        Map<String, Integer> missingValueCounts = new LinkedHashMap<>();
        seedTrackedColumn(missingValueCounts, config.idColumn);
        seedTrackedColumn(missingValueCounts, config.dateColumn);
        seedTrackedColumn(missingValueCounts, config.labelColumn);
        int invalidDateCount = 0;
        Set<String> seenIds = new LinkedHashSet<>();
        Set<String> duplicateIds = new TreeSet<>();
        Set<String> labels = new TreeSet<>();
        LocalDate minDate = null;
        LocalDate maxDate = null;

        for (RowData row : split.rows) {
            if (!config.labelColumn.isBlank()) {
                String labelValue = row.value(config.labelColumn);
                if (!labelValue.isBlank()) {
                    labelCounts.put(labelValue, labelCounts.getOrDefault(labelValue, 0) + 1);
                    labels.add(labelValue);
                } else {
                    incrementMissing(missingValueCounts, config.labelColumn);
                }
            }
            if (!config.idColumn.isBlank()) {
                String idValue = row.value(config.idColumn);
                if (!idValue.isBlank()) {
                    if (!seenIds.add(idValue)) {
                        duplicateIds.add(idValue);
                    }
                } else {
                    incrementMissing(missingValueCounts, config.idColumn);
                }
            }
            if (!config.dateColumn.isBlank()) {
                String rawDate = row.value(config.dateColumn);
                LocalDate parsed = parseDate(rawDate);
                if (parsed != null) {
                    if (minDate == null || parsed.isBefore(minDate)) {
                        minDate = parsed;
                    }
                    if (maxDate == null || parsed.isAfter(maxDate)) {
                        maxDate = parsed;
                    }
                } else if (rawDate.isBlank()) {
                    incrementMissing(missingValueCounts, config.dateColumn);
                } else {
                    invalidDateCount += 1;
                }
            }
        }

        return new SplitSummary(
            split.name,
            split.rows.size(),
            labelCounts,
            new ArrayList<>(duplicateIds),
            minDate,
            maxDate,
            missingValueCounts,
            invalidDateCount,
            labels
        );
    }

    private static void seedTrackedColumn(Map<String, Integer> missingValueCounts, String column) {
        if (!column.isBlank() && !missingValueCounts.containsKey(column)) {
            missingValueCounts.put(column, 0);
        }
    }

    private static void incrementMissing(Map<String, Integer> missingValueCounts, String column) {
        if (column.isBlank()) {
            return;
        }
        missingValueCounts.put(column, missingValueCounts.getOrDefault(column, 0) + 1);
    }

    private static List<String> buildLabelCoverageWarnings(List<SplitSummary> summaries) {
        Set<String> union = new TreeSet<>();
        for (SplitSummary summary : summaries) {
            union.addAll(summary.labels);
        }
        if (union.isEmpty()) {
            return Collections.emptyList();
        }

        List<String> warnings = new ArrayList<>();
        for (SplitSummary summary : summaries) {
            Set<String> missing = new TreeSet<>(union);
            missing.removeAll(summary.labels);
            if (!missing.isEmpty()) {
                warnings.add(
                    String.format(
                        Locale.US,
                        "%s is missing %d label value(s) that appear in other splits: %s.",
                        summary.name,
                        missing.size(),
                        String.join(", ", missing)
                    )
                );
            }
        }
        return warnings;
    }

    private static OverlapSummary buildOverlap(SplitData left, SplitData right, Config config) {
        Set<String> leftFingerprints = new LinkedHashSet<>();
        for (RowData row : left.rows) {
            leftFingerprints.add(row.fingerprint);
        }
        Set<String> rightFingerprints = new LinkedHashSet<>();
        for (RowData row : right.rows) {
            rightFingerprints.add(row.fingerprint);
        }

        Set<String> sharedFingerprints = new TreeSet<>(leftFingerprints);
        sharedFingerprints.retainAll(rightFingerprints);

        Set<String> sharedIds = new TreeSet<>();
        if (!config.idColumn.isBlank()) {
            Set<String> leftIds = new TreeSet<>();
            Set<String> rightIds = new TreeSet<>();
            for (RowData row : left.rows) {
                String value = row.value(config.idColumn);
                if (!value.isBlank()) {
                    leftIds.add(value);
                }
            }
            for (RowData row : right.rows) {
                String value = row.value(config.idColumn);
                if (!value.isBlank()) {
                    rightIds.add(value);
                }
            }
            sharedIds.addAll(leftIds);
            sharedIds.retainAll(rightIds);
        }

        LocalDate leftMaxDate = latestDate(left.rows, config.dateColumn);
        LocalDate rightMinDate = earliestDate(right.rows, config.dateColumn);
        boolean temporalLeakage = leftMaxDate != null && rightMinDate != null && !leftMaxDate.isBefore(rightMinDate);

        return new OverlapSummary(
            left.name,
            right.name,
            sharedFingerprints.size(),
            sample(sharedFingerprints, 5),
            sharedIds.size(),
            sample(sharedIds, 5),
            temporalLeakage,
            leftMaxDate,
            rightMinDate
        );
    }

    private static SplitData readSplit(String name, Path path) throws IOException {
        List<List<String>> rows = parseCsv(path);
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("CSV has no rows: " + path);
        }

        List<String> headers = new ArrayList<>();
        for (String header : rows.get(0)) {
            headers.add(normalizeHeader(header));
        }

        List<RowData> dataRows = new ArrayList<>();
        for (int i = 1; i < rows.size(); i += 1) {
            List<String> row = rows.get(i);
            boolean nonBlank = false;
            Map<String, String> values = new LinkedHashMap<>();
            for (int col = 0; col < headers.size(); col += 1) {
                String value = col < row.size() ? row.get(col).trim() : "";
                if (!value.isBlank()) {
                    nonBlank = true;
                }
                values.put(headers.get(col), value);
            }
            if (!nonBlank) {
                continue;
            }
            dataRows.add(new RowData(values, fingerprint(values), i + 1));
        }

        return new SplitData(name, path, headers, dataRows);
    }

    private static List<List<String>> parseCsv(Path path) throws IOException {
        String text = Files.readString(path, StandardCharsets.UTF_8).replace("\ufeff", "");
        List<List<String>> rows = new ArrayList<>();
        List<String> currentRow = new ArrayList<>();
        StringBuilder currentCell = new StringBuilder();
        boolean inQuotes = false;

        for (int i = 0; i < text.length(); i += 1) {
            char current = text.charAt(i);
            char next = i + 1 < text.length() ? text.charAt(i + 1) : '\0';

            if (current == '"') {
                if (inQuotes && next == '"') {
                    currentCell.append('"');
                    i += 1;
                } else {
                    inQuotes = !inQuotes;
                }
                continue;
            }

            if (current == ',' && !inQuotes) {
                currentRow.add(currentCell.toString());
                currentCell.setLength(0);
                continue;
            }

            if ((current == '\n' || current == '\r') && !inQuotes) {
                if (current == '\r' && next == '\n') {
                    i += 1;
                }
                currentRow.add(currentCell.toString());
                rows.add(new ArrayList<>(currentRow));
                currentRow.clear();
                currentCell.setLength(0);
                continue;
            }

            currentCell.append(current);
        }

        if (currentCell.length() > 0 || !currentRow.isEmpty()) {
          currentRow.add(currentCell.toString());
          rows.add(currentRow);
        }

        return rows;
    }

    private static String normalizeHeader(String value) {
        return value.trim().toLowerCase(Locale.US);
    }

    private static String fingerprint(Map<String, String> values) {
        List<String> parts = new ArrayList<>();
        for (Map.Entry<String, String> entry : values.entrySet()) {
            parts.add(entry.getKey() + "=" + entry.getValue());
        }
        return String.join("|", parts);
    }

    private static LocalDate parseDate(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String trimmed = value.trim();
        try {
            if (trimmed.length() >= 10) {
                return LocalDate.parse(trimmed.substring(0, 10));
            }
            return LocalDate.parse(trimmed);
        } catch (DateTimeParseException error) {
            return null;
        }
    }

    private static LocalDate earliestDate(List<RowData> rows, String dateColumn) {
        if (dateColumn.isBlank()) {
            return null;
        }
        LocalDate result = null;
        for (RowData row : rows) {
            LocalDate date = parseDate(row.value(dateColumn));
            if (date != null && (result == null || date.isBefore(result))) {
                result = date;
            }
        }
        return result;
    }

    private static LocalDate latestDate(List<RowData> rows, String dateColumn) {
        if (dateColumn.isBlank()) {
            return null;
        }
        LocalDate result = null;
        for (RowData row : rows) {
            LocalDate date = parseDate(row.value(dateColumn));
            if (date != null && (result == null || date.isAfter(result))) {
                result = date;
            }
        }
        return result;
    }

    private static List<String> sample(Set<String> values, int limit) {
        List<String> output = new ArrayList<>();
        int count = 0;
        for (String value : values) {
            if (count >= limit) {
                break;
            }
            output.add(value);
            count += 1;
        }
        return output;
    }

    private static void writeText(Path path, String text) throws IOException {
        Path parent = path.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Files.writeString(path, text, StandardCharsets.UTF_8);
    }

    private static final class Config {
        private final Path train;
        private final Path test;
        private final Path validation;
        private final String idColumn;
        private final String dateColumn;
        private final String labelColumn;
        private final Path markdownOut;
        private final Path jsonOut;

        private Config(Path train, Path test, Path validation, String idColumn, String dateColumn, String labelColumn, Path markdownOut, Path jsonOut) {
            this.train = train;
            this.test = test;
            this.validation = validation;
            this.idColumn = idColumn;
            this.dateColumn = dateColumn;
            this.labelColumn = labelColumn;
            this.markdownOut = markdownOut;
            this.jsonOut = jsonOut;
        }

        private static Config parse(String[] args) {
            Map<String, String> values = new HashMap<>();
            for (int i = 0; i < args.length; i += 1) {
                String arg = args[i];
                if ("--help".equals(arg) || "-h".equals(arg)) {
                    printHelpAndExit();
                }
                if (!arg.startsWith("--")) {
                    throw new IllegalArgumentException("Unexpected argument: " + arg);
                }
                if (i + 1 >= args.length) {
                    throw new IllegalArgumentException("Missing value for " + arg);
                }
                values.put(arg.substring(2), args[i + 1]);
                i += 1;
            }

            Path train = requirePath(values, "train");
            Path test = requirePath(values, "test");
            Path validation = values.containsKey("validation") ? Path.of(values.get("validation")) : null;
            return new Config(
                train,
                test,
                validation,
                values.getOrDefault("id-column", "id").trim().toLowerCase(Locale.US),
                values.getOrDefault("date-column", "date").trim().toLowerCase(Locale.US),
                values.getOrDefault("label-column", "label").trim().toLowerCase(Locale.US),
                values.containsKey("report-out") ? Path.of(values.get("report-out")) : null,
                values.containsKey("json-out") ? Path.of(values.get("json-out")) : null
            );
        }

        private static Path requirePath(Map<String, String> values, String key) {
            String raw = values.get(key);
            if (raw == null || raw.isBlank()) {
                throw new IllegalArgumentException("Missing required --" + key + " path.");
            }
            return Path.of(raw);
        }

        private static void printHelpAndExit() {
            System.out.println("dataset-split-auditor");
            System.out.println();
            System.out.println("Usage:");
            System.out.println("  java -cp src DatasetSplitAuditor --train train.csv --test test.csv [--validation val.csv]");
            System.out.println("    [--id-column id] [--date-column date] [--label-column label]");
            System.out.println("    [--report-out reports/audit.md] [--json-out reports/audit.json]");
            System.exit(0);
        }
    }

    private static final class SplitData {
        private final String name;
        private final Path path;
        private final List<String> headers;
        private final List<RowData> rows;

        private SplitData(String name, Path path, List<String> headers, List<RowData> rows) {
            this.name = name;
            this.path = path;
            this.headers = headers;
            this.rows = rows;
        }
    }

    private static final class RowData {
        private final Map<String, String> values;
        private final String fingerprint;
        private final int lineNumber;

        private RowData(Map<String, String> values, String fingerprint, int lineNumber) {
            this.values = values;
            this.fingerprint = fingerprint;
            this.lineNumber = lineNumber;
        }

        private String value(String key) {
            return values.getOrDefault(key, "");
        }
    }

    private static final class SplitSummary {
        private final String name;
        private final int rows;
        private final Map<String, Integer> labelCounts;
        private final List<String> duplicateIds;
        private final LocalDate minDate;
        private final LocalDate maxDate;
        private final Map<String, Integer> missingValueCounts;
        private final int invalidDateCount;
        private final Set<String> labels;

        private SplitSummary(
            String name,
            int rows,
            Map<String, Integer> labelCounts,
            List<String> duplicateIds,
            LocalDate minDate,
            LocalDate maxDate,
            Map<String, Integer> missingValueCounts,
            int invalidDateCount,
            Set<String> labels
        ) {
            this.name = name;
            this.rows = rows;
            this.labelCounts = labelCounts;
            this.duplicateIds = duplicateIds;
            this.minDate = minDate;
            this.maxDate = maxDate;
            this.missingValueCounts = missingValueCounts;
            this.invalidDateCount = invalidDateCount;
            this.labels = labels;
        }
    }

    private static final class OverlapSummary {
        private final String leftName;
        private final String rightName;
        private final int fingerprintOverlapCount;
        private final List<String> fingerprintSamples;
        private final int idOverlapCount;
        private final List<String> idSamples;
        private final boolean temporalLeakage;
        private final LocalDate leftMaxDate;
        private final LocalDate rightMinDate;

        private OverlapSummary(
            String leftName,
            String rightName,
            int fingerprintOverlapCount,
            List<String> fingerprintSamples,
            int idOverlapCount,
            List<String> idSamples,
            boolean temporalLeakage,
            LocalDate leftMaxDate,
            LocalDate rightMinDate
        ) {
            this.leftName = leftName;
            this.rightName = rightName;
            this.fingerprintOverlapCount = fingerprintOverlapCount;
            this.fingerprintSamples = fingerprintSamples;
            this.idOverlapCount = idOverlapCount;
            this.idSamples = idSamples;
            this.temporalLeakage = temporalLeakage;
            this.leftMaxDate = leftMaxDate;
            this.rightMinDate = rightMinDate;
        }
    }

    private static final class AuditReport {
        private final Config config;
        private final List<SplitSummary> summaries;
        private final List<OverlapSummary> overlaps;
        private final List<String> warnings;

        private AuditReport(Config config, List<SplitSummary> summaries, List<OverlapSummary> overlaps, List<String> warnings) {
            this.config = config;
            this.summaries = summaries;
            this.overlaps = overlaps;
            this.warnings = warnings;
        }

        private String toConsoleString() {
            StringBuilder builder = new StringBuilder();
            builder.append("Dataset Split Auditor").append(System.lineSeparator());
            builder.append("Splits: ");
            for (int i = 0; i < summaries.size(); i += 1) {
                if (i > 0) {
                    builder.append(", ");
                }
                builder.append(summaries.get(i).name).append("=").append(summaries.get(i).rows).append(" rows");
            }
            builder.append(System.lineSeparator()).append(System.lineSeparator());
            builder.append("Warnings").append(System.lineSeparator());
            for (String warning : warnings) {
                builder.append("- ").append(warning).append(System.lineSeparator());
            }
            return builder.toString().trim();
        }

        private String toMarkdown() {
            StringBuilder builder = new StringBuilder();
            builder.append("# Dataset Split Audit").append(System.lineSeparator()).append(System.lineSeparator());
            builder.append("## Split Summary").append(System.lineSeparator()).append(System.lineSeparator());
            builder.append("| Split | Rows | Date Range | Duplicate IDs | Missing Core Fields | Invalid Dates | Label Mix |").append(System.lineSeparator());
            builder.append("| --- | ---: | --- | --- | --- | ---: | --- |").append(System.lineSeparator());
            for (SplitSummary summary : summaries) {
                builder.append("| ")
                    .append(summary.name)
                    .append(" | ")
                    .append(summary.rows)
                    .append(" | ")
                    .append(formatDateRange(summary.minDate, summary.maxDate))
                    .append(" | ")
                    .append(summary.duplicateIds.isEmpty() ? "none" : String.join(", ", summary.duplicateIds))
                    .append(" | ")
                    .append(formatMissingCounts(summary))
                    .append(" | ")
                    .append(summary.invalidDateCount)
                    .append(" | ")
                    .append(formatLabelMix(summary))
                    .append(" |")
                    .append(System.lineSeparator());
            }

            builder.append(System.lineSeparator()).append("## Overlap Checks").append(System.lineSeparator()).append(System.lineSeparator());
            for (OverlapSummary overlap : overlaps) {
                builder.append("### ").append(overlap.leftName).append(" vs ").append(overlap.rightName).append(System.lineSeparator());
                builder.append("- Exact row overlap: ").append(overlap.fingerprintOverlapCount).append(System.lineSeparator());
                if (!overlap.fingerprintSamples.isEmpty()) {
                    builder.append("- Sample fingerprint(s): ").append(String.join(" ; ", overlap.fingerprintSamples)).append(System.lineSeparator());
                }
                builder.append("- Duplicate id overlap: ").append(overlap.idOverlapCount).append(System.lineSeparator());
                if (!overlap.idSamples.isEmpty()) {
                    builder.append("- Sample id(s): ").append(String.join(", ", overlap.idSamples)).append(System.lineSeparator());
                }
                builder.append("- Temporal leakage: ").append(overlap.temporalLeakage ? "yes" : "no");
                if (overlap.leftMaxDate != null || overlap.rightMinDate != null) {
                    builder.append(" (")
                        .append(overlap.leftName)
                        .append(" max ")
                        .append(overlap.leftMaxDate)
                        .append(" vs ")
                        .append(overlap.rightName)
                        .append(" min ")
                        .append(overlap.rightMinDate)
                        .append(")");
                }
                builder.append(System.lineSeparator()).append(System.lineSeparator());
            }

            builder.append("## Warnings").append(System.lineSeparator()).append(System.lineSeparator());
            for (String warning : warnings) {
                builder.append("- ").append(warning).append(System.lineSeparator());
            }
            return builder.toString();
        }

        private String toJson() {
            StringBuilder builder = new StringBuilder();
            builder.append("{\n");
            builder.append("  \"splits\": [\n");
            for (int i = 0; i < summaries.size(); i += 1) {
                SplitSummary summary = summaries.get(i);
                builder.append("    {\n");
                builder.append("      \"name\": ").append(json(summary.name)).append(",\n");
                builder.append("      \"rows\": ").append(summary.rows).append(",\n");
                builder.append("      \"min_date\": ").append(json(summary.minDate == null ? "" : summary.minDate.toString())).append(",\n");
                builder.append("      \"max_date\": ").append(json(summary.maxDate == null ? "" : summary.maxDate.toString())).append(",\n");
                builder.append("      \"duplicate_ids\": ").append(jsonArray(summary.duplicateIds)).append(",\n");
                builder.append("      \"missing_value_counts\": ").append(jsonObject(summary.missingValueCounts)).append(",\n");
                builder.append("      \"invalid_date_count\": ").append(summary.invalidDateCount).append(",\n");
                builder.append("      \"labels\": ").append(jsonArray(new ArrayList<>(summary.labels))).append(",\n");
                builder.append("      \"label_counts\": ").append(jsonObject(summary.labelCounts)).append("\n");
                builder.append("    }");
                builder.append(i + 1 == summaries.size() ? "\n" : ",\n");
            }
            builder.append("  ],\n");
            builder.append("  \"overlaps\": [\n");
            for (int i = 0; i < overlaps.size(); i += 1) {
                OverlapSummary overlap = overlaps.get(i);
                builder.append("    {\n");
                builder.append("      \"left\": ").append(json(overlap.leftName)).append(",\n");
                builder.append("      \"right\": ").append(json(overlap.rightName)).append(",\n");
                builder.append("      \"fingerprint_overlap_count\": ").append(overlap.fingerprintOverlapCount).append(",\n");
                builder.append("      \"fingerprint_samples\": ").append(jsonArray(overlap.fingerprintSamples)).append(",\n");
                builder.append("      \"id_overlap_count\": ").append(overlap.idOverlapCount).append(",\n");
                builder.append("      \"id_samples\": ").append(jsonArray(overlap.idSamples)).append(",\n");
                builder.append("      \"temporal_leakage\": ").append(overlap.temporalLeakage).append("\n");
                builder.append("    }");
                builder.append(i + 1 == overlaps.size() ? "\n" : ",\n");
            }
            builder.append("  ],\n");
            builder.append("  \"warnings\": ").append(jsonArray(warnings)).append("\n");
            builder.append("}\n");
            return builder.toString();
        }

        private String formatLabelMix(SplitSummary summary) {
            if (summary.labelCounts.isEmpty()) {
                return "n/a";
            }
            List<String> labels = new ArrayList<>(summary.labelCounts.keySet());
            Collections.sort(labels);
            List<String> parts = new ArrayList<>();
            for (String label : labels) {
                int count = summary.labelCounts.get(label);
                double share = summary.rows == 0 ? 0.0 : (double) count / (double) summary.rows;
                parts.add(label + " " + count + " (" + String.format(Locale.US, "%.1f%%", share * 100.0) + ")");
            }
            return String.join("; ", parts);
        }

        private String formatDateRange(LocalDate minDate, LocalDate maxDate) {
            if (minDate == null && maxDate == null) {
                return "n/a";
            }
            return String.valueOf(minDate) + " -> " + String.valueOf(maxDate);
        }

        private String formatMissingCounts(SplitSummary summary) {
            if (summary.missingValueCounts.isEmpty()) {
                return "n/a";
            }
            List<String> parts = new ArrayList<>();
            for (Map.Entry<String, Integer> entry : summary.missingValueCounts.entrySet()) {
                parts.add(entry.getKey() + " " + entry.getValue());
            }
            return String.join("; ", parts);
        }

        private String json(String value) {
            return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
        }

        private String jsonArray(List<String> values) {
            List<String> encoded = new ArrayList<>();
            for (String value : values) {
                encoded.add(json(value));
            }
            return "[" + String.join(", ", encoded) + "]";
        }

        private String jsonObject(Map<String, Integer> values) {
            List<String> parts = new ArrayList<>();
            for (Map.Entry<String, Integer> entry : values.entrySet()) {
                parts.add(json(entry.getKey()) + ": " + entry.getValue());
            }
            return "{" + String.join(", ", parts) + "}";
        }
    }
}
