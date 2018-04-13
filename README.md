# bbb-download
### The code is no longer maintained

A python script that produces downloadable material for existing and new recordings in a BigBlueButton 0.9.0 installation.
BigBueButton > 2.0 is not supported

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

NOTE: The building of the ffmpeg in install.sh appears to be now broken. You may use the guide [here](https://trac.ffmpeg.org/wiki/CompilationGuide/Ubuntu) to compile ffmpeg in Ubuntu. Be sure to include the following flags. 
```
--enable-version3 --enable-postproc --enable-libvorbis --enable-libvpx --enable-libx264 --enable-libmp3lame --enable-libfdk-aac --enable-gpl --enable-nonfree''
```

## Usage
After running the installation script (install.sh), the python script that produces the downloadable material, will be called for each recording automatically by the BigBlueButton monitoring scripts, after each recording has been transcoded and published.

## Outputs
The script serves a video with all the slides presented during the web conference, multiplexed with the sound from the speaker's and the participants' microphones. It also serves a second video with the participants' video cameras, had they been used during the conference recording. The 2 videos come bundled in a zip file, that is created in the recording folder and is of the format "recording_id.zip". The script only produces the zip file. Serving it to the end user is not provided.
