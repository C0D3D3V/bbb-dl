# Python script that downloads a lessen video from a published bbb recording.

# original authors: CreateWebinar.com <support@createwebinar.com>,
#                   Stefan Wallentowitz <stefan@wallentowitz.de>
#                   and Olivier Berger <olivier.berger@telecom-sudparis.eu>

import argparse
import os
import re
import shutil
import socket
import time
import types

from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError

from PIL import Image, ImageDraw

try:
    from cairosvg.surface import PNGSurface

    CAIROSVG_ERROR = None
    CAIROSVG_LOADED = True
except Exception as err_cairo:
    print(
        'Warning: Cairosvg could not be loaded,'
        + ' to speedup the `--add-annotations` option it is recommended to install cairosvg'
    )
    CAIROSVG_ERROR = err_cairo
    CAIROSVG_LOADED = False


from yt_dlp import YoutubeDL
from yt_dlp.compat import (
    compat_http_client,
    compat_urllib_error,
)
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessorError
from yt_dlp.utils import (
    determine_ext,
    DownloadError,
    encodeFilename,
    error_to_compat_str,
    xpath_text,
    xpath_with_ns,
)
from yt_dlp.downloader.common import FileDownloader
from yt_dlp.extractor.common import InfoExtractor

from bbb_dl.ffmpeg import FFMPEG
from bbb_dl.html2image import Html2Image
from bbb_dl.version import __version__

_s = lambda p: xpath_with_ns(p, {'svg': 'http://www.w3.org/2000/svg'})
_x = lambda p: xpath_with_ns(p, {'xlink': 'http://www.w3.org/1999/xlink'})


def dummy_to_stderr(self, message):
    return


class Slide:
    def __init__(
        self,
        img_id: str,
        url: str,
        filename: str,
        path: str,
        width: int,
        height: int,
        ts_in: float,
        ts_out: float,
        duration: float,
        annotations: ElementTree.Element = None,
    ):
        self.img_id = img_id
        self.url = url
        self.filename = filename
        self.path = path
        self.width = width
        self.height = height
        self.ts_in = ts_in
        self.ts_out = ts_out
        self.duration = duration
        self.annotations = annotations


class BonusImage:
    def __init__(
        self,
        url: str,
        filename: str,
        path: str,
        width: int,
        height: int,
    ):
        self.url = url
        self.filename = filename
        self.path = path
        self.width = width
        self.height = height


