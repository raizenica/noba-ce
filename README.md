# Nobara Automation Suite

A collection of Bash scripts to automate common tasks on Nobara Linux (and other Fedora‑based systems).  
All scripts share a common library (`noba-lib.sh`) and a central YAML configuration file.

## 📦 Installation

1. Clone the repository into your `~/bin` directory (or any folder in `$PATH`):
   ```bash
   git clone https://github.com/raizenica/noba.git ~/bin
   cd ~/bin
   ```

2. Make all scripts executable:
   ```bash
   chmod +x *.sh
   ```

3. Install required dependencies (example for Fedora):
   ```bash
   sudo dnf install rsync msmtp ImageMagick yq jq dialog kdialog lm_sensors
   ```

4. (Optional) Set up your configuration file – see [Configuration](#configuration).

## ⚙️ Configuration

The suite uses a single YAML configuration file located at `~/.config/noba/config.yaml`.  
A minimal example:

```yaml
# Nobara unified configuration
email: "your@email.com"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  sources:
    - "/home/raizen/Documents"
    - "/home/raizen/Pictures"

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

logs:
  dir: "/home/raizen/.local/share/noba"

# ... see each script's section below for all available keys
```

All configuration keys are documented in the [Scripts](#scripts) section.

## 📜 Scripts

### `noba` – Central command
Run any script easily:
```bash
noba run backup --dry-run
noba doctor          # same as config-check.sh
noba config --edit   # edit YAML config
```

### `backup-to-nas.sh`
Backs up specified directories to a NAS with retention, space check, and email report.
**YAML keys:**
- `backup.dest` – destination path
- `backup.sources` – list of directories to back up
- `backup.email` – report recipient
- `backup.retention_days` – number of daily backups to keep
- `backup.space_margin_percent` – extra space buffer
- `backup.min_free_space_gb` – minimum free space required

**Usage:**
```bash
backup-to-nas.sh --source /home/user/Docs --dest /mnt/nas/backups
```

### `disk-sentinel.sh`
Monitors disk space and sends alerts when usage exceeds a threshold. Can clean caches.
**YAML keys:** see `disk:` section in example.

### `organize-downloads.sh`
Moves files from `~/Downloads` into categorised folders.
**YAML keys:** under `downloads:`.

### `undo-organizer.sh`
Reverts the last download organisation (uses undo log).

### `checksum.sh`
Generates or verifies checksums with support for multiple algorithms, recursion, and manifests.
**YAML keys:** under `checksum:`.

### `images-to-pdf.sh`
Converts one or more images to a single PDF. Has both CLI and GUI (kdialog) modes.
**YAML keys:** under `images2pdf:`.

### `system-report.sh`
Generates an HTML system report and emails it.
**YAML keys:** uses top‑level `email` and `logs.dir`.

### `motd-generator.sh`
Displays a colourful Message of the Day with system status.
**YAML keys:** under `motd:`.

### `service-watch.sh`
Monitors system services and restarts any that are failed.
**YAML keys:** under `services:`.

### `cloud-backup.sh`
Syncs local backups to a cloud provider using `rclone`.
**YAML keys:** under `cloud:`.

### `temperature-alert.sh`
Sends desktop notifications when CPU temperature exceeds a threshold.
**YAML keys:** uses `disk.threshold` or can be customised.

### `log-rotator.sh`
Compresses log files older than a given number of days.
**YAML keys:** under `log_rotation:`.

### `noba-update.sh`
Pulls the latest version of all scripts from git.
**YAML keys:** under `update:`.

### `noba-dashboard.sh`
Terminal dashboard showing system health, backup status, disk usage, etc.

### `noba-web.sh`
Launches a web‑based dashboard (auto‑refreshes every minute).  
See [Web Dashboard Service](#web-dashboard-service) to run it permanently.

### `noba-cron-setup.sh`
Interactive helper to set up cron jobs for automation scripts.
**YAML keys:** under `cron:` (optional list of scripts).

### `test-all.sh`
Runs basic tests on all scripts to ensure they start correctly.

## 🚀 Usage Examples

**Backup with dry‑run:**
```bash
backup-to-nas.sh --dry-run
```

**Check disk space with a custom threshold:**
```bash
disk-sentinel.sh --threshold 90
```

**Organise downloads (simulate):**
```bash
organize-downloads.sh --dry-run
```

**Convert images to PDF using GUI:**
```bash
images-to-pdf.sh   # opens file picker if kdialog is installed
```

**Generate system report and email it:**
```bash
system-report.sh
```

## 🔧 Automation (cron / systemd)

You can automate scripts using `noba-cron-setup.sh` (interactive) or by writing systemd timers.  
For a permanent web dashboard, see the next section.

## 🌐 Web Dashboard Service

To run `noba-web.sh` automatically at boot as a user service, follow the instructions in [Web Dashboard Service](#web-dashboard-service) below.

## 🤝 Contributing

Feel free to open issues or pull requests on the [GitHub repository](https://github.com/raizenica/noba).

## 📄 License

MIT (or whichever you prefer)
