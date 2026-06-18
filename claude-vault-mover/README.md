# claude-vault-mover

A macOS LaunchAgent that watches `~/Downloads` and moves files downloaded from
Claude (`claude.ai` / `anthropic`) into an Obsidian vault.

## How it works

- `com.parashuram.claude-vault-mover.plist` is a `launchd` agent with a
  `WatchPaths` entry on `~/Downloads`; `launchd` re-runs the script whenever that
  directory changes.
- `claude-vault-mover.sh` scans `~/Downloads` and, for each finished file, reads
  the macOS quarantine attribute `kMDItemWhereFroms` (the source URL the browser
  recorded). If the source matches an entry in the `MATCH` array it moves the
  file into `VAULT_INBOX`.

The filter **fails safe**: files with no `kMDItemWhereFroms` (locally created
files, or in-app downloads that use `blob:`/`data:` URLs) are skipped, so it
never moves anything it can't positively identify as a Claude download. If a file
of the same name already exists in the destination, it is **skipped** and left in
`~/Downloads`.

## Configuration

Edit `claude-vault-mover.sh`:

- `VAULT_INBOX` — absolute destination path.
- `MATCH` — source-URL substrings that mark a file as "from Claude".

Edit the plist (absolute paths only — `launchd` does not expand `~`):

- `ProgramArguments` — path to the installed script.
- `WatchPaths` — the watched download directory.
- `StandardOutPath` / `StandardErrorPath` — log paths.

## Install

```bash
mkdir -p ~/.local/bin ~/Library/LaunchAgents
cp claude-vault-mover.sh ~/.local/bin/
chmod +x ~/.local/bin/claude-vault-mover.sh
cp com.parashuram.claude-vault-mover.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.parashuram.claude-vault-mover.plist
```

## Reload after editing

```bash
launchctl bootout    gui/$(id -u) ~/Library/LaunchAgents/com.parashuram.claude-vault-mover.plist
launchctl bootstrap  gui/$(id -u) ~/Library/LaunchAgents/com.parashuram.claude-vault-mover.plist
```

## Logs

- Activity: `~/Library/Logs/claude-vault-mover.log` (`moved:` / `skip` lines)
- Errors:   `~/Library/Logs/claude-vault-mover.err.log` (e.g. TCC/permission
  denials reading `~/Downloads` — grant the agent access if you see these)

## Notes

- The agent runs on *every* change to `~/Downloads`, so it also sweeps up
  matching files already sitting there, not just new ones.
