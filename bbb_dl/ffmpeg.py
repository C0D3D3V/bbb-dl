# Python wrapper around the ffmpeg utility
# Original author: CreateWebinar.com

import os
import itertools
import subprocess
import pathvalidate

from yt_dlp import YoutubeDL

from yt_dlp.utils import (
    encodeArgument,
    encodeFilename,
    shell_quote,
)
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor, FFmpegPostProcessorError


class MyFFmpegPostProcessor(FFmpegPostProcessor):
    def own_run_ffmpeg_multiple_files(self, input_paths, out_path, output_path_opts, input_path_opts=None):
        if input_path_opts is None:
            input_path_opts = []
        out_path = pathvalidate.sanitize_filepath(out_path)

        return self.own_real_run_ffmpeg(
            [(path, input_path_opts) for path in input_paths], [(out_path, output_path_opts)]
        )

    def own_real_run_ffmpeg(self, input_path_opts, output_path_opts):

        self.check_version()

        oldest_mtime = min(os.stat(encodeFilename(path)).st_mtime for path, _ in input_path_opts if path)

        cmd = [encodeFilename(self.executable, True), encodeArgument('-y')]
        # avconv does not have repeat option
        if self.basename == 'ffmpeg':
            cmd += [encodeArgument('-loglevel'), encodeArgument('repeat+info')]

        def make_args(file, args, name, number):
            keys = ['_%s%d' % (name, number), '_%s' % name]
            if name == 'o':
                args += ['-movflags', '+faststart']
                if number == 1:
                    keys.append('')
            args += self._configuration_args(self.basename, keys)
            if name == 'i':
                args.append('-i')
            return [encodeArgument(arg) for arg in args] + [encodeFilename(self._ffmpeg_filename_argument(file), True)]

        for arg_type, path_opts in (('i', input_path_opts), ('o', output_path_opts)):
            cmd += itertools.chain.from_iterable(
                make_args(path, list(opts), arg_type, i + 1) for i, (path, opts) in enumerate(path_opts) if path
            )

        if self._downloader.params.get('verbose', False):
            self._downloader.to_screen(f'[debug] ffmpeg command line: {shell_quote(cmd)}')
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, universal_newlines=True
        )

        last_line = ''
        for line in p.stderr:
            # line = line.decode('utf-8', 'replace')
            if line.find('time=') > 0:
                print('\033[K' + line.replace('\n', '') + '\r', end='')
            last_line = line
        print('')

        p.communicate()
        if p.returncode != 0:
            msg = last_line.strip().split('\n')[-1]
            raise FFmpegPostProcessorError(msg)
        for out_path, _ in output_path_opts:
            if out_path:
                self.try_utime(out_path, oldest_mtime, oldest_mtime)

    def own_run_ffmpeg(self, path, out_path, opts, opts_before=None):
        self.own_run_ffmpeg_multiple_files([path], out_path, opts, opts_before)


class FFMPEG:
    def __init__(self, ydl: YoutubeDL, encoder: str, audiocodec: str):
        self.pp = MyFFmpegPostProcessor(ydl)
        self.pp.check_version()
        self._encoder = encoder
        self._audiocodec = audiocodec

    def rescale_image(self, image, out_file, width, height):
        self.pp.own_run_ffmpeg(image, out_file, ["-vf", f"pad={width}:{height}:ow/2-iw/2:oh/2-ih/2"])

    def mux_slideshow_with_webcam(self, video_file, webcam_file, webcam_w, webcam_h, out_file):
        if os.path.isfile(out_file):
            return
        self.pp.own_run_ffmpeg_multiple_files(
            [webcam_file, video_file],
            out_file,
            [
                "-filter_complex",
                f"[0:v]scale={webcam_w}:{webcam_h}, setpts=PTS-STARTPTS, format=rgba,colorchannelmixer=aa=0.8 "
                + " [ovrl];[1:v] fps=24,setpts=PTS-STARTPTS [bg]; [bg][ovrl] overlay=W-w:H-h:shortest=1",
                '-c:a',
                self._audiocodec,
                '-strict',
                'experimental',
                "-preset",
                "ultrafast",
            ],
        )

    def mux_slideshow(self, video_file, webcam_file, out_file):
        if os.path.isfile(out_file):
            return
        self.pp.own_run_ffmpeg_multiple_files(
            [webcam_file, video_file],
            out_file,
            [
                '-map',
                '0:a',
                '-c:a',
                self._audiocodec,
                '-strict',
                'experimental',
                '-map',
                '1:v',
                '-c:v',
                'copy',
                '-shortest',
            ],
        )

    def create_video_from_image(self, image, duration, out_file):
        if os.path.isfile(out_file):
            return
        self.pp.own_run_ffmpeg(
            image,
            out_file,
            [
                "-c:v",
                "libx264",
                "-t",
                str(duration),
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "ultrafast",
            ],
            [
                "-loop",
                "1",
                "-f",
                "image2",
                "-framerate",
                "24",
                "-r",
                "24",
            ],
        )

    def concat_videos(self, video_list, out_file):
        if os.path.isfile(out_file):
            return
        self.pp.own_run_ffmpeg(video_list, out_file, ["-c", "copy"], ["-f", "concat", "-safe", "0"])

    def trim_video_by_seconds(self, video_file, start, duration, width, height, out_file):
        if os.path.isfile(out_file):
            return
        self.pp.own_run_ffmpeg(
            video_file,
            out_file,
            [
                "-t",
                str(duration),
                "-vf",
                f"scale={width}:{height}",
                "-c:v",
                self._encoder,
                "-pix_fmt",
                "yuv420p",
            ],
            [
                "-ss",
                str(start),
            ],
        )
