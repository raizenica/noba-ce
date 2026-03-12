# Nobara Automation Scripts

Personal collection of automation scripts for my Nobara Linux system.

## Scripts

### `backup-to-nas.sh`
- **Description**: Backs up selected files/folders to my NAS.
- **Usage**: Can be run directly or integrated into Dolphin service menu.

### `checksum.sh`
- **Description**: Generates MD5, SHA1, or SHA256 checksums for files.
- **Usage**: Used by the "Generate Checksum..." service menu. Select files in Dolphin, right-click → Generate Checksum..., choose algorithm.

### `images-to-pdf.sh`
- **Description**: Converts multiple images into a single PDF.
- **Usage**: Used by the "Convert to PDF..." service menu. Select images, right-click → Convert to PDF..., choose save location.

## Installation

Clone this repository and make scripts executable:

```bash
git clone https://github.com/raizenica/noba.git
cd noba
chmod +x *.sh
