# bbb-download
### The code will be maintained by createwebinar.com developer team

A python script that produces downloadable material for existing and new recordings in a BigBlueButton installation.
Final MP4 video will include only presentation, audio and screenshare (no chat window, no whiteboard).
- BigBlueButton 2.0 is supported (10.08.2018)
- Screenshare supported (18.09.2018)

## Requirements
1. python2.7
2. ffmpeg compiled with libx264 support (included)
3. Installed and configured Big Blue Button server (1.1 or 2.0)

## Installation (need to be root)
```
git clone https://github.com/createwebinar/bbb-download.git
cd bbb-download
chmod u+x install.sh 
sudo ./install.sh
# To convert all of your current recordings to MP4 format use command:
sudo bbb-record --rebuildall
```


This copies the download scripts to the BigBlueButton scripts folder, and copies compiled FFMPEG to the /opt/ffmpeg folder. 
It also installs python2.7 and additional libs and give an appropriate rights for MP4 files to make them available for download.

NOTE: You may use the guide [here](https://trac.ffmpeg.org/wiki/CompilationGuide/Ubuntu) to compile ffmpeg in Ubuntu by your own. Be sure to include the following flags. 
```
--enable-version3 --enable-postproc --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libmp3lame --enable-libfdk-aac --enable-gpl --enable-nonfree''
```

## Usage
After running the installation script (install.sh), the python script that produces the downloadable material, will be called for each recording automatically by the BigBlueButton monitoring scripts, after each recording has been transcoded and published.

## Outputs
Final MP4 video will include only presentation, audio and screenshare (no chat window, no whiteboard).

Link to download MP4 file will look like this: https://yourBBBserverURL/download/presentation/{meetingID}/{meetingID}.mp4
If your BigBlueButton server is connected to https://createwebinar.com contol panel, all webinar participants will be able to download the recorded webinars from the website in one click.
