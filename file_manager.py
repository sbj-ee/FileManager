"""
File Manager - A log rotation utility that compresses old files.

Scans a directory for files older than a specified threshold,
compresses them using gzip, and removes the originals.
"""

import argparse
import gzip
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProcessingStats:
    """Statistics from file processing."""

    files_scanned: int = 0
    files_compressed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_saved: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Scanned: {self.files_scanned}, "
            f"Compressed: {self.files_compressed}, "
            f"Skipped: {self.files_skipped}, "
            f"Failed: {self.files_failed}, "
            f"Bytes saved: {self.bytes_saved:,}"
        )


def setup_logging(log_file: str | None = None, verbose: bool = False) -> None:
    """Configure logging for the script.

    Args:
        log_file: Path to log file. If None, logs only to console.
        verbose: If True, set log level to DEBUG.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def compress_file(file_path: Path, dry_run: bool = False) -> tuple[bool, int]:
    """Compress a single file using gzip.

    Args:
        file_path: Path to the file to compress.
        dry_run: If True, simulate compression without making changes.

    Returns:
        Tuple of (success: bool, bytes_saved: int)
    """
    compressed_path = file_path.with_suffix(file_path.suffix + ".gz")

    if dry_run:
        logging.info(f"[DRY-RUN] Would compress: {file_path} -> {compressed_path}")
        return True, 0

    try:
        original_size = file_path.stat().st_size

        # Compress file using shutil for memory efficiency
        with open(file_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Verify compressed file exists and is valid
        if not compressed_path.exists():
            raise IOError(f"Compressed file not created: {compressed_path}")

        compressed_size = compressed_path.stat().st_size
        if compressed_size == 0:
            compressed_path.unlink()
            raise IOError("Compressed file is empty")

        # Remove original file after successful compression
        file_path.unlink()
        bytes_saved = original_size - compressed_size

        logging.info(
            f"Compressed: {file_path} -> {compressed_path} "
            f"(saved {bytes_saved:,} bytes)"
        )
        return True, bytes_saved

    except Exception as e:
        logging.error(f"Failed to compress {file_path}: {e}")
        # Clean up partial compressed file if it exists
        if compressed_path.exists():
            try:
                compressed_path.unlink()
            except OSError:
                pass
        return False, 0


def manage_files(
    directory: str | Path,
    days: int = 5,
    dry_run: bool = False,
    recursive: bool = False,
) -> ProcessingStats:
    """Scan directory and compress files older than specified days.

    Args:
        directory: Directory to scan for files.
        days: Compress files older than this many days.
        dry_run: If True, simulate without making changes.
        recursive: If True, process subdirectories.

    Returns:
        ProcessingStats with results of the operation.
    """
    stats = ProcessingStats()
    age_threshold = days * 24 * 60 * 60
    current_time = time.time()

    dir_path = Path(directory)

    if not dir_path.exists():
        logging.error(f"Directory does not exist: {directory}")
        stats.errors.append(f"Directory does not exist: {directory}")
        return stats

    if not dir_path.is_dir():
        logging.error(f"Path is not a directory: {directory}")
        stats.errors.append(f"Path is not a directory: {directory}")
        return stats

    # Choose glob pattern based on recursive flag
    pattern = "**/*" if recursive else "*"

    for file_path in dir_path.glob(pattern):
        if not file_path.is_file():
            continue

        # Skip already compressed files
        if file_path.suffix == ".gz":
            continue

        stats.files_scanned += 1

        try:
            mtime = file_path.stat().st_mtime
            file_age = current_time - mtime

            if file_age > age_threshold:
                success, bytes_saved = compress_file(file_path, dry_run)
                if success:
                    stats.files_compressed += 1
                    stats.bytes_saved += bytes_saved
                else:
                    stats.files_failed += 1
                    stats.errors.append(f"Failed to compress: {file_path}")
            else:
                stats.files_skipped += 1
                logging.debug(f"Skipped (too recent): {file_path}")

        except Exception as e:
            stats.files_failed += 1
            stats.errors.append(f"Error processing {file_path}: {e}")
            logging.error(f"Error processing {file_path}: {e}")

    return stats


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compress files older than a specified number of days.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /var/log/myapp              # Compress files older than 5 days
  %(prog)s /var/log/myapp -d 7         # Compress files older than 7 days
  %(prog)s /var/log/myapp --dry-run    # Show what would be compressed
  %(prog)s /var/log/myapp -r           # Include subdirectories
        """,
    )
    parser.add_argument(
        "directory",
        help="Directory to scan for files",
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=5,
        help="Compress files older than this many days (default: 5)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process subdirectories recursively",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "-l", "--log-file",
        help="Path to log file (default: console only)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    return parser.parse_args()


def main() -> int:
    """Main function to run the file management script.

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    args = parse_args()

    setup_logging(log_file=args.log_file, verbose=args.verbose)

    if args.dry_run:
        logging.info("=== DRY RUN MODE - No changes will be made ===")

    logging.info(f"Starting file management: {args.directory}")
    logging.info(f"Compressing files older than {args.days} days")

    stats = manage_files(
        directory=args.directory,
        days=args.days,
        dry_run=args.dry_run,
        recursive=args.recursive,
    )

    logging.info(f"Completed: {stats}")

    if stats.errors:
        logging.warning(f"Encountered {len(stats.errors)} error(s)")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
