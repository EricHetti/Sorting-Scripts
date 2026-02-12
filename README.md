# Sorting-Script
This was mainly written to sort photo and video files

- Rename the files to the metadata filename
- Sorts the files using metadata into the folder structure of camera model -> year -> month -> day
- If there are duplicates of the same file in a sub folder it will move it to the same folder stucture and suffixed the filename with _DUP_1.extension
- Update all date timestamp fields in the metadata with timestamps so that applications like Synology Photos will sort it correctly
- Move all other files to the OUTPUT_DIR
- Delete all junk files (ie .ds_store, desktop.ini )
- Delete all empty folders
