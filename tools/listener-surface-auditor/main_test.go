package main

import (
	"os"
	"path/filepath"
	"testing"
)

func loadTestCapture(t *testing.T) captureFixture {
	t.Helper()
	capture, err := loadCaptureFixture(filepath.Join("fixtures", "exposed-development-host.json"))
	if err != nil {
		t.Fatalf("load capture: %v", err)
	}
	return capture
}

func TestCapturedListenerReport(t *testing.T) {
	capture := loadTestCapture(t)
	processes, err := parseProcessMap(capture.Tasklist)
	if err != nil {
		t.Fatalf("parse process map: %v", err)
	}
	connections := parseTCPConnections(capture.Netstat)
	findings := buildFindings(connections, processes, map[int]struct{}{})

	if len(connections) != 5 {
		t.Fatalf("expected 5 listening TCP connections, got %d", len(connections))
	}
	if len(findings) != 5 {
		t.Fatalf("expected 5 findings, got %d", len(findings))
	}
	if got := findings[0]; got.Connection.LocalPort != 3000 || got.Process.Image != "node.exe" || got.RiskScore != 91 || got.RiskLabel != "high" {
		t.Fatalf("unexpected highest-risk finding: %+v", got)
	}
	if got := findings[2]; got.Connection.LocalPort != 5432 || got.Exposure != "private-lan" || got.RiskScore != 58 {
		t.Fatalf("unexpected private-LAN finding: %+v", got)
	}
	if got := findings[4]; got.Connection.LocalPort != 9229 || got.Exposure != "loopback" || got.RiskScore != 21 {
		t.Fatalf("unexpected loopback finding: %+v", got)
	}

	rollups := buildProcessRollups(findings)
	if len(rollups) != 4 {
		t.Fatalf("expected 4 process rollups, got %d", len(rollups))
	}
	if got := rollups[0]; got.PID != 4242 || got.ListenerCount != 2 || got.HighestRiskPort != 3000 || got.WildcardCount != 1 {
		t.Fatalf("unexpected node rollup: %+v", got)
	}
}

func TestCapturedListenerFiltersAndTCPStats(t *testing.T) {
	capture := loadTestCapture(t)
	processes, err := parseProcessMap(capture.Tasklist)
	if err != nil {
		t.Fatalf("parse process map: %v", err)
	}
	findings := buildFindings(parseTCPConnections(capture.Netstat), processes, parsePortSet("445, 65535, invalid"))
	if len(findings) != 4 {
		t.Fatalf("expected ignored port to leave 4 findings, got %d", len(findings))
	}
	for _, finding := range findings {
		if finding.Connection.LocalPort == 445 {
			t.Fatal("ignored port 445 remained in findings")
		}
	}

	breakdown := buildExposureBreakdown(findings)
	if breakdown["wildcard"] != 1 || breakdown["private-lan"] != 1 || breakdown["loopback"] != 2 {
		t.Fatalf("unexpected exposure breakdown: %#v", breakdown)
	}
	stats := parseTCPStats(capture.TCPStats)
	if stats["Active Opens"] != "42" || stats["Failed Connection Attempts"] != "3" {
		t.Fatalf("unexpected TCP stats: %#v", stats)
	}
}

func TestCaptureFixtureValidation(t *testing.T) {
	tempPath := filepath.Join(t.TempDir(), "invalid.json")
	if err := os.WriteFile(tempPath, []byte(`{"host":"fixture","captured_at":"not-a-date","tasklist":"x","netstat":"y"}`), 0o644); err != nil {
		t.Fatalf("write invalid fixture: %v", err)
	}
	if _, err := loadCaptureFixture(tempPath); err == nil {
		t.Fatal("expected invalid captured_at to fail validation")
	}
}
