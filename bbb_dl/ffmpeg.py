import json
import os
import subprocess

from dataclasses import dataclass
from subprocess import CalledProcessError
from typing import List
from itertools import cycle

from ffmpeg import FFmpeg
from ffmpeg.utils import Progress

from bbb_dl.utils import PathTools as PT, Log


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int


class FFMPEG:
    def __init__(self, verbose: bool, ffmpeg_location: str, encoder: str, audiocodec: str):
        self.verbose = verbose
        self.ffmpeg_path = 'ffmpeg'
        self.ffprobe_path = 'ffprobe'
        self.spinner = cycle('/|\\-')

        if ffmpeg_location is not None:
            found = False
            for check_name in ['ffmpeg', 'ffmpeg.exe']:
                check_path = PT.get_in_dir(ffmpeg_location, check_name)
                if os.path.isfile(check_path):
                    self.ffmpeg_path = check_path
                    found = True
            if not found:
                Log.error('Error: ffmpeg was not found in your specified --ffmpeg-location path')
                exit(-8)
            found = False
            for check_name in ['ffprobe', 'ffprobe.exe']:
                check_path = PT.get_in_dir(ffmpeg_location, check_name)
                if os.path.isfile(check_path):
                    self.ffprobe_path = check_path
                    found = True
            if not found:
                Log.error('Error: ffprobe was not found in your specified --ffmpeg-location path')
                exit(-9)

        self.encoder = encoder
        self.audiocodec = audiocodec

    def on_error(self, code: int):
        Log.error(f"Error: {code}")
        exit(-10)

    def on_start(self, arguments: List[str]):
        if self.verbose:
            Log.info(f"Running command: {' '.join(arguments)}")

    def on_progress(self, progress: Progress):
        print(
            f"\r\033[K{progress} {next(self.spinner)}",
            end='',
        )

    def on_completed(self):
        print()
        Log.info('Command finished')

    def add_standard_handlers(self, ffmpeg_obj):
        ffmpeg_obj.on("start", self.on_start)
        ffmpeg_obj.on("error", self.on_error)
        ffmpeg_obj.on("progress", self.on_progress)
        ffmpeg_obj.on("completed", self.on_completed)

    def get_video_infos(self, video_path: str) -> VideoInfo:
        try:
            if self.verbose:
                Log.info(f'Checking video information of `{video_path}`')
            result = subprocess.run(
                [
                    self.ffprobe_path,
                    '-v',
                    'error',
                    '-select_streams',
                    "v:0",
                    "-show_entries",
                    "stream=width,height,duration",
                    "-of",
                    "json",
                    video_path,
                ],
                capture_output=True,
                encoding='utf-8',
                text=True,
                check=True,
            )
            streams = json.loads(result.stdout).get('streams', [])
            if len(streams) == 0:
                Log.warning(f"Error: No Stream found in {video_path}")
                return VideoInfo(video_path, None, 0, 0)
            stream = streams[0]
            return VideoInfo(video_path, stream.get('duration', None), stream.get('width', 0), stream.get('height', 0))
        except CalledProcessError as err:
            print(f"Error: {err}")
            exit(-10)

    async def freeze_detect(self, video_path: str) -> bool:
        """
        return true if video is 100% freezed
        """
        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            # .option("nostats")
            .input(video_path)
            .output(
                '-',
                vf='freezedetect=n=-60dB:d=2',
                map='0:v:0',
                f='null',
            )
        )

        freeze_starts = []
        freeze_ends = []

        @ffmpeg.on("stderr")
        def on_stderr(line):
            if line.find('lavfi.freezedetect.freeze_end') >= 0:
                end = float(line.rsplit('lavfi.freezedetect.freeze_end: ', 1)[1])
                freeze_ends.append(end)
            elif line.find('lavfi.freezedetect.freeze_start') >= 0:
                start = float(line.rsplit('lavfi.freezedetect.freeze_start: ', 1)[1])
                freeze_starts.append(start)

        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()
        if len(freeze_ends) == 0 and len(freeze_starts) == 1 and freeze_starts[0] <= 10:
            return True
        return False

    async def create_slideshow(self, concat_file_path: str, output_path: str, width: int, height: int):
        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            .input(
                concat_file_path,
                f='concat',
                # hwaccel="auto",  # In tests it was slower with hwaccel
            )
            .output(
                output_path,
                filter_complex=(
                    f'[0:v]fps=24,scale=w={width}:h={height}:force_original_aspect_ratio=decrease,'
                    + f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2[out]'
                ),
                map='[out]',
                strict='experimental',
                crf='22',
                pix_fmt='yuv420p',
                preset='ultrafast',
            )
        )
        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()

    async def resize_deskshare(self, deskshare_path: str, resized_deskshare_path: str, width: int, height: int):
        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            .input(
                deskshare_path,
                # hwaccel="auto", # Use encoder to activate hwaccel
            )
            .output(
                resized_deskshare_path,
                {
                    'c:v': self.encoder,
                    'c:a': self.audiocodec,
                },
                vf=(
                    f'scale=w={width}:h={height}:force_original_aspect_ratio=decrease,'
                    + f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'
                ),
                preset='ultrafast',
            )
        )

        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()

    async def add_deskshare_to_slideshow(self, concat_file_path: str, output_path: str):
        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            .input(
                concat_file_path,
                f='concat',
                # hwaccel="auto",   # In tests it was slower with hwaccel
            )
            .output(
                output_path,
                {
                    'c:v': self.encoder,
                    'c:a': self.audiocodec,
                },
                strict='experimental',
                preset='ultrafast',
            )
        )
        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()

    def get_webcam_size(self, slideshow_width, slideshow_height):
        webcam_width = slideshow_width // 5
        webcam_height = webcam_width * 3 // 4

        if webcam_height > slideshow_height:
            webcam_height = slideshow_height

        if webcam_width % 2:
            webcam_width -= 1
        if webcam_height % 2:
            webcam_height -= 1

        return webcam_width, webcam_height

    async def add_webcam_to_slideshow(
        self,
        slideshow_path: str,
        webcams_path: str,
        slideshow_width: int,
        slideshow_height: int,
        result_path: str,
    ):
        webcam_width, webcam_height = self.get_webcam_size(slideshow_width, slideshow_height)

        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            .input(webcams_path)
            .input(slideshow_path)
            .output(
                result_path,
                {
                    'c:v': self.encoder,
                    'c:a': self.audiocodec,
                },
                filter_complex=(
                    f'[0:v]scale={webcam_width}:{webcam_height},setpts=PTS-STARTPTS,'
                    + 'format=rgba,colorchannelmixer=aa=0.8'
                    + '[ovrl];[1:v]fps=24,setpts=PTS-STARTPTS[bg];[bg][ovrl]overlay=W-w:H-h:shortest=1'
                ),
                strict='experimental',
                preset='ultrafast',
            )
        )
        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()

    async def add_audio_to_slideshow(self, slideshow_path: str, webcams_path: str, result_path: str):
        ffmpeg = (
            FFmpeg(self.ffmpeg_path)
            .option("hide_banner")
            .input(webcams_path)
            .input(slideshow_path)
            .output(
                result_path,
                {
                    'c:v': self.encoder,
                    'c:a': self.audiocodec,
                },
                map=['0:a', '1:v'],
                strict='experimental',
                preset='ultrafast',
                shortest=None,
            )
        )
        self.add_standard_handlers(ffmpeg)

        await ffmpeg.execute()
