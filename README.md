# Big Blue Button (BBB) Downloader

Downloads a BBB lesson as MP4 video, including presentation, audio, webcam and screenshare.

> Nevertheless, I would definitely recommend you to record a BBB meeting with [OBS](https://obsproject.com/de), it's more efficient and you have more control over the outcome.

### Setup
1. Install [Python](https://www.python.org/) >=3.7
2. Install [ffmpeg](https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Installing-ffmpeg)
3. Run: `pip install --user bbb-dl`
4. Run `bbb-dl --help` to see all options

If you ever need to update `bbb-dl` run: `pip install --user -U bbb-dl`

### Usage


Example call: 

`bbb-dl --add-webcam --add-annotations https://your.bbb.org/playback/presentation/2.3/playback.html?meetingId=5d9100very_long_id70001800032c-160100033965 `


```
usage: bbb-dl [-h] [-aw] [-aa] [-ac] [-bk] [-kt] [-v] [-vc] [--chrome-executable CHROME_EXECUTABLE] [-ncc] [--version] [--encoder ENCODER] [--audiocodec AUDIOCODEC] [-f FILENAME] [-od OUTPUTDIR] URL

Big Blue Button Downloader that downloads a BBB lesson as MP4 video

positional arguments:
  URL                   URL of a BBB lesson

options:
  -h, --help            show this help message and exit
  -aw, --add-webcam     add the webcam video as an overlay to the final video
  -aa, --add-annotations
                        add the annotations of the professor to the final video
  -ac, --add-cursor     add the cursor of the professor to the final video [Experimental, very slow, untested]
  -bk, --backup         downloads all the content from the server and then stops. After using this option, you can run bbb-dl again to create the video based on the saved files
  -kt, --keep-tmp-files
                        keep the temporary files after finish. In case of an error bbb-dl will reuse the already generated files
  -v, --verbose         print more verbose debug informations
  -vc, --verbose-chrome
                        print more verbose debug informations of the chrome browser that is used to generate screenshots
  --chrome-executable CHROME_EXECUTABLE
                        Optional path to your installed Chrome executable (Use it if the path is not detected automatically)
  -ncc, --no-check-certificate
                        Suppress HTTPS certificate validation
  --version             Print program version and exit
  --encoder ENCODER     Optional encoder to pass to ffmpeg (default libx264)
  --audiocodec AUDIOCODEC
                        Optional audiocodec to pass to ffmpeg (default copy the codec from the original source)
  -f FILENAME, --filename FILENAME
                        Optional output filename
  -od OUTPUTDIR, --outputdir OUTPUTDIR
                        Optional output directory
```

### How can I speed up the rendering process?

FFmpeg can use different hardware accelerators for encoding videos. You can find more information about this here: https://trac.ffmpeg.org/wiki/HWAccelIntro

To use such hardware for encoding you may need to install drivers as indicated on the website and then set the `--encoder` option to the appropriate encoder. 

For example, if you have an Nvidia graphics card installed in a computer, you can use it with the [NVENC](https://trac.ffmpeg.org/wiki/HWAccelIntro#CUDANVENCNVDEC) encoder. For this you simply set the option `--encoder h264_nvenc`. You can see on the [Nvidia website which graphics cards support this option](https://developer.nvidia.com/video-encode-and-decode-gpu-support-matrix-new). If your graphics card also supports H.265 (HEVC) you can set the option `--encoder hevc_nvenc` instead, which might be even faster (you have to test this yourself).


### License
This project is licensed under the terms of the *GNU General Public License v2.0*. For further information, please look [here](http://choosealicense.com/licenses/gpl-2.0/) or [here<sup>(DE)</sup>](http://www.gnu.org/licenses/old-licenses/gpl-2.0.de.html).

This project is based on the work of [CreateWebinar.com](https://github.com/createwebinar/bbb-download), [Stefan Wallentowitz](https://github.com/wallento/bbb-scrape) and [Olivier Berger](https://github.com/ytdl-org/youtube-dl/pull/25092).
Parts of this code have already been published under MIT license and public domain. These parts are re-released in this project under the GPL-2.0 License.    
