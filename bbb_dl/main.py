# Python script that downloads a lessen video from a published bbb recording.

# original authors: CreateWebinar.com <support@createwebinar.com>
#                   and Olivier Berger <olivier.berger@telecom-sudparis.eu>

import argparse
import os
import posixpath
import re
import shutil
import socket
import zipfile
import urllib.parse as urlparse

from xml.dom import minidom

import youtube_dl

from youtube_dl import YoutubeDL

from youtube_dl.compat import (
    compat_http_client,
    compat_urllib_error,
)
from youtube_dl.utils import xpath_text, xpath_with_ns, encodeFilename, error_to_compat_str, DownloadError

from youtube_dl.extractor.common import InfoExtractor

import bbb_dl.ffmpeg as ffmpeg

from bbb_dl.version import __version__

meetingId = 'something-somotherthing'

PATH = '/var/bigbluebutton/published/presentation/'
LOGS = '/var/log/bigbluebutton/download/'
source_dir = PATH + meetingId + "/"
temp_dir = source_dir + 'temp/'
target_dir = source_dir + 'download/'
audio_path = 'audio/'
events_file = 'shapes.svg'
LOGFILE = LOGS + meetingId + '.log'
source_events = '/var/bigbluebutton/recording/raw/' + meetingId + '/events.xml'
# Deskshare
SOURCE_DESKSHARE = source_dir + 'deskshare/deskshare.webm'
TMP_DESKSHARE_FILE = temp_dir + 'deskshare.mp4'

_s = lambda p: xpath_with_ns(p, {'svg': 'http://www.w3.org/2000/svg'})
_x = lambda p: xpath_with_ns(p, {'xlink': 'http://www.w3.org/1999/xlink'})


class BBBDL(InfoExtractor):
    _VALID_URL = (
        r'(?P<website>https?://[^/]+)/playback/presentation/2.0/playback.html\?.*?meetingId=(?P<id>[0-9a-f\-]+)'
    )

    def __init__(self):
        if '_VALID_URL_RE' not in self.__dict__:
            BBBDL._VALID_URL_RE = re.compile(self._VALID_URL)

        self.ydl = youtube_dl.YoutubeDL()
        self.set_downloader(self.ydl)

    def run(self, dl_url: str):
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
        slides = []
        fist_img = True
        slides_endmark = 0
        slides_timemarks = {}
        slides_infos = {}

        for image in images:
            img_path = image.get(_x('xlink:href'))
            slides.append(video_website + '/presentation/' + video_id + '/' + img_path)

            if fist_img and '2.0.0' > bbb_version:
                continue
            fist_img = False

            in_times = image.get('in').split(' ')
            out_times = image.get('out').split(' ')

            slide_filename = video_id + '/' + self.determine_filename(img_path)
            slides_infos[slide_filename] = {
                'h': int(image.get('height')),
                'w': int(image.get('width')),
            }

            temp = float(out_times[len(out_times) - 1])
            if temp > slides_endmark:
                slides_endmark = temp

            for in_time in in_times:
                slides_timemarks[float(in_time)] = slide_filename

        self.to_screen("Downloading slides")
        self._write_slides(slides, video_id, self.ydl)
        self._rescale_slides(slides_infos)

        # Downlaoding Webcam / Deskshare
        video_base_url = video_website + '/presentation/' + video_id

        webcams_success = False
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
            webcams_success = True
        except DownloadError:
            pass

        deskshare_success = False
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
            deskshare_success = True
        except DownloadError:
            pass

        # Post processing
        audio_path = video_id + '/audio.ogg'
        # ffmpeg.extract_audio_from_video(webcams_path, audio_path)

    def _create_tmp_dir(self, video_id):
        try:
            if not os.path.exists(video_id):
                os.makedirs(video_id)
        except (OSError, IOError) as err:
            self.ydl.report_error('unable to create directory ' + error_to_compat_str(err))

    @staticmethod
    def determine_filename(url: str):
        url_parsed = urlparse.urlparse(url)
        return posixpath.basename(url_parsed.path)

    def _write_slides(self, slides: [], path: str, ydl: YoutubeDL):

        for slide_url in slides:
            slide_filename = self.determine_filename(slide_url)

            download_path = os.path.join(path, slide_filename)

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

    def _rescale_slides(self, slides_info: {}):
        heights = []
        widths = []

        for slide_path in slides_info:
            slide_info = slides_info[slide_path]
            heights.append(slide_info.get('h'))
            widths.append(slide_info.get('w'))

        if len(heights) == 0 or len(widths) == 0:
            return

        new_height = max(heights)
        new_width = max(widths)

        if new_height % 2:
            new_height += 1
        if new_width % 2:
            new_width += 1

        for slide_path in slides_info:
            slide_info = slides_info[slide_path]
            slide_w = slide_info.get('w')
            slide_h = slide_info.get('h')

            if new_height == slide_h and new_width == slide_w:
                continue

            print('Rescale %s' % (slide_path,))
            # ffmpeg.rescale_image(slide_path, new_height, new_width, slide_path)


