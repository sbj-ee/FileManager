# FileManager

A log rotation utility that compresses old files using gzip. Scans a directory for files older than a specified threshold, compresses them, and removes the originals.

## Features

- **Age-based compression**: Compress files older than N days (default: 5)
- **Gzip compression**: Creates `.gz` files and removes originals
- **Dry-run mode**: Preview what would be compressed without making changes
- **Recursive mode**: Optionally process subdirectories
- **Statistics**: Reports files scanned, compressed, skipped, and bytes saved
- **Safe operation**: Verifies compression before deleting originals
- **Zero dependencies**: Uses only Python standard library

## Installation

```bash
git clone https://github.com/sbj-ee/FileManager.git
cd FileManager
```

## Usage

```bash
# Compress files older than 5 days (default)
python file_manager.py /var/log/myapp

# Compress files older than 7 days
python file_manager.py /var/log/myapp -d 7

# Preview what would be compressed (dry-run)
python file_manager.py /var/log/myapp --dry-run

# Include subdirectories
python file_manager.py /var/log/myapp -r

# Verbose output with log file
python file_manager.py /var/log/myapp -v -l /var/log/file_manager.log
```

## CLI Options

| Option | Description |
|--------|-------------|
| `directory` | Directory to scan for files (required) |
| `-d`, `--days` | Compress files older than this many days (default: 5) |
| `-r`, `--recursive` | Process subdirectories recursively |
| `-n`, `--dry-run` | Show what would be done without making changes |
| `-l`, `--log-file` | Path to log file (default: console only) |
| `-v`, `--verbose` | Enable verbose/debug output |

## Examples

```bash
$ python file_manager.py /var/log/myapp --dry-run
2024-01-15 10:30:00 - INFO - === DRY RUN MODE - No changes will be made ===
2024-01-15 10:30:00 - INFO - Starting file management: /var/log/myapp
2024-01-15 10:30:00 - INFO - Compressing files older than 5 days
2024-01-15 10:30:00 - INFO - [DRY-RUN] Would compress: app.log.1 -> app.log.1.gz
2024-01-15 10:30:00 - INFO - [DRY-RUN] Would compress: app.log.2 -> app.log.2.gz
2024-01-15 10:30:00 - INFO - Completed: Scanned: 2, Compressed: 2, Skipped: 0, Failed: 0, Bytes saved: 0

$ python file_manager.py /var/log/myapp
2024-01-15 10:31:00 - INFO - Starting file management: /var/log/myapp
2024-01-15 10:31:00 - INFO - Compressing files older than 5 days
2024-01-15 10:31:00 - INFO - Compressed: app.log.1 -> app.log.1.gz (saved 15,234 bytes)
2024-01-15 10:31:00 - INFO - Compressed: app.log.2 -> app.log.2.gz (saved 12,456 bytes)
2024-01-15 10:31:00 - INFO - Completed: Scanned: 2, Compressed: 2, Skipped: 0, Failed: 0, Bytes saved: 27,690
```

## Scheduling with Cron

Run daily at midnight:

```bash
0 0 * * * /usr/bin/python3 /path/to/file_manager.py /var/log/myapp -l /var/log/file_manager.log
```

## Safety Features

- **Skips .gz files**: Won't try to compress already-compressed files
- **Verifies compression**: Checks compressed file exists and is non-empty before deleting original
- **Cleans up on failure**: Removes partial compressed files if compression fails
- **Dry-run mode**: Test before running for real
- **Error handling**: Continues processing other files if one fails

## Running Tests

```bash
pip install pytest
pytest test_file_manager.py -v
```

## Requirements

- Python 3.10+
- pytest (for running tests only)

## License

MIT
