# Windows Setup

Windows-specific installation and usage notes.

---

## Installation on Windows

### Via winget (Recommended)

Claude Code supports Windows Package Manager:

```powershell
winget install Anthropic.ClaudeCode
```

Then install the skill:

```
/plugin marketplace add OthmanAdi/planning-with-files
/plugin install planning-with-files@planning-with-files
```

### Local Plugin Development

```powershell
git clone https://github.com/OthmanAdi/planning-with-files.git
claude --plugin-dir .\planning-with-files
```

`--plugin-dir` is session-only. Marketplace installs are managed by Claude Code under `%USERPROFILE%\.claude\plugins\cache\`; do not clone into or edit that cache.

### Skills Only

```powershell
git clone https://github.com/OthmanAdi/planning-with-files.git
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse planning-with-files\skills\planning-with-files $env:USERPROFILE\.claude\skills\
```

---

## Path Differences

| Unix/macOS | Windows |
|------------|---------|
| `~/.claude/skills/` | `%USERPROFILE%\.claude\skills\` |
| `~/.claude/plugins/cache/` | `%USERPROFILE%\.claude\plugins\cache\` |
| Local checkout passed to `--plugin-dir` | Any explicit Windows path, including paths with spaces |

---

## Shell Script Compatibility

The helper scripts (`init-session.sh`, `check-complete.sh`) are bash scripts.

### Option 1: Use Git Bash

If you have Git for Windows installed, run scripts in Git Bash:

```bash
./scripts/init-session.sh
```

### Option 2: Use WSL

```bash
wsl ./scripts/init-session.sh
```

### Option 3: Manual alternative

Instead of running scripts, manually create the files:

```powershell
# Copy templates to current directory
Copy-Item templates\task_plan.md .
Copy-Item templates\findings.md .
Copy-Item templates\progress.md .
```

---

## Hook Commands

Claude Code plugin hooks use the cache-safe `${CLAUDE_PLUGIN_ROOT}` and a Unix-compatible shell. On Windows:

- Hooks run in a Unix-compatible shell environment
- Commands like `cat`, `head`, `echo` work automatically
- No changes needed to the skill configuration

---

## Common Windows Issues

### Path separators

If you see path errors, ensure you're using the correct separator:

```powershell
# Windows
$env:USERPROFILE\.claude\skills\

# Not Unix-style
~/.claude/skills/
```

### Line endings

If templates appear corrupted, check line endings:

```powershell
# Convert to Windows line endings if needed
(Get-Content template.md) | Set-Content -Encoding UTF8 template.md
```

### Permission errors

Run PowerShell as Administrator if you get permission errors:

```powershell
# Right-click PowerShell → Run as Administrator
```

---

## Terminal Recommendations

For best experience on Windows:

1. **Windows Terminal** - Modern terminal with good Unicode support
2. **Git Bash** - Unix-like environment on Windows
3. **WSL** - Full Linux environment

---

## Need Help?

Open an issue at [github.com/OthmanAdi/planning-with-files/issues](https://github.com/OthmanAdi/planning-with-files/issues).
