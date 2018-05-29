# bbb-download
### The code will be maintained by createwebinar.com developer team

A python script that produces downloadable material for existing and new recordings in a BigBlueButton 1.1 installation.
BigBueButton >= 2.0 is not supported yet. 

## Requirements
1. python2.7
2. ffmpeg compiled with libx264 support

## Installation (need to be root)
```
chmod u+x install.sh 
sudo ./install.sh
```

This copies the download scripts to the BigBlueButton scripts folder, and copies compiled FFMPEG to the /opt/ffmpeg folder. 
It also installs python2.7 and additional libs and give an appropriate rights for MP4 files to make them available for download.

NOTE: You may use the guide [here](https://trac.ffmpeg.org/wiki/CompilationGuide/Ubuntu) to compile ffmpeg in Ubuntu by your own. Be sure to include the following flags. 
```
--enable-version3 --enable-postproc --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libmp3lame --enable-libfdk-aac --enable-gpl --enable-nonfree''
```

## Usage
After running the installation script (install.sh), the python script that produces the downloadable material, will be called for each recording automatically by the BigBlueButton monitoring scripts, after each recording has been transcoded and published.
Link to download MP4 file will look like this: https://yourBBBserverURL/download/presentation/{meetingID}/{meetingID}.mp4
If your BigBlueButton server is connected to Createwebinar.com contol panel, all webinar participants can download the recorded webinars from Schedule menu.

## Outputs
Link to download MP4 file will look like this: https://yourBBBserverURL/download/presentation/{meetingID}/{meetingID}.mp4
If your BigBlueButton server is connected to Createwebinar.com Advanced contol panel, all webinar participants can download the recorded webinars from Schedule menu.
