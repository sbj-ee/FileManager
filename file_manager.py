import os
import gzip
import time
from datetime import datetime, timedelta
import logging
from pathlib import Path

def setup_logging():
    """Configure logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('file_manager.log'),
            logging.StreamHandler()
        ]
    )

def compress_file(file_path):
    """Compress a single file using gzip."""
    try:
        with open(file_path, 'rb') as f_in:
            compressed_path = f"{file_path}.gz"
            with gzip.open(compressed_path, 'wb') as f_out:
                f_out.writelines(f_in)
        # Remove original file after successful compression
        os.remove(file_path)
        logging.info(f"Compressed and removed: {file_path} -> {compressed_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to compress {file_path}: {str(e)}")
        return False

def manage_files(directory, days=5):
    """Scan directory and compress files older than specified days."""
    # Convert days to seconds for comparison
    age_threshold = days * 24 * 60 * 60
    current_time = time.time()

    # Convert directory to Path object for better path handling
    dir_path = Path(directory)
    
    if not dir_path.exists():
        logging.error(f"Directory does not exist: {directory}")
        return

    for file_path in dir_path.glob('*'):
        if file_path.is_file() and not file_path.suffix == '.gz':
            try:
                # Get file modification time
                mtime = file_path.stat().st_mtime
                file_age = current_time - mtime
                
                if file_age > age_threshold:
                    compress_file(file_path)
            except Exception as e:
                logging.error(f"Error processing {file_path}: {str(e)}")

def main():
    """Main function to run the file management script."""
    setup_logging()
    
    # Directory to monitor (modify as needed)
    target_directory = "/path/to/your/log/directory"
    
    logging.info("Starting file management process")
    manage_files(target_directory, days=5)
    logging.info("File management process completed")

if __name__ == "__main__":
    main()
