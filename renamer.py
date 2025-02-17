import os
import json
import subprocess
from datetime import datetime

# Define your Takeout folder path
takeout_folder = "D:\RawFootage"

# Function to convert Unix timestamp to EXIF-compatible format
def convert_timestamp(unix_timestamp):
    return datetime.utcfromtimestamp(int(unix_timestamp)).strftime('%Y:%m:%d %H:%M:%S')

# Function to update filesystem creation date on Windows
def update_filesystem_date(file_path, photo_taken_time):
    formatted_time = datetime.utcfromtimestamp(int(photo_taken_time)).strftime('%m/%d/%Y %H:%M:%S')
    try:
        subprocess.run(["powershell", f"(Get-Item '{file_path}').CreationTime = '{formatted_time}'"], check=True)
        print(f"[Success] Filesystem creation date updated for {file_path}")
    except subprocess.CalledProcessError as e:
        print(f"[Error] Failed to update filesystem creation date for {file_path}: {e}")

# Loop through files in the Takeout folder
for root, _, files in os.walk(takeout_folder):
    for file in files:
        foundImage = False
        if file.endswith(".supplemental-metadata.json"):
            json_path = os.path.join(root, file)
            
            # Get the corresponding image file name
            image_filename = file.replace(".supplemental-metadata.json", "")
            image_path = os.path.join(root, image_filename)
            foundImage = True
	# Fix for pixel filename truncation
        if file.endswith(".supplemental-metada.json"):
            json_path = os.path.join(root, file)
            
            # Get the corresponding image file name
            image_filename = file.replace(".supplemental-metada.json", "")
            image_path = os.path.join(root, image_filename)
            foundImage = True	

	# Fix for UUID filename truncation
        if file.endswith(".suppl.json"):
            json_path = os.path.join(root, file)
            
            # Get the corresponding image file name
            image_filename = file.replace(".suppl.json", "")
            image_path = os.path.join(root, image_filename)
            foundImage = True

	
        if foundImage:
            
            # Check if the corresponding image file exists
            if not os.path.exists(image_path):
                print(f"[Skipped] No image found for JSON: {file}")
                continue
            
            # Check if JSON file is empty
            if os.path.getsize(json_path) == 0:
                print(f"[Skipped] JSON file is empty: {file}")
                continue

            # Load metadata from JSON file
            try:
                with open(json_path, "r") as f:
                    metadata = json.load(f)
            except json.JSONDecodeError:
                print(f"[Error] Failed to decode JSON file: {file}")
                continue
            
            # Extract photoTakenTime
            photo_taken_time = metadata.get("photoTakenTime", {}).get("timestamp")
            if not photo_taken_time:
                print(f"[Skipped] No photoTakenTime found for JSON: {file}")
                continue

            # Extract description and geotags
            description = metadata.get("description", "").strip()
            latitude = metadata.get("geoData", {}).get("latitude", 0.0)
            longitude = metadata.get("geoData", {}).get("longitude", 0.0)

            # Prepare ExifTool command to update EXIF metadata
            formatted_photo_time = convert_timestamp(photo_taken_time)
            exiftool_cmd = [
                "exiftool", 
                "-overwrite_original",  # Overwrite the file directly
                f"-DateTimeOriginal={formatted_photo_time}"
            ]

            # Add description if available
            if description:
                exiftool_cmd.append(f"-ImageDescription={description}")

            # Add geotags if meaningful
            if latitude != 0.0 and longitude != 0.0:
                exiftool_cmd.extend([
                    f"-GPSLatitude={latitude}",
                    f"-GPSLongitude={longitude}",
                    f"-GPSLatitudeRef={'N' if latitude >= 0 else 'S'}",
                    f"-GPSLongitudeRef={'E' if longitude >= 0 else 'W'}"
                ])

            # Append the image file to the ExifTool command
            exiftool_cmd.append(image_path)
            
            # Run ExifTool command
            result = subprocess.run(exiftool_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode == 0:
                print(f"[Success] Metadata updated for {image_filename}")
                
                # Update the filesystem creation date
                update_filesystem_date(image_path, photo_taken_time)
                
                # Delete the JSON file after successful updates
                os.remove(json_path)
                print(f"[Deleted] JSON file: {file}")
            else:
                print(f"[Error] Failed to update metadata for {image_filename}")
                print(result.stderr.decode())

# Final message
print("Processing complete.")
