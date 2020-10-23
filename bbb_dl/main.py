# Python script that downloads a lessen video from a published bbb recording.

# original authors: CreateWebinar.com <support@createwebinar.com>
#                   and Olivier Berger <olivier.berger@telecom-sudparis.eu>

import argparse
import os
import posixpath
import re
import shutil
import socket
import time
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

        # We don't parse anything, but make sure it exists
        self.to_screen("Downloading meta informations")
        self._download_webpage(dl_url, video_id)

        # Extract basic metadata (more available in metadata.xml)
        metadata_url = video_website + '/presentation/' + video_id + '/metadata.xml'
        metadata = self._download_xml(metadata_url, video_id)

        # --------------------  Title / Starttime  --------------------
        meta = metadata.find('./meta')
        start_time = xpath_text(metadata, 'start_time')
        title = xpath_text(meta, 'meetingName')

        # --------------------  Slides  --------------------
        shapes_url = video_website + '/presentation/' + video_id + '/shapes.svg'
        shapes = self._download_xml(shapes_url, video_id)
        images = shapes.findall(_s("./svg:image[@class='slide']"))
        slides = []
        for image in images:
            slides.append(video_website + '/presentation/' + video_id + '/' + image.get(_x('xlink:href')))

        try:
            if not os.path.exists(video_id):
                os.makedirs(video_id)
        except (OSError, IOError) as err:
            self.ydl.report_error('unable to create directory ' + error_to_compat_str(err))

        self.to_screen("Downloading slides")
        self._write_slides(slides, video_id, self.ydl)

        # --------------------  Webcam / Deskshare  --------------------

        video_base_url = video_website + '/presentation/' + video_id

        webcams_success = False
        try:
            self.to_screen("Downloading webcams.webm")
            webcams_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/video/webcams.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl'] = '%(id)s/webcams.webm'
            self.ydl.process_ie_result(webcams_dl)
            webcams_success = True
        except DownloadError:
            pass

        deskshare_success = False
        try:
            self.to_screen("Downloading deskshare.webm")
            deskshare_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/deskshare/deskshare.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl'] = '%(id)s/deskshare.webm'
            self.ydl.process_ie_result(deskshare_dl)
            deskshare_success = True
        except DownloadError:
            pass

        pass

    def _write_slides(self, slides: [], path: str, ydl: YoutubeDL):

        for slide_url in slides:
            url_parsed = urlparse.urlparse(slide_url)
            slide_filename = posixpath.basename(url_parsed.path)

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


def extract_timings(bbb_version):
    doc = minidom.parse(events_file)
    dictionary = {}
    total_length = 0
    j = 0

    for image in doc.getElementsByTagName('image'):
        path = image.getAttribute('xlink:href')

        if j == 0 and '2.0.0' > bbb_version:
            path = u'/usr/local/bigbluebutton/core/scripts/logo.png'
            j += 1

        in_times = str(image.getAttribute('in')).split(' ')
        out_times = image.getAttribute('out').split(' ')

        temp = float(out_times[len(out_times) - 1])
        if temp > total_length:
            total_length = temp

        occurrences = len(in_times)
        for i in range(occurrences):
            dictionary[float(in_times[i])] = temp_dir + str(path)

    return dictionary, total_length


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


def rescale_presentation(new_height, new_width, dictionary, bbb_version):
    times = dictionary.keys()
    times.sort()
    for i, t in enumerate(times):
        # ?
        # print >> sys.stderr, "_rescale_presentation_"
        # print >> sys.stderr, (i, t)

        if i < 1 and '2.0.0' > bbb_version:
            continue

        # print >> sys.stderr, "_rescale_presentation_after_skip_"
        # print >> sys.stderr, (i, t)

        ffmpeg.rescale_image(dictionary[t], new_height, new_width, dictionary[t])


def check_presentation_dims(dictionary, dims, bbb_version):
    names = dims.keys()
    heights = []
    widths = []

    for i in names:
        temp = dims[i]
        heights.append(temp[0])
        widths.append(temp[1])

    height = max(heights)
    width = max(widths)

    dim1 = height % 2
    dim2 = width % 2

    new_height = height
    new_width = width

    if dim1 or dim2:
        if dim1:
            new_height += 1
        if dim2:
            new_width += 1

    rescale_presentation(new_height, new_width, dictionary, bbb_version)


def prepare(bbb_version):
    if not os.path.exists(target_dir):
        os.mkdir(target_dir)

    if not os.path.exists(temp_dir):
        os.mkdir(temp_dir)

    if not os.path.exists('audio'):
        global audio_path
        audio_path = temp_dir + 'audio/'
        os.mkdir(audio_path)
        ffmpeg.extract_audio_from_video('video/webcams.webm', audio_path + 'audio.ogg')

    shutil.copytree("presentation", temp_dir + "presentation")
    dictionary, length = extract_timings(bbb_version)
    # debug
    print("dictionary")
    print(dictionary)
    print("length")
    print(length)
    dims = get_different_presentations(dictionary)
    # debug
    print("dims")
    print(dims)
    check_presentation_dims(dictionary, dims, bbb_version)
    return dictionary, length, dims


def get_different_presentations(dictionary):
    times = dictionary.keys()
    print("times")
    print(times)
    presentations = []
    dims = {}
    for t in times:
        # ?if t < 1:
        # ?    continue

        name = dictionary[t].split("/")[7]
        # debug
        print("name")
        print(name)
        if name not in presentations:
            presentations.append(name)
            dims[name] = get_presentation_dims(name)

    return dims


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


def bbbversion():
    global bbb_ver
    bbb_ver = 0
    s_events = minidom.parse(source_events)
    for event in s_events.getElementsByTagName('recording'):
        bbb_ver = event.getAttribute('bbb_version')
    return bbb_ver


def run_download():
    print("\n<-------------------" + time.strftime("%c") + "----------------------->\n")

    bbb_version = bbbversion()
    print("bbb_version: " + bbb_version)

    os.chdir(source_dir)

    dictionary, length, dims = prepare(bbb_version)

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
