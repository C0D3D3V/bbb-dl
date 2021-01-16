# Python script that downloads a lessen video from a published bbb recording.

# original authors: CreateWebinar.com <support@createwebinar.com>,
#                   Stefan Wallentowitz <stefan@wallentowitz.de>
#                   and Olivier Berger <olivier.berger@telecom-sudparis.eu>

import argparse
import os
import re
import shutil
import socket

from xml.etree import ElementTree

import youtube_dl

from PIL import Image, ImageDraw
from youtube_dl import YoutubeDL
from datetime import datetime

from cairosvg.surface import PNGSurface
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

from youtube_dl.downloader.common import FileDownloader

from youtube_dl.extractor.common import InfoExtractor
from youtube_dl.postprocessor.ffmpeg import FFmpegPostProcessorError

from bbb_dl.ffmpeg import FFMPEG

from bbb_dl.version import __version__

_s = lambda p: xpath_with_ns(p, {'svg': 'http://www.w3.org/2000/svg'})
_x = lambda p: xpath_with_ns(p, {'xlink': 'http://www.w3.org/1999/xlink'})


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


class BBBDL(InfoExtractor):
    _VALID_URL = (
        r'(?P<website>https?://[^/]+)/playback/presentation/2.0/playback.html\?.*?meetingId=(?P<id>[0-9a-f\-]+)'
    )

    def __init__(self, verbose: bool, no_check_certificate: bool):
        if '_VALID_URL_RE' not in self.__dict__:
            BBBDL._VALID_URL_RE = re.compile(self._VALID_URL)

        ydl_options = {}
        if verbose:
            ydl_options.update({"verbose": True})

        if no_check_certificate:
            ydl_options.update({"nocheckcertificate": True})

        self.verbose = verbose
        self.ydl = youtube_dl.YoutubeDL(ydl_options)
        self.set_downloader(self.ydl)
        self.ffmpeg = FFMPEG(self.ydl)

    def run(self, dl_url: str, add_webcam: bool, add_annotations: bool, add_cursor, keep_tmp_files: bool):
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

        cursor_url = video_website + '/presentation/' + video_id + '/cursor.xml'
        cursor_infos = self._download_xml(cursor_url, video_id)

        # Parse metadata.xml
        meta = metadata.find('./meta')
        start_time = xpath_text(metadata, 'start_time')
        title = xpath_text(meta, 'meetingName')
        bbb_version = xpath_text(meta, 'bbb-origin-version').split(' ')[0]
        self.to_screen("BBB version: " + bbb_version)

        # Downloading Slides
        images = shapes.findall(_s("./svg:image[@class='slide']"))
        slides_infos = []
        img_path_to_filename = {}
        counter = 0
        for image in images:
            img_path = image.get(_x('xlink:href'))

            image_id = image.get('id')
            image_url = video_website + '/presentation/' + video_id + '/' + img_path
            image_width = int(image.get('width'))
            image_height = int(image.get('height'))
            slide_annotations = shapes.find(_s("./svg:g[@image='{}']".format(image_id)))

            if img_path.endswith('deskshare.png'):
                image_url = video_website + '/presentation/' + video_id + '/deskshare/deskshare.webm'
                slide_filename = 'deskshare.webm'
            else:
                if img_path not in img_path_to_filename:
                    slide_filename = 'slide-{:03d}'.format(counter) + '.' + determine_ext(img_path)
                    img_path_to_filename[img_path] = slide_filename
                    counter += 1
                else:
                    slide_filename = img_path_to_filename[img_path]

            slide_path = video_id + '/' + slide_filename
            slide_ts_in = float(image.get('in'))
            slide_ts_out = float(image.get('out'))

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
                    max(0, slide_ts_out - slide_ts_in),
                    slide_annotations,
                )
            )

        self.to_screen("Downloading slides")
        self._write_slides(slides_infos, self.ydl)
        if add_annotations:
            slides_infos = self._add_annotations(slides_infos)
        if add_cursor:
            slides_infos = self._add_cursor(slides_infos, cursor_infos)

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

        slideshow_path = self._create_slideshow(slides_infos, video_id, slideshow_w, slideshow_h)

        formatted_date = datetime.fromtimestamp(int(start_time) / 1000).strftime('%Y-%m-%dT%H-%M-%S')
        result_path = formatted_date + '_' + title + '.mp4'
        self.to_screen("Mux Slideshow")
        webcam_w, webcam_h = self._get_webcam_size(slideshow_w, slideshow_h)

        if os.path.isfile(result_path):
            self.report_warning("Final Slideshow already exists. Abort!")
            return

        if add_webcam:
            self.ffmpeg.mux_slideshow_with_webcam(slideshow_path, webcams_path, webcam_w, webcam_h, result_path)
        else:
            self.ffmpeg.mux_slideshow(slideshow_path, webcams_path, result_path)

        if not keep_tmp_files:
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
        for slide in slides_infos:
            if os.path.exists(encodeFilename(slide.path)):
                self.to_screen('Slide %s is already present' % (slide.filename))
            else:
                self.to_screen('Downloading slide %s...' % (slide.filename))
                try_num = 1
                try:
                    url_f = ydl.urlopen(slide.url)
                    with open(encodeFilename(slide.path), 'wb') as slide_f:
                        shutil.copyfileobj(url_f, slide_f)
                    self.to_screen('Successfully downloaded to: %s' % (slide.path))
                except (compat_urllib_error.URLError, compat_http_client.HTTPException, socket.error) as err:
                    self.report_warning(
                        '(Try %s of 3) Unable to download slide "%s": %s'
                        % (try_num, slide.url, error_to_compat_str(err))
                    )
                    if try_num == 3:
                        self.report_warning('Slides are essential. Abort! Please try again later!')
                        exit(1)
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
                for i in range(len(draw_elements)):
                    draw_elm = draw_elements[i]
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
                    self.convert_svg_to_png(ElementTree.tostring(svg_root), slide.width, slide.height, new_path)

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

    def _add_cursor(self, slides_infos: [], cursor_infos: ElementTree):
        """Expandes the slides_infos with all cursors"""

        result_list = []

        real_ts_in = None
        cursors = cursor_infos.findall("event[@timestamp]")
        cursors[0].attrib['timestamp'] = '0.0'

        for cursor_id in range(len(cursors)):
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

                    # self.convert_svg_to_png(ElementTree.tostring(svg_root), slide.width, slide.height, new_path)

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

        with Image.open(slide.path) as image:
            image = image.convert('RGB')
            draw = ImageDraw.Draw(image)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 0, 0))

            image.save(output_path)

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
        vl_file = open(video_list, 'w')

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
                self.report_warning('Something went wrong, please try again!\nError: {}'.format(e))
                if os.path.isfile(out_ts_file):
                    os.remove(out_ts_file)
                vl_file.close()
                exit(1)

            vl_file.write("file " + tmp_ts_name + "\n")
        vl_file.close()

        self.to_screen("Concat Slideshow")
        self.ffmpeg.concat_videos(video_list, slideshow_path)
        return slideshow_path

    def convert_svg_to_png(self, svg_bytes, width, height, output_path):
        if os.path.isfile(output_path):
            return
        PNGSurface.convert(
            bytestring=svg_bytes,
            width=width,
            height=height,
            write_to=open(output_path, 'wb'),
        )


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

    """
    parser.add_argument(
        '-ac',
        '--add-cursor',
        action='store_true',
        help='add the cursor of the professor to the final video',
    )
    """

    parser.add_argument(
        '-kt',
        '--keep-tmp-files',
        action='store_true',
        help=('keep the temporary files after finish'),
    )

    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help=('print more verbose debug informations'),
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

    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    parser = get_parser()
    args = parser.parse_args(args)

    BBBDL(args.verbose, args.no_check_certificate).run(
        args.URL,
        args.add_webcam,
        args.add_annotations,
        False,
        args.keep_tmp_files,
    )