class BBBDL(InfoExtractor):
    _VALID_URL = r'''(?x)
                     (?P<website>https?://[^/]+)/playback/presentation/
                     (?P<version>[\d\.]+)/
                     (playback.html\?.*?meetingId=)?
                     (?P<id>[0-9a-f\-]+)
                   '''

    @staticmethod
    def get_user_data_directory():
        """Returns a platform-specific root directory for user application data."""
        if os.name == "nt":
            appdata = os.getenv("LOCALAPPDATA")
            if appdata:
                return appdata
            appdata = os.getenv("APPDATA")
            if appdata:
                return appdata
            return None
        # On non-windows, use XDG_DATA_HOME if set, else default to ~/.config.
        xdg_config_home = os.getenv("XDG_DATA_HOME")
        if xdg_config_home:
            return xdg_config_home
        return os.path.join(os.path.expanduser("~"), ".local/share")

    @staticmethod
    def get_project_data_directory():
        """
        Returns an Path object to the project config directory
        """
        data_dir = Path(BBBDL.get_user_data_directory()) / "bbb-dl"
        if not data_dir.is_dir():
            data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)

    def __init__(
        self,
        verbose: bool,
        no_check_certificate: bool,
        encoder: str,
        audiocodec: str,
        add_webcam: bool,
        add_annotations: bool,
        add_cursor: bool,
        keep_tmp_files: bool,
        verbose_chrome: bool,
        chrome_executable: str,
        ffmpeg_location: str,
        workingdir: str,
    ):
        self.add_webcam = add_webcam
        self.add_annotations = add_annotations
        self.add_cursor = add_cursor
        self.keep_tmp_files = keep_tmp_files
        self.verbose_chrome = verbose_chrome
        self.chrome_executable = chrome_executable
        self.ffmpeg_location = ffmpeg_location

        self.original_cwd = os.getcwd()
        if workingdir is not None:
            self._use_working_dir(workingdir)
        else:
            self._use_working_dir(self.get_project_data_directory())

        if '_VALID_URL_RE' not in self.__dict__:
            BBBDL._VALID_URL_RE = re.compile(self._VALID_URL)

        self.global_retries = 10
        ydl_options = {
            'retries': self.global_retries,
            'fragment_retries': self.global_retries,
        }
        if verbose:
            ydl_options.update({"verbose": True})
        if self.ffmpeg_location is not None:
            ydl_options.update({"ffmpeg_location": self.ffmpeg_location})

        if no_check_certificate:
            ydl_options.update({"nocheckcertificate": True})

        self.verbose = verbose
        self.ydl = YoutubeDL(ydl_options)
        try:
            self.ffmpeg = FFMPEG(self.ydl, encoder, audiocodec)
        except FFmpegPostProcessorError as err:
            Log.error(f'Error: {err}')
            exit(-1)
        super().__init__(self.ydl)

    def _get_automatic_captions(self, *args, **kwargs):
        return

    def _get_subtitles(self, *args, **kwargs):
        return

    def _mark_watched(self, *args, **kwargs):
        return

    def run(self, dl_url: str, filename: str, outputdir: str, backup: bool):
        if outputdir is not None:
            try:
                if not os.path.exists(outputdir):
                    os.makedirs(outputdir)
            except (OSError, IOError) as err:
                Log.error('Error: Unable to create output directory ' + error_to_compat_str(err))
                exit(-2)
            abs_outputdir = os.path.abspath(outputdir)
            if not backup:
                Log.info(f'Output directory for the final video is: {abs_outputdir}')

        else:
            Log.warning('You have not specified an output folder, using working directory as output folder.')
            abs_outputdir = os.path.abspath(self.original_cwd)
            if not backup:
                Log.warning(f'Output directory for the final video is: {abs_outputdir}')

        if not os.access(abs_outputdir, os.R_OK) or not os.access(abs_outputdir, os.W_OK):
            Log.error(f'Error: Unable to read or write in the output directory {os.getcwd()}')
            Log.warning(
                'You can choose an alternative output directory for the final video with the --outputdir option.'
            )
            exit(-3)

        m_obj = re.match(self._VALID_URL, dl_url)

        if m_obj is None:
            Log.error(
                f'Your URL {dl_url} does not match the bbb session pattern.'
                + ' If you think this URL should work, please open an issue on https://github.com/C0D3D3V/bbb-dl/issues'
            )
            exit(-4)

        video_id = m_obj.group('id')
        video_website = m_obj.group('website')

        self.to_screen("Downloading meta informations")
        # Make sure the lesson exists
        if not os.path.exists(video_id):
            self._download_webpage(dl_url, video_id)
        self._create_tmp_dir(video_id)
        if backup:
            Log.warning(f"Backup will be located in: {os.path.abspath(video_id)}")

        # Extract basic metadata
        metadata_url = video_website + '/presentation/' + video_id + '/metadata.xml'
        metadata_local_path = video_id + '/metadata.xml'
        metadata = self._download_and_backup_xml(metadata_url, metadata_local_path)

        shapes_url = video_website + '/presentation/' + video_id + '/shapes.svg'
        shapes_local_path = video_id + '/shapes.svg'
        shapes = self._download_and_backup_xml(shapes_url, shapes_local_path)

        cursor_url = video_website + '/presentation/' + video_id + '/cursor.xml'
        cursor_local_path = video_id + '/cursor.xml'
        cursor_infos = self._download_and_backup_xml(cursor_url, cursor_local_path)

        # Parse metadata.xml
        meta = metadata.find('./meta')
        start_time = xpath_text(metadata, 'start_time')
        recording_duration = float(xpath_text(metadata, './playback/duration')) / 1000.0  # in seconds
        title = xpath_text(meta, 'meetingName')
        try:
            bbb_origin_version = xpath_text(meta, 'bbb-origin-version')
            if bbb_origin_version is not None:
                bbb_version = bbb_origin_version.split(' ')[0]
                self.to_screen("BBB version: " + bbb_version)
        except IndexError:
            pass

        # Downlaoding Webcam / Deskshare
        video_base_url = video_website + '/presentation/' + video_id

        if not self.verbose:
            self.ydl.to_stderr_backup = self.ydl.to_stderr
            self.ydl.to_stderr = types.MethodType(dummy_to_stderr, self.ydl)

        webcams_path = video_id + '/webcams.webm'
        try:
            self.to_screen("Downloading webcams.webm")
            webcams_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/video/webcams.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl']['default'] = webcams_path
            self.ydl.process_ie_result(webcams_dl)
        except DownloadError:
            self.to_screen("Downloading webcams.webm failed! Downloading webcams.mp4 instead")
            webcams_path = video_id + '/webcams.mp4'
            try:
                webcams_dl = {
                    'id': video_id,
                    'title': title,
                    'url': video_base_url + '/video/webcams.mp4',
                    'timestamp': int(start_time),
                }
                self.ydl.params['outtmpl']['default'] = webcams_path
                self.ydl.process_ie_result(webcams_dl)
            except DownloadError:
                webcams_path = None
                Log.error(
                    'Error: Downloading webcams.mp4 failed! webcams.mp4 is essential.'
                    + ' Abort! Please try again later!'
                )
                exit(1)

        deskshare_path = video_id + '/deskshare.webm'
        try:
            self.to_screen("Downloading deskshare.webm")
            deskshare_dl = {
                'id': video_id,
                'title': title,
                'url': video_base_url + '/deskshare/deskshare.webm',
                'timestamp': int(start_time),
            }
            self.ydl.params['outtmpl']['default'] = deskshare_path
            self.ydl.process_ie_result(deskshare_dl)
        except DownloadError:
            self.to_screen("Downloading deskshare.webm failed! Downloading deskshare.mp4 instead")
            deskshare_path = video_id + '/deskshare.mp4'
            try:
                deskshare_dl = {
                    'id': video_id,
                    'title': title,
                    'url': video_base_url + '/deskshare/deskshare.mp4',
                    'timestamp': int(start_time),
                }
                self.ydl.params['outtmpl']['default'] = deskshare_path
                self.ydl.process_ie_result(deskshare_dl)
            except DownloadError:
                deskshare_path = None
                self.to_screen("Warning: Downloading deskshare.mp4 failed - No desk was likely shared in this session.")

        if not self.verbose:
            self.ydl.to_stderr = self.ydl.to_stderr_backup

        # Downloading Slides
        images = list()
        self.xml_find_rec(shapes, _s('svg:image'), images)
        # images = shapes.findall(_s("./svg:image[@class='slide']"))
        slides_infos = []
        bonus_images = []
        img_path_to_filename = {}
        counter = 0
        for image in images:
            img_path = image.get(_x('xlink:href'))
            image_url = video_website + '/presentation/' + video_id + '/' + img_path
            image_width = int(float(image.get('width')))
            image_height = int(float(image.get('height')))

            if not image.get('class') or image.get('class') != 'slide':
                image_filename = image_url.split('/')[-1]
                image_path = video_id + '/' + image_filename
                bonus_images.append(
                    BonusImage(
                        image_url,
                        image_filename,
                        image_path,
                        image_width,
                        image_height,
                    )
                )
                continue

            image_id = image.get('id')
            slide_annotations = shapes.find(_s("./svg:g[@image='{}']".format(image_id)))

            if img_path.endswith('deskshare.png'):
                if deskshare_path is None:
                    Log.error(
                        'Error: Downloading deskshare failed, but it is needed for the slideshow!'
                        + ' Abort! Please try again later!'
                    )
                    exit(2)
                image_url = video_website + '/presentation/' + video_id + '/deskshare/deskshare.webm'
                slide_filename = 'deskshare.webm'
                slide_path = deskshare_path
            else:
                if img_path not in img_path_to_filename:
                    slide_filename = 'slide-{:03d}'.format(counter) + '.' + determine_ext(img_path)
                    img_path_to_filename[img_path] = slide_filename
                    counter += 1
                else:
                    slide_filename = img_path_to_filename[img_path]
                slide_path = os.getcwd() + '/' + video_id + '/' + slide_filename

            slide_ts_in = float(image.get('in'))
            slide_ts_out = float(image.get('out'))
            slide_ts_duration = max(0.0, min(recording_duration - slide_ts_in, slide_ts_out - slide_ts_in))

            slides_infos.append(
                Slide(
                    image_id,
                    image_url,
                    slide_filename,
                    slide_path,
                    image_width,
                    image_height,
                    slide_ts_in,
                    slide_ts_out,
                    slide_ts_duration,
                    slide_annotations,
                )
            )

        # We now change the xml tree, all hrefs of all images now point to local files
        for image in images:
            image.attrib[_x('xlink:href')] = (
                os.getcwd() + '/' + video_id + '/' + image.attrib[_x('xlink:href')].split('/')[-1]
            )

        self.to_screen("Downloading slides")
        self._write_slides(slides_infos)
        self._write_slides(bonus_images)

        if backup:
            self.to_screen("Backup Finished")
            self.to_screen("You can run bbb-dl again to generate the video based on the backed up files!")
            Log.warning(f"Backup is located in: {os.path.abspath(video_id)}")
            return

        if self.add_annotations:
            slides_infos = self._add_annotations(slides_infos)
        if self.add_cursor:
            slides_infos = self._add_cursor(slides_infos, cursor_infos)

        for slides_info in slides_infos:
            slides_info.path = os.path.relpath(slides_info.path)

        # Post processing
        slideshow_w, slideshow_h = self._rescale_slides(slides_infos)

        slideshow_path = self._create_slideshow(slides_infos, video_id, slideshow_w, slideshow_h)

        formatted_date = datetime.fromtimestamp(int(start_time) / 1000).strftime('%Y-%m-%dT%H-%M-%S')

        if filename is not None:
            result_path = str(Path(abs_outputdir) / filename)
        else:
            result_path = str(
                Path(abs_outputdir) / (formatted_date + '_' + title.replace('/', '_', title.count('/')) + '.mp4')
            )

        self.to_screen("Mux Slideshow")
        webcam_w, webcam_h = self._get_webcam_size(slideshow_w, slideshow_h)

        if os.path.isfile(result_path):
            self.report_warning("Final Slideshow already exists. Abort!")
            return

        if self.add_webcam:
            self.ffmpeg.mux_slideshow_with_webcam(slideshow_path, webcams_path, webcam_w, webcam_h, result_path)
        else:
            self.ffmpeg.mux_slideshow(slideshow_path, webcams_path, result_path)

        if not self.keep_tmp_files:
            self.to_screen("Cleanup")
            self._remove_tmp_dir(video_id)

    def xml_find_rec(self, node, element, result):
        for el in list(node):
            self.xml_find_rec(el, element, result)
        if node.tag == element:
            result.append(node)

    def _use_working_dir(self, workingdir: str):
        try:
            if not os.path.exists(workingdir):
                os.makedirs(workingdir)
        except (OSError, IOError) as err:
            Log.warning(
                'You can choose an alternative working directory for the temporary files with the --workingdir option.'
            )
            Log.error('Error: Unable to create working directory for temporary files ' + error_to_compat_str(err))
            exit(-2)
        os.chdir(workingdir)
        if not os.access(os.getcwd(), os.R_OK) or not os.access(os.getcwd(), os.W_OK):
            Log.warning(
                'You can choose an alternative working directory for the temporary files with the --workingdir option.'
            )
            Log.error(f'Error: Unable to read or write in the working directory for temporary files {os.getcwd()}')
            exit(-3)

    def _create_tmp_dir(self, video_id):
        try:
            if not os.path.exists(video_id):
                os.makedirs(video_id)
            Log.info(f'The temporary files are generated in: {os.path.abspath(video_id)}')
        except (OSError, IOError) as err:
            Log.error('Error: Unable to create directory ' + error_to_compat_str(err))
            exit(-5)

    def _remove_tmp_dir(self, video_id):
        try:

            if os.path.exists(video_id):
                shutil.rmtree(video_id)
        except (OSError, IOError) as err:
            Log.error('Error: Unable to remove directory ' + error_to_compat_str(err))
            exit(-6)

    def _download_and_backup_xml(self, url: str, local_path: str):
        filePath = encodeFilename(local_path)
        if os.path.exists(filePath):
            self.to_screen('XML file %s is already present' % (local_path))
        else:
            self.to_screen('Downloading XML file %s...' % (url))
            try_num = 1
            while True:
                try:
                    url_f = self.ydl.urlopen(url)
                    with open(filePath, 'wb') as xml_f:
                        shutil.copyfileobj(url_f, xml_f)
                    self.to_screen('Successfully downloaded to: %s' % (local_path))
                    break
                except (compat_urllib_error.URLError, compat_http_client.HTTPException, socket.error) as err:
                    if os.path.exists(filePath):
                        os.remove(filePath)
                    self.report_warning(
                        f'(Try {try_num} of {self.global_retries}) Unable to download XML file "{url}":'
                        + f' {error_to_compat_str(err)}'
                    )
                    if try_num == self.global_retries:
                        Log.error('Error: XML files are essential. Abort! Please try again later!')
                        exit(3)
                    try_num += 1
        try:
            tree_root = ElementTree.parse(filePath).getroot()
        except ParseError as err:
            Log.error('Unable to parse XML file "%s": %s' % (url, error_to_compat_str(err)))
            Log.error('Error: XML files are essential. Abort! Please try again later!')
            exit(3)
        return tree_root

    def _write_slides(self, slides_infos: {}):
        for slide in slides_infos:
            filePath = encodeFilename(slide.path)
            if os.path.exists(filePath):
                self.to_screen('Slide %s is already present' % (slide.filename))
            else:
                self.to_screen('Downloading slide %s...' % (slide.filename))
                try_num = 1
                while True:
                    try:
                        url_f = self.ydl.urlopen(slide.url)
                        with open(filePath, 'wb') as slide_f:
                            shutil.copyfileobj(url_f, slide_f)
                        self.to_screen('Successfully downloaded to: %s' % (slide.path))
                        break
                    except (compat_urllib_error.URLError, compat_http_client.HTTPException, socket.error) as err:
                        if os.path.exists(filePath):
                            os.remove(filePath)
                        self.report_warning(
                            f'(Try {try_num} of {self.global_retries}) Unable to download XML file "{slide.url}":'
                            + f' {error_to_compat_str(err)}'
                        )
                        if try_num == self.global_retries:
                            Log.error('Error: Slides are essential. Abort! Please try again later!')
                            exit(4)
                        try_num += 1

    def _add_annotations(self, slides_infos: []):
        """Expandes the slides_infos with all annotation slides"""

        result_list = []

        for frame_id, slide in enumerate(slides_infos):
            if slide.annotations is None:
                result_list.append(slide)
            else:
                annotation_slides = []

                svg_root = self._create_svg_root_for_slide(slide)

                real_ts_in = None
                ignore_original_slide = False
                draw_elements = slide.annotations.findall(_s("./svg:g[@timestamp]"))
                for i, draw_elm in enumerate(draw_elements):
                    ts_in = int(float(draw_elm.get('timestamp')))

                    if ts_in <= int(slide.ts_in):
                        ignore_original_slide = True
                        ts_in = slide.ts_in

                    if i == len(draw_elements) - 1:
                        ts_out = slide.ts_out
                        next_ts_in = None
                    else:
                        ts_out = next_ts_in = int(float(draw_elements[i + 1].get('timestamp')))

                    # make it visible
                    style = draw_elm.attrib["style"].split(";")
                    style.remove("visibility:hidden")
                    draw_elm.attrib["style"] = ";".join(style)

                    svg_root.append(draw_elm)

                    # if next has same timestamp, create only one
                    if next_ts_in is not None and next_ts_in <= ts_in:
                        if real_ts_in is None:
                            real_ts_in = ts_in
                        continue
                    if real_ts_in is not None:
                        ts_in = real_ts_in
                        real_ts_in = None

                    old_path_parts = slide.path.split('.')
                    old_filename_parts = slide.filename.split('.')
                    new_path = old_path_parts[0] + '_f{:02d}_p{:02d}.'.format(frame_id, i) + old_path_parts[1]
                    new_filename = (
                        old_filename_parts[0] + '_f{:02d}_p{:02d}.'.format(frame_id, i) + old_filename_parts[1]
                    )

                    self.to_screen(
                        "Paint image {} with annotation {}/{} (Frame: {}/{})".format(
                            slide.filename, i, len(draw_elements) - 1, frame_id, len(slides_infos) - 1
                        )
                    )

                    self.convert_svg_to_png(svg_root, slide.width, slide.height, new_path)

                    annotation_slides.append(
                        Slide(
                            slide.img_id,
                            slide.url,
                            new_filename,
                            new_path,
                            slide.width,
                            slide.height,
                            ts_in,
                            ts_out,
                            max(0, ts_out - ts_in),
                        )
                    )

                if len(annotation_slides) == 0:
                    result_list.append(slide)
                else:
                    if not ignore_original_slide:
                        slide.ts_out = annotation_slides[0].ts_in
                        slide.duration = slide.ts_out - slide.ts_in
                        result_list.append(slide)
                    result_list += annotation_slides

        return result_list

    def strip_namespace(self, el):
        """Remove namespaces"""
        if el.tag.startswith("{"):
            el.tag = el.tag.split('}', 1)[1]  # strip namespace
        keys = list(el.attrib.keys())
        for k in keys:
            if k.startswith("{"):
                k2 = k.split('}', 1)[1]
                el.attrib[k2] = el.attrib[k]
                del el.attrib[k]
        for child in el:
            self.strip_namespace(child)

    def _add_cursor(self, slides_infos: [], cursor_infos: ElementTree):
        """Expandes the slides_infos with all cursors"""

        result_list = []

        real_ts_in = None
        cursors = cursor_infos.findall("event[@timestamp]")
        cursors[0].attrib['timestamp'] = '0.0'

        for cursor_id, cursor in enumerate(cursors):
            cursor = cursors[cursor_id]

            ts_in = int(float(cursor.get('timestamp')))

            if cursor_id == len(cursors) - 1:
                ts_out = slides_infos[len(slides_infos) - 1].ts_out
                if ts_out < ts_in:
                    self.to_screen("Ignored cursor at {}".format(ts_in))
                    continue
                next_ts_in = None
            else:
                ts_out = next_ts_in = int(float(cursors[cursor_id + 1].get('timestamp')))

            # if next has same timestamp, create only one
            if next_ts_in is not None and next_ts_in <= ts_in:
                if real_ts_in is None:
                    real_ts_in = ts_in
                continue

            if real_ts_in is not None:
                ts_in = real_ts_in
                real_ts_in = None

            slides = self._get_slides_between(slides_infos, ts_in, ts_out)
            location_text = cursor.find('cursor').text
            l_x_percent = float(location_text.split(' ')[0])
            l_y_percent = float(location_text.split(' ')[1])
            for slide in slides:

                new_path = slide.path
                new_filename = slide.filename

                if l_x_percent != -1 and l_y_percent != -1:
                    # svg_root = self._create_svg_root_for_slide(slide)
                    # svg_root.append(self._create_pointer(slide, l_x_percent, l_y_percent))

                    old_path_parts = slide.path.split('.')
                    old_filename_parts = slide.filename.split('.')
                    new_path = old_path_parts[0] + '_c{:02d}.'.format(cursor_id) + old_path_parts[1]
                    new_filename = old_filename_parts[0] + '_c{:02d}.'.format(cursor_id) + old_filename_parts[1]

                    self.to_screen(
                        "Paint cursor on slide {} (Cursor: {}/{})".format(
                            slide.filename,
                            cursor_id,
                            len(cursors) - 1,
                        )
                    )

                    self._paint_cursor(slide, l_x_percent, l_y_percent, new_path)

                    # self.convert_svg_to_png(svg_root, slide.width, slide.height, new_path)

                tmp_ts_out = ts_out
                if slide.ts_out < ts_out:
                    tmp_ts_out = slide.ts_out

                result_list.append(
                    Slide(
                        slide.img_id,
                        slide.url,
                        new_filename,
                        new_path,
                        slide.width,
                        slide.height,
                        ts_in,
                        tmp_ts_out,
                        max(0, tmp_ts_out - ts_in),
                    )
                )
                ts_in = tmp_ts_out

        return result_list

    def _paint_cursor(self, slide, l_x_percent, l_y_percent, output_path):
        if os.path.isfile(output_path):
            return

        r = 6
        cx = slide.width * l_x_percent - r
        cy = slide.height * l_y_percent - r

        try:
            with Image.open(slide.path) as image:
                image = image.convert('RGB')
                draw = ImageDraw.Draw(image)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 0, 0))

                image.save(output_path)
        except (OSError, IOError) as err:
            Log.error(f'This slide is broken: {os.path.abspath(slide.path)}')
            Log.warning('Please check the file and remove it. Then run the command again!')
            Log.error(f'Error: {err}')
            exit(6)

    def _create_svg_root_for_slide(self, slide):
        svg_root = ElementTree.Element(
            '{http://www.w3.org/2000/svg}svg',
            {
                'version': '1.1',
                'id': 'svgfile',
                'style': 'position:absolute',
                'viewBox': '0 0 {} {}'.format(slide.width, slide.height),
            },
        )
        svg_root.append(
            ElementTree.Element(
                '{http://www.w3.org/2000/svg}image',
                {
                    '{http://www.w3.org/1999/xlink}href': slide.path,
                    'width': str(slide.width),
                    'height': str(slide.height),
                    'x': '0',
                    'y': '0',
                },
            )
        )
        return svg_root

    def _create_pointer(self, slide, l_x_percent, l_y_percent):
        cx = slide.width * l_x_percent - 6
        cy = slide.height * l_y_percent - 6

        pointer_svg = ElementTree.Element(
            '{http://www.w3.org/2000/svg}circle',
            {
                'cx': str(cx),
                'cy': str(cy),
                'fill': 'red',
                'r': '6',
            },
        )
        return pointer_svg

    def _get_slides_between(self, slides_infos: [], ts_in: int, ts_out: int):
        """Retrun a Frame at a specific time stamp"""

        selected_slides = []
        for slide in slides_infos:
            if int(slide.ts_in) <= ts_in and int(slide.ts_out) > ts_in and int(slide.ts_in) < ts_out:
                selected_slides.append(slide)
            if int(slide.ts_in) >= ts_out:
                break

        if len(selected_slides) == 0:
            self.to_screen("There is are no slides between {} and {}".format(ts_in, ts_out))
            return [slides_infos[len(slides_infos) - 1]]
        else:
            return selected_slides

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

        for slide in slides_infos:
            widths.append(slide.width)
            heights.append(slide.height)

        if len(widths) == 0 or len(heights) == 0:
            return

        new_width = max(widths)
        new_height = max(heights)

        if new_width % 2:
            new_width += 1
        if new_height % 2:
            new_height += 1

        for slide in slides_infos:
            if new_width == slide.width and new_height == slide.height:
                continue

            if slide.filename == 'deskshare.webm':
                continue

            old_path_parts = slide.path.split('.')
            old_filename_parts = slide.filename.split('.')
            rescaled_path = old_path_parts[0] + '_scaled.' + old_path_parts[1]
            rescaled_filename = old_filename_parts[0] + '_scaled.' + old_filename_parts[1]

            if not os.path.isfile(rescaled_path):
                self.to_screen('Rescale %s' % (slide.filename,))
                self.ffmpeg.rescale_image(slide.path, rescaled_path, new_width, new_height)

            slide.path = rescaled_path
            slide.filename = rescaled_filename
        return new_width, new_height

    def _create_slideshow(self, slides_infos: {}, video_id: str, width: int, height: int):
        slideshow_path = video_id + '/slideshow.mp4'

        video_list = video_id + '/video_list.txt'
        vl_file = open(video_list, 'w', encoding="utf-8")

        self.to_screen("Create slideshow")
        for i, slide in enumerate(slides_infos):
            tmp_ts_name = '{:04d}.ts'.format(i)
            out_ts_file = video_id + '/' + tmp_ts_name

            try:
                if slide.filename == "deskshare.webm":
                    self.to_screen(
                        "Trimming deskshare (frame %s / %s) at time stamp %s (Duration: %s)"
                        % (
                            i,
                            len(slides_infos) - 1,
                            FileDownloader.format_seconds(slide.ts_in),
                            FileDownloader.format_seconds(slide.duration),
                        )
                    )
                    self.ffmpeg.trim_video_by_seconds(
                        slide.path, slide.ts_in, slide.duration, width, height, out_ts_file
                    )
                else:
                    self.to_screen(
                        "Trimming slide (frame %s / %s) at time stamp %s (Duration: %s)"
                        % (
                            i,
                            len(slides_infos) - 1,
                            FileDownloader.format_seconds(slide.ts_in),
                            FileDownloader.format_seconds(slide.duration),
                        )
                    )
                    self.ffmpeg.create_video_from_image(slide.path, slide.duration, out_ts_file)

            except (FFmpegPostProcessorError, KeyboardInterrupt) as e:
                Log.error('Error: Something went wrong, please try again!\nError: {}'.format(e))
                if os.path.isfile(out_ts_file):
                    os.remove(out_ts_file)
                vl_file.close()
                exit(5)

            vl_file.write("file " + tmp_ts_name + "\n")
        vl_file.close()

        self.to_screen("Concat Slideshow")
        self.ffmpeg.concat_videos(video_list, slideshow_path)
        return slideshow_path

    def convert_svg_to_png(self, svg_root, width: int, height: int, output_path: str):
        if os.path.isfile(output_path):
            return

        use_html2image = False
        if svg_root.find(_s("./svg:foreignObject")) is not None or CAIROSVG_LOADED is False:
            use_html2image = True
        svg_bytes = ElementTree.tostring(svg_root)

        if use_html2image:
            self.strip_namespace(svg_root)
            body = f"""
            <html style="width: {width}px;height: {height}px;">
            <body>{svg_bytes.decode()}</body>
            </html>
            """

            Html2Image(
                output_path=os.path.dirname(output_path),
                browser_executable=self.chrome_executable,
                verbose=self.verbose,
                verbose_chrome=self.verbose_chrome,
            ).screenshot(html_str=body, save_as=os.path.basename(output_path), size=(width, height))
        else:
            PNGSurface.convert(
                bytestring=svg_bytes,
                width=width,
                height=height,
                write_to=open(output_path, 'wb'),
            )


