# GooglePhotos-Tools

Tools to download & fix google photos images. Based around the original code by Albert Ratajczak, and updated by me to work with the new Google APIs OAuth2 flow (there was a small bug).

The "main.py" script inside the "src" folder is a fixed version of the original code by AR. It allows you to download source files from Google Photos directly, at the same quality as they were stored on their servers.
However, Google Photos adds "<FILENAME>.<EXT>.supplemental-metadata.json" files, which contain geolocation information as well as shot date and camera info. The `renamer.py` tool uses _exiftool_ to restore the original EXIF data into the files and cleanup the directory structure. I recommend you run this after using the first script to download an album.

### What you can do?
* List your albums from Google Photos
* Select album(s) to be tracked
* Download/update tracked album(s) to local library on your hard drive
* ALL photos from the album(s) are always downloaded (photos, which has been downloaded earlier, will be overwritten)

### How to run it?
* In project directory, you need to place client_secret.json file from [Google API Console](https://console.developers.google.com/apis/)
* You also need virtual environment for the project (venv directory)
* If you have client_secret.json and virtual environment, run run.bat file, or just call the python script directly

### About client secret
* Create new project in [Google API Console](https://console.developers.google.com/apis/)
* Enable Photos Library API
* Create a new "Desktop" OAuth2 client, and download credentials (OAuth client ID). Save them as client_secret.json in the "src" folder
