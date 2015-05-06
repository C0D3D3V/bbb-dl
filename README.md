# bbb-download
A python script that produces downloadable material for existing and new recordings in a BigBlueButton 0.9.0 installation.

## Requirements
1. python2.7
2. ffmpeg compiled with libx264 support

## Installation
```
chmod u+x install.sh 
sudo ./install.sh
```

This copies the download scripts to the BigBlueButton scripts folder. 
It also installs python2.7 and builds a static ffmpeg with all the necessary compilation flags enabled.

## Usage
After running the installation script (install.sh), the python script that produces the downloadable material, will be called for each recording automatically by the BigBlueButton monitoring scripts, after each recording has been transcoded and published.

## Outputs
