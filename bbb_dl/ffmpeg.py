# Python wrapper around the ffmpeg utility
# Original author: CreateWebinar.com

import os

from youtube_dl import YoutubeDL

from youtube_dl.postprocessor.ffmpeg import FFmpegPostProcessor


class FFMPEG:
    def __init__(self, ydl: YoutubeDL):
        self.pp = FFmpegPostProcessor(ydl)
        self.pp.check_version()

    def extract_audio_from_video(self, video_file: str, out_file: str):
        self.pp.run_ffmpeg(video_file, out_file, ["-ab", "160k", "-ac", "2", "-ar", "44100", "-vn"])

    def rescale_image(self, image, height, width, out_file):
        if height < width:
            self.pp.run_ffmpeg(image, out_file, ["-vf", "160k", "pad=%s:%s:0:oh/2-ih/2" % (width, height), "2", "-y"])
        else:
            self.pp.run_ffmpeg(image, out_file, ["-vf", "160k", "pad=%s:%s:0:ow/2-iw/2" % (width, height), "2", "-y"])

    def mux_slideshow_audio(self, video_file, audio_file, out_file):
        self.pp.run_ffmpeg_multiple_files(
            [video_file, audio_file], out_file, ["-map", "0", "-map", "1", "-codec", 'copy', '-shortest']
        )

    def create_video_from_image(self, image, duration, out_file):
        self.pp.run_ffmpeg(
            image,
            out_file,
            [
                "-loop",
                "1",
                "-r",
                "5",
                "-f",
                "image2",
                "-c:v",
                "libx264",
                "-t",
                str(duration),
                "-pix_fmt",
                "yuv420p",
                "-vf",
                'scale=trunc(iw/2)*2:trunc(ih/2)*2',
            ],
        )

    def concat_videos(self, video_list, out_file):
        self.pp.run_ffmpeg(video_list, out_file, ["-f", "concat", "-safe", "0", "-c", "copy"])

    def mp4_to_ts(self, inp_file, out_file):
        self.pp.run_ffmpeg(inp_file, out_file, ["-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "mpegts"])

    def webm_to_mp4(self, webm_file, mp4_file):
        self.pp.run_ffmpeg(webm_file, mp4_file, ["-qscale", "0"])

    def trim_video_by_seconds(self, video_file, start, end, out_file):
        self.pp.run_ffmpeg(video_file, out_file, ["-ss", str(start), "-c", "copy", "-t", str(end)])

    def _get_trim_marks(self, start, end):
        start_h = start / 3600
        start_m = start / 60 - start_h * 60
        start_s = start % 60

        end_h = end / 3600
        end_m = end / 60 - end_h * 60
        end_s = end % 60

        str1 = '%d:%d:%d' % (start_h, start_m, start_s)
        str2 = '%d:%d:%d' % (end_h, end_m, end_s)
        return str1, str2

    def trim_audio_start(self, slides_timemarks, slides_endmark, full_audio, audio_trimmed):
        times = list(slides_timemarks.keys())
        times.sort()
        self.trim_audio(full_audio, int(round(times[0])), int(slides_endmark), audio_trimmed)

    def trim_audio(self, audio_file, start, end, out_file):
        temp_file = 'temp.mp3'
        str1, str2 = self._get_trim_marks(start, end)

        self.pp.run_ffmpeg(audio_file, temp_file, ["-ss", str1, "-t", str2])

        self.mp3_to_aac(temp_file, out_file)
        os.remove(temp_file)

    def mp3_to_aac(self, mp3_file, aac_file):
        self.pp.run_ffmpeg(mp3_file, aac_file, ["-c:a", "libfdk_aac"])
