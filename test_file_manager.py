"""Tests for file_manager.py"""

import gzip
import logging
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from file_manager import (
    ProcessingStats,
    compress_file,
    manage_files,
    setup_logging,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def old_file(temp_dir):
    """Create a file that appears to be 10 days old."""
    file_path = temp_dir / "old_file.log"
    file_path.write_text("This is old content that should be compressed.")
    # Set mtime to 10 days ago
    old_time = time.time() - (10 * 24 * 60 * 60)
    os.utime(file_path, (old_time, old_time))
    return file_path


@pytest.fixture
def new_file(temp_dir):
    """Create a file that appears to be 1 day old."""
    file_path = temp_dir / "new_file.log"
    file_path.write_text("This is new content that should not be compressed.")
    # Set mtime to 1 day ago
    new_time = time.time() - (1 * 24 * 60 * 60)
    os.utime(file_path, (new_time, new_time))
    return file_path


class TestProcessingStats:
    """Tests for ProcessingStats dataclass."""

    def test_default_values(self):
        """Stats should initialize with zero counts."""
        stats = ProcessingStats()
        assert stats.files_scanned == 0
        assert stats.files_compressed == 0
        assert stats.files_skipped == 0
        assert stats.files_failed == 0
        assert stats.bytes_saved == 0
        assert stats.errors == []

    def test_str_representation(self):
        """Stats should have readable string representation."""
        stats = ProcessingStats(
            files_scanned=10,
            files_compressed=5,
            files_skipped=4,
            files_failed=1,
            bytes_saved=1024,
        )
        result = str(stats)
        assert "Scanned: 10" in result
        assert "Compressed: 5" in result
        assert "Skipped: 4" in result
        assert "Failed: 1" in result
        assert "1,024" in result  # bytes_saved with comma formatting


class TestCompressFile:
    """Tests for compress_file function."""

    def test_compress_file_success(self, temp_dir):
        """Should compress file and remove original."""
        file_path = temp_dir / "test.log"
        content = "Test content for compression" * 100
        file_path.write_text(content)
        original_size = file_path.stat().st_size

        success, bytes_saved = compress_file(file_path)

        assert success is True
        assert not file_path.exists()
        assert (temp_dir / "test.log.gz").exists()
        assert bytes_saved > 0

    def test_compress_file_creates_valid_gzip(self, temp_dir):
        """Compressed file should be valid gzip."""
        file_path = temp_dir / "test.log"
        content = "Test content for compression"
        file_path.write_text(content)

        compress_file(file_path)

        compressed_path = temp_dir / "test.log.gz"
        with gzip.open(compressed_path, "rt") as f:
            decompressed = f.read()
        assert decompressed == content

    def test_compress_file_dry_run(self, temp_dir):
        """Dry run should not modify files."""
        file_path = temp_dir / "test.log"
        file_path.write_text("Test content")

        success, bytes_saved = compress_file(file_path, dry_run=True)

        assert success is True
        assert bytes_saved == 0
        assert file_path.exists()
        assert not (temp_dir / "test.log.gz").exists()

    def test_compress_nonexistent_file(self, temp_dir):
        """Should handle nonexistent file gracefully."""
        file_path = temp_dir / "nonexistent.log"

        success, bytes_saved = compress_file(file_path)

        assert success is False
        assert bytes_saved == 0

    def test_compress_preserves_extension(self, temp_dir):
        """Should append .gz to existing extension."""
        file_path = temp_dir / "test.txt"
        file_path.write_text("Test content")

        compress_file(file_path)

        assert (temp_dir / "test.txt.gz").exists()


class TestManageFiles:
    """Tests for manage_files function."""

    def test_compress_old_files(self, temp_dir, old_file):
        """Should compress files older than threshold."""
        stats = manage_files(temp_dir, days=5)

        assert stats.files_scanned == 1
        assert stats.files_compressed == 1
        assert stats.files_skipped == 0
        assert not old_file.exists()
        assert old_file.with_suffix(".log.gz").exists()

    def test_skip_new_files(self, temp_dir, new_file):
        """Should skip files newer than threshold."""
        stats = manage_files(temp_dir, days=5)

        assert stats.files_scanned == 1
        assert stats.files_compressed == 0
        assert stats.files_skipped == 1
        assert new_file.exists()

    def test_skip_already_compressed(self, temp_dir):
        """Should skip .gz files."""
        gz_file = temp_dir / "already.log.gz"
        gz_file.write_bytes(b"fake gzip content")
        old_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(gz_file, (old_time, old_time))

        stats = manage_files(temp_dir, days=5)

        assert stats.files_scanned == 0
        assert gz_file.exists()

    def test_mixed_files(self, temp_dir, old_file, new_file):
        """Should handle mix of old and new files."""
        stats = manage_files(temp_dir, days=5)

        assert stats.files_scanned == 2
        assert stats.files_compressed == 1
        assert stats.files_skipped == 1

    def test_nonexistent_directory(self):
        """Should handle nonexistent directory."""
        stats = manage_files("/nonexistent/path")

        assert stats.files_scanned == 0
        assert len(stats.errors) == 1
        assert "does not exist" in stats.errors[0]

    def test_file_instead_of_directory(self, temp_dir):
        """Should handle file path instead of directory."""
        file_path = temp_dir / "not_a_dir.txt"
        file_path.write_text("content")

        stats = manage_files(file_path)

        assert stats.files_scanned == 0
        assert len(stats.errors) == 1
        assert "not a directory" in stats.errors[0]

    def test_dry_run_mode(self, temp_dir, old_file):
        """Dry run should not modify files."""
        stats = manage_files(temp_dir, days=5, dry_run=True)

        assert stats.files_scanned == 1
        assert stats.files_compressed == 1  # Counted as would-be compressed
        assert old_file.exists()  # But file still exists

    def test_recursive_mode(self, temp_dir):
        """Should process subdirectories when recursive=True."""
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        subfile = subdir / "nested.log"
        subfile.write_text("Nested content")
        old_time = time.time() - (10 * 24 * 60 * 60)
        os.utime(subfile, (old_time, old_time))

        # Without recursive
        stats = manage_files(temp_dir, days=5, recursive=False)
        assert stats.files_scanned == 0

        # With recursive
        stats = manage_files(temp_dir, days=5, recursive=True)
        assert stats.files_scanned == 1
        assert stats.files_compressed == 1

    def test_custom_days_threshold(self, temp_dir):
        """Should respect custom days threshold."""
        file_path = temp_dir / "test.log"
        file_path.write_text("Content")
        # Set to 3 days old
        old_time = time.time() - (3 * 24 * 60 * 60)
        os.utime(file_path, (old_time, old_time))

        # With 5 day threshold, should skip
        stats = manage_files(temp_dir, days=5)
        assert stats.files_skipped == 1

        # With 2 day threshold, should compress
        stats = manage_files(temp_dir, days=2)
        assert stats.files_compressed == 1


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_console_only(self):
        """Should configure console-only logging."""
        # Reset logging
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        setup_logging()

        assert len(logging.root.handlers) >= 1

    def test_setup_logging_with_file(self, temp_dir):
        """Should configure file and console logging."""
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        log_file = temp_dir / "test.log"
        setup_logging(log_file=str(log_file))

        # Log something
        logging.info("Test message")

        assert log_file.exists()


class TestCLI:
    """Tests for command line interface."""

    def test_cli_help(self):
        """CLI should show help."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "file_manager.py", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
        )
        assert result.returncode == 0
        assert "Compress files older than" in result.stdout
        assert "--days" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--recursive" in result.stdout

    def test_cli_dry_run(self, temp_dir, old_file):
        """CLI dry run should not modify files."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "file_manager.py",
                str(temp_dir),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
        )
        assert result.returncode == 0
        assert old_file.exists()
        assert "DRY RUN" in result.stderr or "DRY RUN" in result.stdout

    def test_cli_nonexistent_directory(self):
        """CLI should handle nonexistent directory."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "file_manager.py", "/nonexistent/path"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
        )
        assert result.returncode == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
