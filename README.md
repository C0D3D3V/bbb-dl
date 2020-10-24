# Big Blue Button (BBB) Downloader

Downloads a BBB lesson as MP4 video, including presentation, audio, webcam and screenshare.

### Setup
1. Install [Python](https://www.python.org/) >=3.7
2. Install [ffmpeg](https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Installing-ffmpeg)
3. Run: `pip install bbb-dl` as administrator

### Usage

To download a lesson with webcam use: 

`bbb-dl --add-webcam https://bbb-uni.com/playback/path/to/your/video`

Adding the webcam to the video takes longer, so you can leave it out:

`bbb-dl https://bbb-uni.com/playback/path/to/your/video`


### Notes
This project is based on the work of [CreateWebinar.com](https://github.com/createwebinar/bbb-download), [Stefan Wallentowitz](https://github.com/wallento/bbb-scrape) and [Olivier Berger](https://github.com/ytdl-org/youtube-dl/pull/25092)