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
from enum import Enum
from pathlib import Path


class CompressResult(Enum):
    """Outcome of attempting to compress a single file."""

    SUCCESS = "success"
    FAILED = "failed"
    IN_USE = "in_use"


@dataclass
class ProcessingStats:
    """Statistics from file processing."""

    files_scanned: int = 0
    files_compressed: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    files_in_use: int = 0
    bytes_saved: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Scanned: {self.files_scanned}, "
            f"Compressed: {self.files_compressed}, "
            f"Skipped: {self.files_skipped}, "
            f"In use: {self.files_in_use}, "
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


def compress_file(
    file_path: Path, dry_run: bool = False, compresslevel: int = 9
) -> tuple[CompressResult, int]:
    """Compress a single file using gzip.

    To avoid corrupting or losing data from a file that is still being
    written, the original's size and mtime are re-checked after compression;
    if they changed during the copy the original is left untouched.

    Args:
        file_path: Path to the file to compress.
        dry_run: If True, simulate compression without making changes.
        compresslevel: gzip compression level (1=fastest, 9=best, default: 9).

    Returns:
        Tuple of (result: CompressResult, bytes_saved: int)
    """
    compressed_path = file_path.with_suffix(file_path.suffix + ".gz")

    if dry_run:
        logging.info(f"[DRY-RUN] Would compress: {file_path} -> {compressed_path}")
        return CompressResult.SUCCESS, 0

    try:
        stat_before = file_path.stat()
        original_size = stat_before.st_size

        # Compress file using shutil for memory efficiency
        with open(file_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb", compresslevel=compresslevel) as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Verify compressed file exists and is valid
        if not compressed_path.exists():
            raise IOError(f"Compressed file not created: {compressed_path}")

        compressed_size = compressed_path.stat().st_size
        if compressed_size == 0:
            compressed_path.unlink()
            raise IOError("Compressed file is empty")

        # Active-file safety: if the original changed while we were reading it,
        # our compressed copy may be torn. Discard it and keep the original so a
        # live writer doesn't lose data to an unlinked inode.
        stat_after = file_path.stat()
        if (
            stat_after.st_mtime_ns != stat_before.st_mtime_ns
            or stat_after.st_size != original_size
        ):
            logging.warning(
                f"Skipped (modified during compression): {file_path}"
            )
            compressed_path.unlink()
            return CompressResult.IN_USE, 0

        # Preserve original metadata (mode, mtime, etc.) on the compressed file
        # so permissions and age-based handling carry over.
        shutil.copystat(file_path, compressed_path)

        # Remove original file after successful compression
        file_path.unlink()
        bytes_saved = original_size - compressed_size

        logging.info(
            f"Compressed: {file_path} -> {compressed_path} "
            f"(saved {bytes_saved:,} bytes)"
        )
        return CompressResult.SUCCESS, bytes_saved

    except Exception as e:
        logging.error(f"Failed to compress {file_path}: {e}")
        # Clean up partial compressed file if it exists
        if compressed_path.exists():
            try:
                compressed_path.unlink()
            except OSError:
                pass
        return CompressResult.FAILED, 0


def manage_files(
    directory: str | Path,
    days: int = 5,
    dry_run: bool = False,
    recursive: bool = False,
    pattern: str = "*",
    compresslevel: int = 9,
    min_size: int = 0,
) -> ProcessingStats:
    """Scan directory and compress files older than specified days.

    Args:
        directory: Directory to scan for files.
        days: Compress files older than this many days.
        dry_run: If True, simulate without making changes.
        recursive: If True, process subdirectories.
        pattern: Glob pattern selecting which files to consider (default: "*").
        compresslevel: gzip compression level (1=fastest, 9=best, default: 9).
        min_size: Skip files smaller than this many bytes (default: 0).

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

    # Apply the pattern at every level when recursing, else only the top level.
    glob_pattern = f"**/{pattern}" if recursive else pattern

    for file_path in dir_path.glob(glob_pattern):
        # Skip symlinks to avoid compressing files outside the tree,
        # following dangling links, or recursing through linked directories.
        if file_path.is_symlink():
            logging.debug(f"Skipped (symlink): {file_path}")
            continue

        if not file_path.is_file():
            continue

        # Skip already compressed files
        if file_path.suffix == ".gz":
            continue

        stats.files_scanned += 1

        try:
            file_stat = file_path.stat()
            file_age = current_time - file_stat.st_mtime

            if file_stat.st_size < min_size:
                stats.files_skipped += 1
                logging.debug(f"Skipped (smaller than min-size): {file_path}")
            elif file_age > age_threshold:
                result, bytes_saved = compress_file(
                    file_path, dry_run, compresslevel
                )
                if result is CompressResult.SUCCESS:
                    stats.files_compressed += 1
                    stats.bytes_saved += bytes_saved
                elif result is CompressResult.IN_USE:
                    stats.files_in_use += 1
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


def non_negative_int(value: str) -> int:
    """Argparse type for a non-negative integer.

    Args:
        value: Raw command line argument value.

    Returns:
        The parsed integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not a non-negative integer.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative, got {parsed}")
    return parsed


def compression_level(value: str) -> int:
    """Argparse type for a gzip compression level (1-9).

    Args:
        value: Raw command line argument value.

    Returns:
        The parsed integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not an integer in 1-9.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if not 1 <= parsed <= 9:
        raise argparse.ArgumentTypeError(f"must be between 1 and 9, got {parsed}")
    return parsed


def human_size(value: str) -> int:
    """Argparse type for a non-negative size with an optional K/M/G suffix.

    Examples: "0", "512", "10K", "5M", "1G" (suffixes are powers of 1024).

    Args:
        value: Raw command line argument value.

    Returns:
        The size in bytes.

    Raises:
        argparse.ArgumentTypeError: If the value cannot be parsed as a
            non-negative size.
    """
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
    text = value.strip().upper()
    if text[-1:] in multipliers:
        number, multiplier = text[:-1], multipliers[text[-1]]
    else:
        number, multiplier = text, 1
    try:
        parsed = int(number)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid size value: {value!r}")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative, got {value!r}")
    return parsed * multiplier


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
  %(prog)s /var/log/myapp -p '*.log'   # Only files matching the pattern
  %(prog)s /var/log/myapp -c 1         # Fastest compression
  %(prog)s /var/log/myapp -m 4K        # Skip files smaller than 4 KiB
        """,
    )
    parser.add_argument(
        "directory",
        help="Directory to scan for files",
    )
    parser.add_argument(
        "-d", "--days",
        type=non_negative_int,
        default=5,
        help="Compress files older than this many days (default: 5)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process subdirectories recursively",
    )
    parser.add_argument(
        "-p", "--pattern",
        default="*",
        help="Glob pattern selecting which files to consider (default: '*')",
    )
    parser.add_argument(
        "-c", "--compresslevel",
        type=compression_level,
        default=9,
        help="gzip compression level, 1=fastest to 9=best (default: 9)",
    )
    parser.add_argument(
        "-m", "--min-size",
        type=human_size,
        default=0,
        metavar="BYTES",
        help="Skip files smaller than this size; accepts K/M/G suffixes "
             "(default: 0, no minimum)",
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
        pattern=args.pattern,
        compresslevel=args.compresslevel,
        min_size=args.min_size,
    )

    logging.info(f"Completed: {stats}")

    if stats.errors:
        logging.warning(f"Encountered {len(stats.errors)} error(s)")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