RESET_SEQ = '\033[0m'
COLOR_SEQ = '\033[1;%dm'

BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(30, 38)


class Log:
    """
    Logs a given string to output with colors
    :param logString: the string that should be logged

    The string functions returns the strings that would be logged.
    """

    @staticmethod
    def info_str(logString: str):
        return COLOR_SEQ % WHITE + logString + RESET_SEQ

    @staticmethod
    def special_str(logString: str):
        return COLOR_SEQ % BLUE + logString + RESET_SEQ

    @staticmethod
    def debug_str(logString: str):
        return COLOR_SEQ % CYAN + logString + RESET_SEQ

    @staticmethod
    def warning_str(logString: str):
        return COLOR_SEQ % YELLOW + logString + RESET_SEQ

    @staticmethod
    def error_str(logString: str):
        return COLOR_SEQ % RED + logString + RESET_SEQ

    @staticmethod
    def critical_str(logString: str):
        return COLOR_SEQ % MAGENTA + logString + RESET_SEQ

    @staticmethod
    def success_str(logString: str):
        return COLOR_SEQ % GREEN + logString + RESET_SEQ

    @staticmethod
    def info(logString: str):
        print(Log.info_str(logString))

    @staticmethod
    def special(logString: str):
        print(Log.special_str(logString))

    @staticmethod
    def debug(logString: str):
        print(Log.debug_str(logString))

    @staticmethod
    def warning(logString: str):
        print(Log.warning_str(logString))

    @staticmethod
    def error(logString: str):
        print(Log.error_str(logString))

    @staticmethod
    def critical(logString: str):
        print(Log.critical_str(logString))

    @staticmethod
    def success(logString: str):
        print(Log.success_str(logString))


