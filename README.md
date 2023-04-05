# Big Blue Button (BBB) Downloader

Downloads a BBB lesson as MP4 video.
The assembled video includes:

- shared audio and webcams video
- presented slides with
  - whiteboard actions (text and drawings)
  - cursor movements
  - zooming
- screen sharing

If something does not work, feel free to [contact me](https://github.com/C0D3D3V/bbb-dl/issues). 

### Setup
1. Install [Python](https://www.python.org/) >=3.7
2. Install [ffmpeg](https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Installing-ffmpeg)
3. Run: `pip install --user bbb-dl`
4. Run `playwright install chromium`

5. Run `bbb-dl --help` to see all options

If you ever need to update `bbb-dl` run: `pip install -U bbb-dl`

### Usage

**Temporary files are default stored in the application data folder** 

- The `--backup` option uses the same location
- You can change this location with the `--working-dir` option
- On Windows, the folder is located in `%localappdata%\bbb-dl`
- On Linux / MacOS, the folder is located in `~/.local/share/bbb-dl/`
- If you used the `--keep-tmp-files` option and you run the program again with other `--skip-annotations` or `--skip-cursor` options, then you may want to remove the corresponding `frames` folder inside the temporary directory. Because frames are not overwritten. 
- If ffmpeg has an error and a file has not been finished, it should be deleted from the temporary directory.

Example call:

`bbb-dl --skip-cursor https://your.bbb.org/playback/presentation/2.3/playback.html?meetingId=5d9100very_long_id70001800032c-160100033965`


```
usage: bbb-dl [-h] [-ao] [-sw] [-swfd] [-sa] [-sc] [-sz] [-bk] [-kt] [-v] [--ffmpeg-location FFMPEG_LOCATION] [-ncc] [--version] [--encoder ENCODER] [--audiocodec AUDIOCODEC] [--preset PRESET] [--crf CRF]
              [-f FILENAME] [-od OUTPUT_DIR] [-wd WORKING_DIR] [-mpc MAX_PARALLEL_CHROMES] [-fw FORCE_WIDTH] [-fh FORCE_HEIGHT]
              URL

Big Blue Button Downloader that downloads a BBB lesson as MP4 video

positional arguments:
  URL                   URL of a BBB lesson

options:
  -h, --help            show this help message and exit
  -ao, --audio-only     Extract only the audio from the presentation, do not generate video.
  -sw, --skip-webcam    Skip adding the webcam video as an overlay to the final video. This will reduce the time to generate the final video
  -swfd, --skip-webcam-freeze-detection
                        Skip detecting if the webcam video is completely empty. It is assumed the webcam recording is not empty. This will reduce the time to generate the final video
  -sa, --skip-annotations
                        Skip capturing the annotations of the professor. This will reduce the time to generate the final video
  -sc, --skip-cursor    Skip capturing the cursor of the professor. This will reduce the time to generate the final video
  -sz, --skip-zoom      Skip zooming into the presentation. All presentation slides are rendered in full size, which may result in sharper output video. However, consequently also to smaller font.
  -bk, --backup         Downloads all the content from the server and then stops. After using this option, you can run bbb-dl again to create the video based on the saved files
  -kt, --keep-tmp-files
                        Keep the temporary files after finish. In case of an error bbb-dl will reuse the already generated files
  -v, --verbose         Print more verbose debug information
  --ffmpeg-location FFMPEG_LOCATION
                        Optional path to the directory in that your installed ffmpeg executable is located (Use it if ffmpeg is not located in your system PATH)
  -ncc, --no-check-certificate
                        Suppress HTTPS certificate validation
  --version             Print program version and exit
  --encoder ENCODER     Optional encoder to pass to ffmpeg (default libx264)
  --audiocodec AUDIOCODEC
                        Optional audiocodec to pass to ffmpeg (default copy the codec from the original source)
  --preset PRESET       Optional preset to pass to ffmpeg (default fast, a preset that can be used with all encoders)
  --crf CRF             Optional crf to pass to ffmpeg (default 23, lower crf (e.g 22) usually means larger file size and better video quality)
  -f FILENAME, --filename FILENAME
                        Optional output filename
  -od OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Optional output directory for final video
  -wd WORKING_DIR, --working-dir WORKING_DIR
                        Optional output directory for all temporary directories/files
  -mpc MAX_PARALLEL_CHROMES, --max-parallel-chromes MAX_PARALLEL_CHROMES
                        Maximum number of chrome browser instances used to generate frames
  -fw FORCE_WIDTH, --force-width FORCE_WIDTH
                        Force width on final output. (e.g. 1280) This can reduce the time to generate the final video
  -fh FORCE_HEIGHT, --force-height FORCE_HEIGHT
                        Force height on final output. (e.g. 720) This can reduce the time to generate the final video
```
 
### Batch processing

 If you want to do batch processing you can use `bbb-dl-batch`. All passed arguments will be passed to the respective `bbb-dl`. `bbb-dl-batch` itself only needs the path to a text file in which URLs to bbb sessions are specified line by line. See `bbb-dl-batch --help` for more information.

 Successfully downloaded URL sessions are added to `successful.txt` in the output folder. Session URLs that could not be successfully downloaded are added to `failed.txt` in the output folder. 

### The video quality is too low, how can I improve the output quality?

First of all, you should check if the BBB session you downloaded really looks better in the browser than the video you created. When comparing, make sure that the presentation in the browser has the same resolution as the video. 

Among other things, `ffmpeg` offers two options with which you can influence the output quality. You can experiment with them and see if the output improves.

- `--preset` is the first of these options, it can take values from -1 to 13 or in words ultrafast, superfast, veryfast, faster, fast (default), medium, slow and veryslow. A slower encoder often delivers better quality, so try `--preset medium` to see if the quality improves.
- `--crf` is the second of these options, it can take values from -1 to 63. A lower crf (e.g 22) usually means larger file size and better video quality, so try `--crf 22` to see if the quality improves.

`bbb-dl` tries to estimate a suitable output resolution for the final video, this choice may or may not be good. You can force your own output resolution with the `--force-width` and `--force-height` options.

- A high resolution would be e.g. FullHD with 1920x1080. Be warned if the slides themselves are not that large you may get blurry slides.
- A lower resolution for faster rendering would be e.g. HD with 1280x720. It may be that the output looks sharper or less sharp, test it yourself.

### How can I speed up the rendering process?

FFmpeg can use different hardware accelerators for encoding videos. You can find more information about this here: https://trac.ffmpeg.org/wiki/HWAccelIntro

To use such hardware for encoding you may need to install drivers as indicated on the website and then set the `--encoder` option to the appropriate encoder. 

For example, if you have an **Nvidia** graphics card installed on a computer, you can use it with the [NVENC](https://trac.ffmpeg.org/wiki/HWAccelIntro#CUDANVENCNVDEC) encoder. For this, you simply set the option `--encoder h264_nvenc`. You can see on the [Nvidia website which graphics cards support this option](https://developer.nvidia.com/video-encode-and-decode-gpu-support-matrix-new). If your graphics card also supports H.265 (HEVC) you can set the option `--encoder hevc_nvenc` instead, which might be even faster (you have to test this yourself).

- For Intel CPUs, you can try the encoder `h264_qsv` (Use the option `--encoder h264_qsv`). Sometimes this encoder is faster than your graphics card encoder.

- For AMD CPUs / GPUs, you can try the encoder `h264_amf` (Use the option `--encoder h264_amf`).

> You have to test yourself if it is faster to use your hardware encoder or not. In some cases, hardware encoders are slower than using the CPU directly. 


### Other downloader

[bbb-video-download](https://github.com/tilmanmoser/bbb-video-download)
- It uses a clever approach written in Node.js that can be easily integrated into a bbb server
- You can use the `--backup` option to feed `bbb-video-download`.
- A multi-threaded port in go-lang can be found here: [bbb-video-converter](https://github.com/cli-ish/bbb-video-converter)

[bbb-download](https://github.com/fossasia/bbb-download)
- Takes advantage of the fact that you can use the bbb-player to play the session data offline.
- Instead of creating a video file, this downloader downloads only the necessary files from the server, so you can use the bbb-player to play the session offline. The player is provided to you via shortcut.

If someone wants to link another downloader here, which offers e.g. functions that bbb-dl does not offer, feel free to open an issue. 

### License
This project is licensed under the terms of the *MIT License*. For further information, please look [here](LICENSE).
