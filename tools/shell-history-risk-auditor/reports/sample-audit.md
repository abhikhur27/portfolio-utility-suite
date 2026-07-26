# Shell History Risk Audit

- Files scanned: 1
- Commands scanned: 5
- High findings: 2
- Medium findings: 1
- Low findings: 1

## Findings

- `high` remote script execution at `examples\ConsoleHost_history.txt`:4: Downloads are being piped straight into a shell or expression evaluator.
  Shell: `powershell`
  Command: `irm https://example.com/bootstrap.ps1 | iex`
- `high` secret-like token at `examples\ConsoleHost_history.txt`:5: Command contains a token- or credential-like value that should not live in shell history.
  Shell: `powershell`
  Command: `curl https://api.internal -H "Authorization: Bearer sk-demo-history-token"`
- `medium` history-rewriting git command at `examples\ConsoleHost_history.txt`:3: Command rewrites git history or force-pushes a branch.
  Shell: `powershell`
  Command: `git push --force origin main`
- `low` safety bypass at `examples\ConsoleHost_history.txt`:2: Command weakens an execution or file-permission safety boundary.
  Shell: `powershell`
  Command: `Set-ExecutionPolicy Bypass -Scope Process`