class Timer(object):
    '''
    Timing Context Manager
    Can be used for future speed comparisons, like this:

    with Timer() as t:
        Do.stuff()
    print(f'Do.stuff() took:\t {t.duration:.3f} \tseconds.')
    '''

    def __enter__(self):
        self.start = time.perf_counter_ns()
        return self

    def __exit__(self, *args):
        end = time.perf_counter_ns()
        self.duration = (end - self.start) * 10**-9  # 1 nano-sec = 10^-9 sec


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser(
        description=('Big Blue Button Downloader that downloads a BBB lesson as MP4 video')
    )

    parser.add_argument('URL', type=str, help='URL of a BBB lesson')

    parser.add_argument(
        '-aw',
        '--add-webcam',
        action='store_true',
        help='add the webcam video as an overlay to the final video',
    )

    parser.add_argument(
        '-aa',
        '--add-annotations',
        action='store_true',
        help='add the annotations of the professor to the final video',
    )

    parser.add_argument(
        '-ac',
        '--add-cursor',
        action='store_true',
        help='add the cursor of the professor to the final video [Experimental, very slow, untested]',
    )

    parser.add_argument(
        '-bk',
        '--backup',
        action='store_true',
        help=(
            'downloads all the content from the server and then stops. After using this option, you can run bbb-dl'
            + ' again to create the video based on the saved files'
        ),
    )
    parser.add_argument(
        '-kt',
        '--keep-tmp-files',
        action='store_true',
        help=(
            'keep the temporary files after finish. In case of an error bbb-dl will reuse the already generated files'
        ),
    )

    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help=('print more verbose debug informations'),
    )

    parser.add_argument(
        '-vc',
        '--verbose-chrome',
        action='store_true',
        help=('print more verbose debug informations of the chrome browser that is used to generate screenshots'),
    )

    parser.add_argument(
        '--chrome-executable',
        type=str,
        default=None,
        help='Optional path to your installed Chrome executable (Use it if the path is not detected automatically)',
    )

    parser.add_argument(
        '--ffmpeg-location',
        type=str,
        default=None,
        help='Optional path to the directory in that your installed ffmpeg executable is located'
        + ' (Use it if the path is not detected automatically)',
    )

    parser.add_argument(
        '-ncc',
        '--no-check-certificate',
        action='store_true',
        help=('Suppress HTTPS certificate validation'),
    )

    parser.add_argument(
        '--version', action='version', version='bbb-dl ' + __version__, help='Print program version and exit'
    )

    parser.add_argument(
        '--encoder',
        dest='encoder',
        type=str,
        default='libx264',
        help='Optional encoder to pass to ffmpeg (default libx264)',
    )
    parser.add_argument(
        '--audiocodec',
        dest='audiocodec',
        type=str,
        default='copy',
        help='Optional audiocodec to pass to ffmpeg (default copy the codec from the original source)',
    )

    parser.add_argument(
        '-f',
        '--filename',
        type=str,
        help='Optional output filename',
    )

    parser.add_argument(
        '-od',
        '--outputdir',
        type=str,
        help='Optional output directory for final video',
    )

    parser.add_argument(
        '-wd',
        '--workingdir',
        type=str,
        help='Optional output directory for all temporary directories/files',
    )
    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    parser = get_parser()
    args = parser.parse_args(args)
    if args.verbose and not CAIROSVG_LOADED and CAIROSVG_ERROR is not None:
        print(f'The error was: {CAIROSVG_ERROR}')

    BBBDL(
        args.verbose,
        args.no_check_certificate,
        args.encoder,
        args.audiocodec,
        args.add_webcam,
        args.add_annotations,
        args.add_cursor,
        args.keep_tmp_files,
        args.verbose_chrome,
        args.chrome_executable,
        args.ffmpeg_location,
        args.workingdir,
    ).run(
        args.URL,
        args.filename,
        args.outputdir,
        args.backup,
    )