def create_slideshow(dictionary, length, result, bbb_version):
    video_list = 'video_list.txt'
    f = open(video_list, 'w')

    times = dictionary.keys()
    times.sort()

    ffmpeg.webm_to_mp4(SOURCE_DESKSHARE, TMP_DESKSHARE_FILE)

    print("-=create_slideshow=-")
    for i, t in enumerate(times):
        # print >> sys.stderr, (i, t)

        # if i < 1 and '2.0.0' > bbbversion:
        #   continue

        tmp_name = '%d.mp4' % i
        tmp_ts_name = '%d.ts' % i
        image = dictionary[t]

        if i == len(times) - 1:
            duration = length - t
        else:
            duration = times[i + 1] - t

        out_file = temp_dir + tmp_name
        out_ts_file = temp_dir + tmp_ts_name

        if "deskshare.png" in image:
            print(0, i, t, duration)
            ffmpeg.trim_video_by_seconds(TMP_DESKSHARE_FILE, t, duration, out_file)
            ffmpeg.mp4_to_ts(out_file, out_ts_file)
        else:
            print(1, i, t, duration)
            ffmpeg.create_video_from_image(image, duration, out_ts_file)

        f.write('file ' + out_ts_file + '\n')
    f.close()

    ffmpeg.concat_videos(video_list, result)
    os.remove(video_list)


def get_presentation_dims(presentation_name):
    doc = minidom.parse(events_file)
    images = doc.getElementsByTagName('image')

    for el in images:
        name = el.getAttribute('xlink:href')
        pattern = presentation_name
        if re.search(pattern, name):
            height = int(el.getAttribute('height'))
            width = int(el.getAttribute('width'))
            return height, width


def prepare(bbb_version):
    check_presentation_dims(dictionary, dims)


def cleanup():
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)


def serve_webcams():
    if os.path.exists('video/webcams.webm'):
        shutil.copy2('video/webcams.webm', './download/')


def copy_mp4(result, dest):
    if os.path.exists(result):
        shutil.copy2(result, dest)


def zipdir(path):
    filename = meetingId + '.zip'
    zipf = zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(path):
        for f in files:
            zipf.write(os.path.join(root, f))
    zipf.close()


def run_download():

    # dictionary, length, dims = prepare(bbb_version)

    audio = audio_path + 'audio.ogg'
    audio_trimmed = temp_dir + 'audio_trimmed.m4a'
    result = target_dir + 'meeting.mp4'
    slideshow = temp_dir + 'slideshow.mp4'

    try:
        create_slideshow(dictionary, length, slideshow, bbb_version)
        ffmpeg.trim_audio_start(dictionary, length, audio, audio_trimmed)
        ffmpeg.mux_slideshow_audio(slideshow, audio_trimmed, result)
        serve_webcams()
        # zipdir('./download/')
        copy_mp4(result, source_dir + meetingId + '.mp4')
    finally:
        print("Cleaning up temp files...")
        cleanup()
        print("Done")


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser(description=('BBB Downloader that downloads a BBB lesson as an MP4 video'))

    parser.add_argument('URL', type=str, help='The URL of a lesson to be downloaded.')

    parser.add_argument(
        '--version', action='version', version='bbb-dl ' + __version__, help='Print program version and exit'
    )

    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    parser = get_parser()
    args = parser.parse_args(args)

    BBBDL().run(args.URL)
