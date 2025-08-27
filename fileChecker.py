import os
import hashlib
import psutil
from tqdm import tqdm

# Define the list of file extensions for images and videos
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif", ".heic", ".raw", ".raf"}
VIDEO_EXTENSIONS = {".mov", ".mp4"}

# Flag to toggle between full hashing and filename/filesize matching
USE_HASHING = False

def detect_sd_cards():
    """
    Detects external drives (SD cards or USB drives) connected to the system.

    Returns:
        list: A list of paths to the detected SD cards.
    """
    external_drives = []
    partitions = psutil.disk_partitions()
    for partition in partitions:
        if "removable" in partition.opts.lower():
            external_drives.append(partition.device)
    return external_drives

def calculate_file_hash(filepath, chunk_size=8192, video_partial=True):
    """
    Calculates the hash of a file. For videos, hashes only specific chunks (first and last parts).
    
    Args:
        filepath (str): Path to the file.
        chunk_size (int): Size of chunks to read for hashing.
        video_partial (bool): Whether to hash only a part of video files.

    Returns:
        str: The hash of the file.
    """
    hash_md5 = hashlib.md5()
    file_extension = os.path.splitext(filepath)[1].lower()

    if file_extension in VIDEO_EXTENSIONS and video_partial:
        with open(filepath, "rb") as f:
            # Read the first few chunks
            for _ in range(4):  # Hash the first `4 * chunk_size` bytes
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hash_md5.update(chunk)

            # Seek to the end and hash the last few chunks
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(max(file_size - (4 * chunk_size), 0))  # Go back `4 * chunk_size` from the end
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hash_md5.update(chunk)
    else:
        with open(filepath, "rb") as f:
            # For images or if full hash is needed, hash the whole file
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_md5.update(chunk)

    return hash_md5.hexdigest()

def get_file_info(directory):
    """
    Recursively collects all files in a directory and their metadata (filename, filesize, and optional hash).

    Args:
        directory (str): Path to the directory to scan.

    Returns:
        dict: A dictionary with full file paths as keys and metadata as values (filename, filesize, and optional hash).
    """
    file_info = {}
    total_files = sum(len(files) for _, _, files in os.walk(directory))
    progress = tqdm(total=total_files, desc=f"Processing files in {directory}")

    for root, _, files in os.walk(directory):
        for file in files:
            file_extension = os.path.splitext(file)[1].lower()
            if file_extension in IMAGE_EXTENSIONS or file_extension in VIDEO_EXTENSIONS or True:
                filepath = os.path.join(root, file)
                filesize = os.path.getsize(filepath)

                # Add hash only if USE_HASHING is enabled
                file_hash = calculate_file_hash(filepath) if USE_HASHING else None

                file_info[filepath] = {
                    "filename": file,
                    "filesize": filesize,
                    "hash": file_hash
                }
            progress.update(1)

    progress.close()
    return file_info

def normalize_filename_variants(filename):
    """
    Generates all possible filename variants (original and with single-letter prefix removed).

    Args:
        filename (str): Original filename.

    Returns:
        set: A set containing the original filename and the normalized variant.
    """
    variants = {filename}
    if len(filename) > 1 and filename[0].isalpha():
        variants.add(filename[1:])  # Add version without the single-letter prefix
    return variants

def check_files(sd_card_paths, local_folder_paths):
    """
    Checks if all files (images and videos) on the SD cards are present in the local folder.

    Args:
        sd_card_paths (list): List of paths to the SD cards.
        local_folder_path (str): Path to the local folder directory.

    Returns:
        dict: A dictionary of missing files for each SD card.
    """
    # Get metadata for files in the local folder
    
    local_files = {}
    for folder in local_folder_paths:
        print(f"Scanning local folder ({folder})...")
        local_files |= get_file_info(folder)

    # Create a lookup for local files using filename and filesize (and hash if enabled)
    local_lookup = {}
    for path, metadata in local_files.items():
        for variant in normalize_filename_variants(metadata["filename"]):
            local_lookup[(variant, metadata["filesize"], metadata["hash"])] = path

    missing_files_by_sd = {}

    for sd_card_path in sd_card_paths:
        print(f"\nScanning SD card ({sd_card_path})...")
        sd_files = get_file_info(sd_card_path)
        #print(sd_files)

        # Find files on the SD card that are not in the local folder
        missing_files = []
        for sd_path, sd_metadata in sd_files.items():
            match_key = (sd_metadata["filename"], sd_metadata["filesize"], sd_metadata["hash"])
            normalized_keys = [
                (variant, sd_metadata["filesize"], sd_metadata["hash"])
                for variant in normalize_filename_variants(sd_metadata["filename"])
            ]

            if not any(key in local_lookup for key in normalized_keys):
                missing_files.append(sd_path)

        missing_files_by_sd[sd_card_path] = missing_files

    return missing_files_by_sd

def main():
    # Automatically detect SD cards
    sd_cards = detect_sd_cards()
    if not sd_cards:
        print("No SD cards detected. Please insert an SD card and try again.")
        return

    print("Detected SD cards:")
    for idx, sd_card in enumerate(sd_cards, 1):
        print(f"{idx}. {sd_card}")

    # Ask the user to select one or more SD cards
    selected_indices = input("Select the SD cards to use (enter numbers separated by commas): ").strip()
    try:
        selected_sd_cards = [sd_cards[int(idx) - 1] for idx in selected_indices.split(",")]
    except (ValueError, IndexError):
        print("Invalid selection. Exiting.")
        return

    # Local folders for photo storage
    local_folder_paths = ["E:\\Lishmoa-Organized", "E:\\Lishmoa-RawFootage"]

    for path in local_folder_paths:
        if not os.path.isdir(path):
            print(f"Local folder path '{path}' does not exist.")
            return

    # Ensure nothing on either drive is modified (read-only operations)
    print("\nComparing files on selected SD cards against the local folder...")
    missing_files_by_sd = check_files(selected_sd_cards, local_folder_paths)

    # Report missing files
    for sd_card, missing_files in missing_files_by_sd.items():
        print(f"\nMissing files for SD card ({sd_card}):")
        if missing_files:
            for file in missing_files:
                print(file)
        else:
            print("All files are present in the local folder.")

if __name__ == "__main__":
    main()
