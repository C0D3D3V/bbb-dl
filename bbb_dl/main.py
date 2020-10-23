# Python script that downloads a lessen video from a published bbb recording.

# original authors: CreateWebinar.com <support@createwebinar.com>
#                   and Olivier Berger <olivier.berger@telecom-sudparis.eu>

import argparse
import os
import re
import shutil
import socket

import youtube_dl

from youtube_dl import YoutubeDL

from youtube_dl.compat import (
    compat_http_client,
    compat_urllib_error,
)
from youtube_dl.utils import (
    xpath_text,
    xpath_with_ns,
    encodeFilename,
    error_to_compat_str,
    DownloadError,
    determine_ext,
)

from youtube_dl.extractor.common import InfoExtractor

from bbb_dl.ffmpeg import FFMPEG

from bbb_dl.version import __version__

_s = lambda p: xpath_with_ns(p, {'svg': 'http://www.w3.org/2000/svg'})
_x = lambda p: xpath_with_ns(p, {'xlink': 'http://www.w3.org/1999/xlink'})


class BBBDL(InfoExtractor):
    _VALID_URL = (
        r'(?P<website>https?://[^/]+)/playback/presentation/2.0/playback.html\?.*?meetingId=(?P<id>[0-9a-f\-]+)'
    )

    def __init__(self):
        if '_VALID_URL_RE' not in self.__dict__:
            BBBDL._VALID_URL_RE = re.compile(self._VALID_URL)

        ydl_options = {"verbose": True}
        self.ydl = youtube_dl.YoutubeDL(ydl_options)
        self.set_downloader(self.ydl)
        self.ffmpeg = FFMPEG(self.ydl)

    def run(self, dl_url: str, without_webcam: bool):
        m_obj = self._VALID_URL_RE.match(dl_url)

        video_id = m_obj.group('id')
        video_website = m_obj.group('website')

        self.to_screen("Downloading meta informations")
        # Make sure the lesson exists
        self._download_webpage(dl_url, video_id)
        self._create_tmp_dir(video_id)

        # Extract basic metadata
        metadata_url = video_website + '/presentation/' + video_id + '/metadata.xml'
        metadata = self._download_xml(metadata_url, video_id)

        shapes_url = video_website + '/presentation/' + video_id + '/shapes.svg'
        shapes = self._download_xml(shapes_url, video_id)

        # Parse metadata.xml
        meta = metadata.find('./meta')
        start_time = xpath_text(metadata, 'start_time')
        title = xpath_text(meta, 'meetingName')
        bbb_version = xpath_text(meta, 'bbb-origin-version').split(' ')[0]
        self.to_screen("BBB version: " + bbb_version)

        # Downloading Slides
        images = shapes.findall(_s("./svg:image[@class='slide']"))
        fist_img = True
        slides_endmark = 0
        slides_timemarks = {}
        slides_infos = {}
        counter = 0
        for image in images:
            img_path = image.get(_x('xlink:href'))

            if fist_img and '2.0.0' > bbb_version:
                continue
            fist_img = False

            in_times = image.get('in').split(' ')
            out_times = image.get('out').split(' ')

            if img_path not in slides_infos:
                slide_filename = 'slide-' + str(counter) + '.' + determine_ext(img_path)
                slides_infos[img_path] = {
                    'h': int(image.get('height')),
                    'w': int(image.get('width')),
                    'url': video_website + '/presentation/' + video_id + '/' + img_path,
                    'filename': slide_filename,
                    'filepath': video_id + '/' + slide_filename,
                }
                counter += 1

            temp = float(out_times[len(out_times) - 1])
            if temp > slides_endmark:
                slides_endmark = temp

            for in_time in in_times:
                slides_timemarks[float(in_time)] = img_path

        self.to_screen("Downloading slides")
        self._write_slides(slides_infos, self.ydl)

        # Downlaoding Webcam / Deskshare
        video_base_url = video_website + '/presentation/' + video_id

        webcams_path = video_id + '/webcams.webm'
        try:
            self.to_screen("Downloading webcams.webm")
            webcams_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/video/webcams.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl'] = webcams_path
            self.ydl.process_ie_result(webcams_dl)
        except DownloadError:
            pass

        deskshare_path = video_id + '/deskshare.webm'
        try:
            self.to_screen("Downloading deskshare.webm")
            deskshare_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/deskshare/deskshare.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl'] = deskshare_path
            self.ydl.process_ie_result(deskshare_dl)
        except DownloadError:
            pass

        # Post processing
        slideshow_w, slideshow_h = self._rescale_slides(slides_infos)

        slideshow_path = self._create_slideshow(
            slides_timemarks, slides_infos, slides_endmark, deskshare_path, video_id
        )

        result_path = title + '.mp4'
        self.to_screen("Mux Slideshow")
        webcam_w, webcam_h = self._get_webcam_size(slideshow_w, slideshow_h)
        if without_webcam:
            self.ffmpeg.mux_slideshow(slideshow_path, webcams_path, result_path)

        else:
            self.ffmpeg.mux_slideshow_with_webcam(slideshow_path, webcams_path, webcam_w, webcam_h, result_path)

        self.to_screen("Cleanup")
        self._remove_tmp_dir(video_id)

    def _create_tmp_dir(self, video_id):
        try:
            if not os.path.exists(video_id):
                os.makedirs(video_id)
        except (OSError, IOError) as err:
            self.ydl.report_error('unable to create directory ' + error_to_compat_str(err))

    def _remove_tmp_dir(self, video_id):
        try:

            if os.path.exists(video_id):
                shutil.rmtree(video_id)
        except (OSError, IOError) as err:
            self.ydl.report_error('unable to remove directory ' + error_to_compat_str(err))

    def _write_slides(self, slides_infos: {}, ydl: YoutubeDL):

        for slide_id in slides_infos:
            slide = slides_infos[slide_id]
            slide_url = slide.get('url')
            slide_filename = slide.get('filename')
            download_path = slide.get('filepath')

            if os.path.exists(encodeFilename(download_path)):
                self.to_screen('Slide %s is already present' % (slide_filename))
            else:
                self.to_screen('Downloading slide %s...' % (slide_filename))
                try:
                    uf = ydl.urlopen(slide_url)
                    with open(encodeFilename(download_path), 'wb') as thumbf:
                        shutil.copyfileobj(uf, thumbf)
                    self.to_screen('Writing slide %s to: %s' % (slide_filename, download_path))
                except (compat_urllib_error.URLError, compat_http_client.HTTPException, socket.error) as err:
                    self.report_warning('Unable to download slide "%s": %s' % (slide_url, error_to_compat_str(err)))

    def _get_webcam_size(self, slideshow_w, slideshow_h):

        webcam_w = slideshow_w // 5
        webcam_h = webcam_w * 3 // 4

        if webcam_h > slideshow_h:
            webcam_h = slideshow_h

        if webcam_w % 2:
            webcam_w -= 1

        if webcam_h % 2:
            webcam_h -= 1

        return webcam_w, webcam_h

    def _rescale_slides(self, slides_infos: {}):
        widths = []
        heights = []

        for slide_id in slides_infos:
            slide = slides_infos[slide_id]
            widths.append(slide.get('w'))
            heights.append(slide.get('h'))

        if len(widths) == 0 or len(heights) == 0:
            return

        new_width = max(widths)
        new_height = max(heights)

        if new_width % 2:
            new_width += 1
        if new_height % 2:
            new_height += 1

        for slide_id in slides_infos:
            slide_info = slides_infos[slide_id]
            slide_w = slide_info.get('w')
            slide_h = slide_info.get('h')
            slide_name = slide_info.get('filename')
            slide_path = slide_info.get('filepath')

            if new_width == slide_w and new_height == slide_h:
                continue

            self.to_screen('Rescale %s' % (slide_name,))
            self.ffmpeg.rescale_image(slide_path, new_width, new_height)
        return new_width, new_height

    def _create_slideshow(
        self, slides_timemarks: {}, slides_infos: {}, slides_endmark: int, deskshare_path: str, video_id: str
    ):
        slideshow_path = video_id + '/slideshow.mp4'

        video_list = video_id + '/video_list.txt'
        vl_file = open(video_list, 'w')

        times = list(slides_timemarks.keys())
        times.sort()

        deskshare_mp4_path = video_id + '/deskshare.mp4'
        if os.path.exists(deskshare_path):
            self.to_screen("Convert webm to mp4")
            self.ffmpeg.webm_to_mp4(deskshare_path, deskshare_mp4_path)

        self.to_screen("Create slideshow")
        for i, time_mark in enumerate(times):

            tmp_name = '%d.mp4' % i
            tmp_ts_name = '%d.ts' % i
            slide = slides_infos.get(slides_timemarks[time_mark])
            image = slide.get('filepath')

            if i == len(times) - 1:
                duration = slides_endmark - time_mark
            else:
                duration = times[i + 1] - time_mark

            out_file = video_id + '/' + tmp_name
            out_ts_file = video_id + '/' + tmp_ts_name

            if "deskshare.png" in image:
                self.to_screen("Trimming deskshare at time stamp %ss (Duration: %.2fs)" % (time_mark, duration))
                self.ffmpeg.trim_video_by_seconds(deskshare_mp4_path, time_mark, duration, out_file)
                self.ffmpeg.mp4_to_ts(out_file, out_ts_file)
            else:
                self.to_screen("Trimming slide at time stamp %ss (Duration: %.2fs)" % (time_mark, duration))
                self.ffmpeg.create_video_from_image(image, duration, out_ts_file)

            vl_file.write("file " + tmp_ts_name + "\n")
        vl_file.close()

        self.to_screen("Concat Slideshow")
        self.ffmpeg.concat_videos(video_list, slideshow_path)
        return slideshow_path


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser(description=('BBB Downloader that downloads a BBB lesson as an MP4 video'))

    parser.add_argument('URL', type=str, help='The URL of a lesson to be downloaded.')

    parser.add_argument(
        '--add_webcam',
        '-aw',
        action='store_false',
        help='Use this option if you want to see the webcam in the final video.',
    )

    parser.add_argument(
        '--version', action='version', version='bbb-dl ' + __version__, help='Print program version and exit'
    )

    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    parser = get_parser()
    args = parser.parse_args(args)

    BBBDL().run(args.URL, args.add_webcam)
