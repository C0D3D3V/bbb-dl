# Big Blue Button (BBB) Downloader

Downloads a BBB lesson as MP4 video, including presentation, audio, webcam and screenshare.

### Setup
1. Install [Python](https://www.python.org/) >=3.7
2. Install [ffmpeg](https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Installing-ffmpeg)
3. Run: `pip install bbb-dl` as administrator

### Usage

```
usage: bbb-dl [-h] [--add-webcam] [--add-annotations] [--add-cursor] [--keep-tmp-files] [--verbose] [--version] URL

Big Blue Button Downloader that downloads a BBB lesson as MP4 video

positional arguments:
  URL                   URL of a BBB lesson

optional arguments:
  -h, --help            show this help message and exit
  --add-webcam, -aw     add the webcam video as an overlay to the final video
  --add-annotations, -aa
                        add the annotations of the professor to the final video
  --add-cursor, -ac     add the cursor of the professor to the final video
  --keep-tmp-files, -kt
                        keep the temporary files after finish
  --verbose, -v         print more verbose debug informations
  --version             Print program version and exit
```


### Notes
This project is based on the work of [CreateWebinar.com](https://github.com/createwebinar/bbb-download), [Stefan Wallentowitz](https://github.com/wallento/bbb-scrape) and [Olivier Berger](https://github.com/ytdl-org/youtube-dl/pull/25092)