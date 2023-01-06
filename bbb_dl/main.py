# Python script that downloads a lessen video from a published bbb recording.

import argparse
import asyncio
import hashlib
import math
import os
import re
import shutil
import traceback

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import partial
from http.server import ThreadingHTTPServer
from itertools import cycle
from pathlib import Path
from threading import Thread
from typing import List, Dict, Any, Tuple
from xml.etree import ElementTree
from xml.etree.ElementTree import ParseError, Element

import aiohttp
import aiofiles

from aiohttp.client_exceptions import ClientError, ClientResponseError
from playwright.async_api import async_playwright
from playwright.async_api._generated import Page

from bbb_dl.ffmpeg import FFMPEG
from bbb_dl.utils import (
    _s,
    _x,
    append_get_idx,
    format_bytes,
    formatSeconds,
    get_free_port,
    Log,
    PathTools as PT,
    QuietRequestHandler,
    Timer,
    xpath_text,
)
from bbb_dl.version import __version__


class ActionType(Enum):
    show_image = 1
    hide_image = 2
    show_drawing = 3
    hide_drawing = 4
    set_view_box = 5
    move_cursor = 6


@dataclass
class Action:
    action_type: ActionType
    element_id: str = None
    value: Any = None
    width: int = None
    height: int = None
    x: int = None
    y: int = None


@dataclass
class Metadata:
    date: int
    date_formatted: str
    duration: float
    title: str
    bbb_version: str = None


@dataclass
class Frame:
    timestamp: float
    actions: [Action]
    capture_rel_path: str = None
    capture_path: str = None


@dataclass
class Deskshare:
    start_timestamp: float
    stop_timestamp: float
    width: int
    height: int


class BBBDL:
    VALID_URL_RE = re.compile(
        r'''(?x)
            (?P<website>https?://[^/]+)/playback/presentation/
            (?P<version>[\d\.]+)/
            (playback.html\?.*?meetingId=)?
            (?P<id>[0-9a-f\-]+)
        '''
    )
    NUMBER_RE = re.compile(r'\d+')

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en',
        'Accept-Encoding': 'deflate, gzip',
    }

    def __init__(
        self,
        dl_url: str,
        filename: str,
        output_dir: str,
        verbose: bool,
        no_check_certificate: bool,
        encoder: str,
        audiocodec: str,
        skip_webcam: bool,
        skip_webcam_freeze_detection: bool,
        skip_annotations: bool,
        skip_cursor: bool,
        keep_tmp_files: bool,
        ffmpeg_location: str,
        working_dir: str,
        backup: bool,
        max_parallel_chromes: int,
        force_width: int,
        force_height: int,
    ):
        # Rendering options
        self.skip_webcam_opt = skip_webcam
        self.skip_webcam_freeze_detection_opt = skip_webcam_freeze_detection
        self.skip_annotations_opt = skip_annotations
        self.skip_cursor_opt = skip_cursor
        # BBB-dl Options
        self.keep_tmp_files = keep_tmp_files
        self.backup = backup
        self.working_dir = self.get_working_dir(working_dir)
        self.verbose = verbose
        self.no_check_certificate = no_check_certificate
        self.max_dl_retries = 10
        self.max_parallel_dl = 5
        self.max_parallel_chromes = int(max_parallel_chromes)

        # Job Options
        self.dl_url = dl_url
        self.filename = filename
        self.output_dir = self.get_output_dir(output_dir)
        self.force_width = int(force_width) if force_width is not None else None
        self.force_height = int(force_height) if force_height is not None else None

        self.ffmpeg = FFMPEG(verbose, ffmpeg_location, encoder, audiocodec)

        # Check DL-URL
        m_obj = re.match(self.VALID_URL_RE, self.dl_url)

        if m_obj is None:
            Log.error(
                f'Error: Your URL {self.dl_url} does not match the bbb session pattern.'
                + ' If you think this URL should work, please open an issue on https://github.com/C0D3D3V/bbb-dl/issues'
            )
            exit(-4)

        self.video_id = m_obj.group('id')
        self.video_website = m_obj.group('website')
        self.presentation_base_url = self.video_website + '/presentation/' + self.video_id
        self.tmp_dir = self.get_tmp_dir(self.video_id)
        self.frames_dir = self.get_frames_dir()

    def run(self):
        if not self.backup:
            Log.yellow(f'Output directory for the final video is: {self.output_dir}')
            Log.yellow(f'Directory for the temporary files is: {self.tmp_dir}')
        else:
            Log.yellow(f'Output directory for backup is: {self.tmp_dir}')

        Log.info("Downloading meta information")

        dl_jobs = ['metadata.xml', 'shapes.svg']
        _ = asyncio.run(self.batch_download_from_bbb(dl_jobs))

        Log.info("Downloading webcams / deskshare")
        dl_jobs = ['cursor.xml', 'panzooms.xml', 'captions.json', 'deskshare.xml', 'events.xml']
        cam_webm_idx = append_get_idx(dl_jobs, 'video/webcams.webm')
        cam_mp4_idx = append_get_idx(dl_jobs, 'video/webcams.mp4')
        dsk_webm_idx = append_get_idx(dl_jobs, 'deskshare/deskshare.webm')
        dsk_mp4_idx = append_get_idx(dl_jobs, 'deskshare/deskshare.mp4')

        dl_results = asyncio.run(self.batch_download_from_bbb(dl_jobs, False))

        if not dl_results[cam_webm_idx] and not dl_results[cam_mp4_idx]:
            Log.error('Error: webcams video is essential. Abort! Please try again later!')
            exit(4)
        webcams_rel_path = 'video/webcams.webm' if dl_results[cam_webm_idx] else 'video/webcams.mp4'
        webcams_path = PT.get_in_dir(self.tmp_dir, webcams_rel_path)

        deskshare_rel_path = (
            'deskshare/deskshare.webm'
            if dl_results[dsk_webm_idx]
            else 'deskshare/deskshare.mp4'
            if dl_results[dsk_mp4_idx]
            else None
        )
        deskshare_path = PT.get_in_dir(self.tmp_dir, deskshare_rel_path) if deskshare_rel_path is not None else None

        Log.info("Downloading slides")
        loaded_shapes = self.load_xml('shapes.svg')
        dl_jobs = self.get_all_image_urls(loaded_shapes)
        _ = asyncio.run(self.batch_download_from_bbb(dl_jobs))

        metadata = self.parse_metadata()
        deskshare_events = self.parse_deskshare_data(metadata.duration)
        if deskshare_path is None and len(deskshare_events) == 0:
            Log.yellow('No desk was shared in this session')
        elif deskshare_path is None and len(deskshare_events) > 0:
            Log.error(
                'Error: deskshare video is essential, because a desk was shared in this session.'
                + ' Abort! Please try again later!'
            )
            exit(5)

        if self.backup:
            Log.success("Backup Finished")
            Log.info("You can run bbb-dl again to generate the video based on the backed up files!")
            Log.yellow(f"Backup is located in: {self.tmp_dir}")
            return

        frames, only_zooms, partitions = self.parse_slides_data(loaded_shapes, metadata)
        self.create_frames(frames, only_zooms, partitions)

        slideshow_width, slideshow_height = self.get_slideshow_size(only_zooms, deskshare_path)
        if self.force_width is not None:
            slideshow_width = self.force_width
        if self.force_height is not None:
            slideshow_height = self.force_height
        slideshow_path = self.create_slideshow(frames, slideshow_width, slideshow_height)
        slideshow_path = self.add_deskshare_to_slideshow(
            slideshow_path, deskshare_path, deskshare_events, slideshow_width, slideshow_height, metadata
        )

        result_path = self.final_mux(
            slideshow_path, webcams_path, webcams_rel_path, slideshow_width, slideshow_height, metadata
        )

        if not self.keep_tmp_files:
            self.remove_tmp_dir()
        else:
            Log.warning(f'Temporary directory will not be deleted: {self.tmp_dir}')
        Log.success(f'All done! Final video: {result_path}')

    def parse_deskshare_data(self, recording_duration) -> List[Deskshare]:
        result_list = []
        loaded_deskshare = self.load_xml('deskshare.xml', False)
        if loaded_deskshare is None:
            return result_list
        deskshares = loaded_deskshare.findall("./event[@start_timestamp]")
        for deskshare in deskshares:
            deskshare_in = float(deskshare.get('start_timestamp'))
            deskshare_out = float(deskshare.get('stop_timestamp'))
            deskshare_width = int(deskshare.get('video_width'))
            deskshare_height = int(deskshare.get('video_height'))
            if deskshare_in < recording_duration:
                result_list.append(
                    Deskshare(
                        start_timestamp=deskshare_in,
                        stop_timestamp=deskshare_out,
                        width=deskshare_width,
                        height=deskshare_height,
                    )
                )
        result_list = sorted(result_list, key=lambda item: item.start_timestamp)
        return result_list

    def get_slideshow_size(self, only_zooms: Dict[float, Frame], deskshare_path: str):
        widths = []
        heights = []
        if deskshare_path is not None:
            video_info = self.ffmpeg.get_video_infos(deskshare_path)
            widths.append(video_info.width)
            heights.append(video_info.height)

        for _, frame in only_zooms.items():
            action = frame.actions[0]
            widths.append(int(action.width))
            heights.append(int(action.height))

        if len(widths) == 0 or len(heights) == 0:
            return

        max_width = max(widths)
        max_height = max(heights)

        if max_width % 2:
            max_width += 1
        if max_height % 2:
            max_height += 1

        return max_width, max_height

    def create_frames(self, frames: Dict[float, Frame], only_zooms: Dict[float, Frame], partitions: List[Tuple]):
        Log.info('Start capturing frames...')
        Log.info(f'Output directory for frames is: {self.frames_dir}')
        Log.info('Initialization takes a few seconds...')
        # Setup a server for Chrome browser to access
        port, port_error = get_free_port()
        if port is None:
            Log.error(f'Error: Could not open a port for a local http server: {port_error}')
            Log.warning(
                'Please check your Antivirus, to allow bbb-dl to open a local port.'
                + ' This is needed so we can use chrome browser to generate the presentation frames.'
            )
            exit(3)

        simple_handler = partial(QuietRequestHandler, directory=self.tmp_dir)
        server = ThreadingHTTPServer(('127.0.0.1', port), simple_handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with Timer() as t:
            _ = asyncio.run(self.multi_capture_frames(f'http://localhost:{port}', frames, only_zooms, partitions))

        print()
        Log.info(f'Frames capturing is finished and took: {formatSeconds(t.duration)}.')

        server.shutdown()
        thread.join(timeout=10)

    async def display_capture_status(self, status_dict: Dict):
        spinner = cycle('/|\\-')
        print()
        while (status_dict.get('done', 0)) < status_dict.get('total', 0):
            print(
                "\r\033[KDone:"
                + f" {status_dict.get('done', 0):05} / {status_dict.get('total', 0):05} Frames"
                + f" | {status_dict.get('done_partitions', 0):03} / {status_dict.get('total_partitions', 0):03} Parts"
                + f" {next(spinner)}",
                end='',
            )
            await asyncio.sleep(1)

    async def _real_multi_capture_frames(
        self,
        server_url: str,
        frames: Dict[float, Frame],
        only_zooms: Dict[float, Frame],
        partitions: List[Tuple],
        status_dict: Dict,
    ):
        semaphore = asyncio.Semaphore(self.max_parallel_chromes)
        try:
            await asyncio.gather(
                *[
                    self.capture_frames(server_url, frames, only_zooms, partition, semaphore, status_dict)
                    for partition in partitions
                ]
            )
        except Exception:
            traceback.print_exc()
            Log.error(
                'Unexpected Error! Press Ctr+C to exit.'
                + ' Please try to set a low number of threads with `--max-parallel-chromes`.'
                + ' You can contact bbb-dl support.'
            )
            exit(-1)

    async def multi_capture_frames(
        self,
        server_url: str,
        frames: Dict[float, Frame],
        only_zooms: Dict[float, Frame],
        partitions: List[Tuple],
    ):
        status_dict = {
            'done': 0,
            'total': len(frames),
            'done_partitions': 0,
            'total_partitions': len(partitions),
        }
        await asyncio.wait(
            [
                asyncio.create_task(
                    self._real_multi_capture_frames(server_url, frames, only_zooms, partitions, status_dict)
                ),
                asyncio.create_task(self.display_capture_status(status_dict)),
            ],
        )

    async def capture_frames(
        self,
        server_url: str,
        frames: Dict[float, Frame],
        only_zooms: Dict[float, Frame],
        partition: Tuple,
        semaphore: asyncio.Semaphore,
        status_dict: Dict,
    ):
        async with semaphore, async_playwright() as p:
            first_timestamp = partition[0]
            last_timestamp = partition[1]
            partition_already_done = True
            total_frames_in_partition = 0
            for timestamp, frame in frames.items():
                if timestamp > last_timestamp:
                    break
                if timestamp < first_timestamp:
                    continue
                if not os.path.isfile(frame.capture_path):
                    partition_already_done = False
                    break
                total_frames_in_partition += 1

            if partition_already_done:
                status_dict['done'] += total_frames_in_partition
                print()
                Log.info(f'Partition already finished: {formatSeconds(partition[0])} to {formatSeconds(partition[1])}')
                status_dict['done_partitions'] += 1
                return

            browser = await p.chromium.launch()
            page = await browser.new_page()

            await page.goto(server_url + '/shapes.svg')
            await page.wait_for_selector('#svgfile')
            # add cursor
            await page.evaluate(
                """() => { 
                let el = document.querySelector('#svgfile')
                el.style.width = '100%'
                el.style.height = '100%'
                el.innerHTML = el.innerHTML + '<circle id="cursor" cx="9999" cy="9999" r="5" stroke="red" stroke-width="3" fill="red" style="visibility:hidden" />'
            }"""
            )
            current_view_box = None
            for timestamp, frame in only_zooms.items():
                if timestamp > first_timestamp:
                    continue
                # We only set one initial ViewBox, the first we find before the partition
                current_view_box = frame.actions[0]
                await self.set_view_box(page, current_view_box)
                break
            for timestamp, frame in frames.items():
                if timestamp > last_timestamp:
                    break
                if timestamp < first_timestamp:
                    continue
                for action in frame.actions:
                    if action.action_type == ActionType.show_image:
                        await self.show_image(page, action)
                        await self.show_cursor(page)
                    elif action.action_type == ActionType.hide_image:
                        await self.hide_image(page, action)
                        await self.hide_cursor(page)
                    elif action.action_type == ActionType.show_drawing:
                        await self.show_drawing(page, action)
                    elif action.action_type == ActionType.hide_drawing:
                        await self.hide_drawing(page, action)
                    elif action.action_type == ActionType.set_view_box:
                        current_view_box = action
                        await self.set_view_box(page, action)
                    elif action.action_type == ActionType.move_cursor:
                        if current_view_box is None:
                            Log.warning('No ViewBox, cursor position unclear!')
                            await self.move_cursor(page, -1, -1)
                        if current_view_box is not None:
                            if action.x == -1 and action.y == -1:
                                await self.move_cursor(page, -1, -1)
                            else:
                                await self.move_cursor(
                                    page,
                                    current_view_box.x + (action.x * current_view_box.width),
                                    current_view_box.y + (action.y * current_view_box.height),
                                )

                if not os.path.isfile(frame.capture_path):
                    await page.screenshot(path=frame.capture_path)
                status_dict['done'] += 1

            await browser.close()
            print()
            Log.info(f'Partition finished: {formatSeconds(partition[0])} to {formatSeconds(partition[1])}')
            status_dict['done_partitions'] += 1

    async def show_image(self, page: Page, action: Action):
        await page.evaluate(
            """([id, canvas_num]) => {
                document.querySelector('#' + id).style.visibility = 'visible'
                const canvas = document.querySelector('#canvas' + canvas_num)
                if (canvas) canvas.setAttribute('display', 'block')
            }""",
            [action.element_id, action.value],
        )

    async def hide_image(self, page: Page, action: Action):
        await page.evaluate(
            """([id, canvas_num]) => {
                document.querySelector('#' + id).style.visibility = 'hidden'
                const canvas = document.querySelector('#canvas' + canvas_num)
                if (canvas) canvas.setAttribute('display', 'none')
            }""",
            [action.element_id, action.value],
        )

    async def show_drawing(self, page: Page, action: Action):
        await page.evaluate(
            """([id, shape_id]) => {
                document.querySelectorAll('[shape=' + shape_id + ']').forEach( element => {
                    element.style.visibility = 'hidden'
                })
                document.querySelector('#' + id).style.visibility = 'visible'
            }""",
            [action.element_id, action.value],
        )

    async def hide_drawing(self, page: Page, action: Action):
        await page.evaluate(
            """(id) => {
                document.querySelector('#' + id).style.display = 'none'
            }""",
            action.element_id,
        )  # Maybe use visibility?

    async def set_view_box(self, page: Page, action: Action):
        await page.set_viewport_size({"width": int(action.width), "height": int(action.height)})
        await page.evaluate(
            """(viewBox) => {
                document.querySelector('#svgfile').setAttribute('viewBox', viewBox)
            }""",
            action.value,
        )

    async def show_cursor(self, page: Page):
        await page.evaluate(
            """() => {
                document.querySelector('#cursor').style.visibility = 'visible'
            }""",
        )

    async def hide_cursor(self, page: Page):
        await page.evaluate(
            """() => {
                document.querySelector('#cursor').style.visibility = 'hidden'
            }""",
        )

    async def move_cursor(self, page: Page, x: float, y: float):
        await page.evaluate(
            """([x,y]) => {
                document.querySelector('#cursor').setAttribute('cx', x)
                document.querySelector('#cursor').setAttribute('cy', y)
            }""",
            [x, y],
        )

    def get_all_image_urls(self, loaded_shapes: Element) -> List[str]:
        image_urls = []
        shapes_images = loaded_shapes.findall(_s(".//svg:image"))
        for image in shapes_images:
            image_rel_path = image.get(_x('xlink:href'))
            if image_rel_path not in image_urls:
                image_urls.append(image_rel_path)
        return image_urls

    def parse_metadata(self) -> Metadata:
        loaded_metadata = self.load_xml('metadata.xml')

        date = xpath_text(loaded_metadata, 'start_time')  # date on that the recording took place
        date_formatted = datetime.fromtimestamp(int(date) / 1000).strftime('%Y-%m-%dT%H-%M-%S')
        duration = float(xpath_text(loaded_metadata, './playback/duration')) / 1000.0  # in seconds
        title = xpath_text(loaded_metadata, './meta/meetingName')

        Log.info(f"Recording title: {title}")
        Log.info(f"Recording date: {date_formatted}")
        Log.info(f"Recording duration: {formatSeconds(duration)}")

        bbb_version = None
        if self.verbose:
            try:
                bbb_origin_version = xpath_text(loaded_metadata, './meta/bbb-origin-version')
                if bbb_origin_version is not None:
                    bbb_version = bbb_origin_version.split(' ')[0]
                    Log.info(f"BBB version: {bbb_version}")
            except IndexError:
                pass

        return Metadata(date, date_formatted, duration, title, bbb_version)

    def parse_slides_data(self, loaded_shapes: Element, metadata: Metadata) -> Dict[float, Frame]:
        frames = {}

        partitions = self.parse_slide_partitions(loaded_shapes, metadata.duration)
        self.parse_images(loaded_shapes, frames, metadata.duration)
        if not self.skip_annotations_opt:
            self.parse_drawings(loaded_shapes, frames, metadata.duration)

        only_zooms = {}
        loaded_zooms = self.load_xml('panzooms.xml', False)
        if loaded_zooms is not None:
            self.parse_zooms(loaded_zooms, frames, only_zooms, metadata.duration)

        if not self.skip_cursor_opt:
            loaded_cursors = self.load_xml('cursor.xml', False)
            if loaded_cursors is not None:
                self.parse_cursors(loaded_cursors, frames, metadata.duration)

        frames = dict(sorted(frames.items(), key=lambda item: item[0]))
        only_zooms = dict(sorted(only_zooms.items(), key=lambda item: item[0], reverse=True))

        return frames, only_zooms, partitions

    def get_frame_by_timestamp(self, frames: Dict[float, Frame], timestamp: float):
        if timestamp not in frames:
            capture_rel_path = PT.get_in_dir('frames', f'{timestamp}.png')
            capture_path = PT.get_in_dir(self.frames_dir, f'{timestamp}.png')
            frames[timestamp] = Frame(timestamp, [], capture_rel_path, capture_path)
        return frames[timestamp]

    def parse_slide_partitions(self, loaded_shapes: Element, recording_duration: float) -> List[Tuple]:
        partitions = []
        slides = loaded_shapes.findall(_s("./svg:image[@class='slide']"))
        partition_start = None
        last_slide_idx = len(slides) - 1
        for idx, image in enumerate(slides):
            image_id = image.get('id')
            image_in = float(image.get('in'))
            image_out = float(image.get('out'))
            got_annotations = loaded_shapes.find(_s(f"./svg:g[@image='{image_id}']")) is not None
            if partition_start is None:
                partition_start = image_in
            if idx == last_slide_idx or got_annotations:
                partitions.append((partition_start, image_out))
                partition_start = None
        return partitions

    def parse_images(self, loaded_shapes: Element, frames: Dict[float, Frame], recording_duration: float):
        slides = loaded_shapes.findall(_s("./svg:image[@class='slide']"))
        for image in slides:
            image_id = image.get('id')
            image_id_value = self.NUMBER_RE.search(image_id).group()
            image_in = float(image.get('in'))
            image_out = float(image.get('out'))
            image_width = int(float(image.get('width')))
            image_height = int(float(image.get('height')))
            if image_in < recording_duration:
                self.get_frame_by_timestamp(frames, image_in).actions.append(
                    Action(
                        action_type=ActionType.show_image,
                        element_id=image_id,
                        value=image_id_value,
                        width=image_width,
                        height=image_height,
                    )
                )
                self.get_frame_by_timestamp(frames, min(recording_duration, image_out)).actions.append(
                    Action(
                        action_type=ActionType.hide_image,
                        element_id=image_id,
                        value=image_id_value,
                    )
                )

    def parse_drawings(self, loaded_shapes: Element, frames: Dict[float, Frame], recording_duration: float):
        drawings = loaded_shapes.findall(_s(".//svg:g[@timestamp]"))
        for drawing in drawings:
            drawing_id = drawing.get('id')
            drawing_shape_value = drawing.get('shape')
            drawing_in = float(drawing.get('timestamp'))
            drawing_out = float(drawing.get('undo'))
            if drawing_in < recording_duration:
                self.get_frame_by_timestamp(frames, drawing_in).actions.append(
                    Action(
                        action_type=ActionType.show_drawing,
                        element_id=drawing_id,
                        value=drawing_shape_value,
                    )
                )
                if drawing_out != -1:
                    self.get_frame_by_timestamp(frames, min(recording_duration, drawing_out)).actions.append(
                        Action(
                            action_type=ActionType.hide_drawing,
                            element_id=drawing_id,
                        )
                    )

    def parse_zooms(
        self,
        loaded_zooms: Element,
        frames: Dict[float, Frame],
        only_zooms: Dict[float, Frame],
        recording_duration: float,
    ):
        zooms = loaded_zooms.findall("./event[@timestamp]")
        for zoom in zooms:
            zoom_in = float(zoom.get('timestamp'))
            zoom_value = zoom.find('viewBox').text
            zoom_value_split = zoom_value.split(' ')  # min-x min-y width height
            zoom_x = float(zoom_value_split[0])
            zoom_y = float(zoom_value_split[1])
            zoom_width = float(zoom_value_split[2])
            zoom_height = float(zoom_value_split[3])
            if zoom_in < recording_duration:
                zoom_action = Action(
                    action_type=ActionType.set_view_box,
                    value=zoom_value,
                    x=zoom_x,
                    y=zoom_y,
                    width=zoom_width,
                    height=zoom_height,
                )
                self.get_frame_by_timestamp(frames, zoom_in).actions.append(zoom_action)
                self.get_frame_by_timestamp(only_zooms, zoom_in).actions.append(zoom_action)

    def parse_cursors(self, loaded_cursors: Element, frames: Dict[float, Frame], recording_duration: float):
        cursors = loaded_cursors.findall("./event[@timestamp]")
        for cursor in cursors:
            cursor_in = float(cursor.get('timestamp'))
            cursor_value_text = cursor.find('cursor').text.split(' ')
            cursor_x = float(cursor_value_text[0])
            cursor_y = float(cursor_value_text[1])
            cursor_value = (float(cursor_value_text[0]), float(cursor_value_text[1]))
            if cursor_in < recording_duration:
                self.get_frame_by_timestamp(frames, cursor_in).actions.append(
                    Action(
                        action_type=ActionType.move_cursor,
                        x=cursor_x,
                        y=cursor_y,
                        value=cursor_value,
                    )
                )

    def get_output_file_path(self, metadata: Metadata):
        if self.filename is not None:
            return str(Path(self.output_dir) / PT.to_valid_name(self.filename))
        else:
            return str(
                Path(self.output_dir) / PT.to_valid_name(metadata.date_formatted + '_' + metadata.title + '.mp4')
            )

    def get_output_dir(
        self,
        output_dir: str,
    ):
        return self.check_directory(output_dir, os.getcwd(), 'output', '--output-dir')

    def get_working_dir(
        self,
        working_dir: str,
    ):
        return self.check_directory(working_dir, PT.get_project_data_directory(), 'temporary', '--working-dir')

    def check_directory(self, path: str, default_path: str, file_type: str, option_name: str):
        if path is None:
            path = default_path
        else:
            path = PT.sanitize_path(path)

        path = PT.get_abs_path(path)
        try:
            PT.make_dirs(path)
        except (OSError, IOError) as err:
            Log.error(f'Error: Unable to create directory "{path}" for {file_type} files: {str(err)}')
            Log.warning(
                f'You can choose an alternative directory for the {file_type} files with the {option_name} option.'
            )
            exit(-2)

        if not os.access(path, os.R_OK) or not os.access(path, os.W_OK):
            Log.error(f'Error: Unable to read or write in the directory for {file_type} files {path}')
            Log.warning(
                f'You can choose an alternative directory for the {file_type} files with the {option_name} option.'
            )
            exit(-3)
        return path

    def get_frames_dir(self):
        frames_dir = PT.get_in_dir(self.tmp_dir, 'frames')
        try:
            PT.make_dirs(frames_dir)
        except (OSError, IOError) as err:
            Log.error(f'Error: Unable to create directory "{frames_dir}" for generated frames: {str(err)}')
            exit(-7)

        return frames_dir

    def get_tmp_dir(self, video_id):
        # We use a shorted version of the video id as name for the temporary directory
        short_video_id = hashlib.md5(video_id.encode(encoding='utf-8')).hexdigest()

        tmp_dir = PT.get_in_dir(self.working_dir, short_video_id)
        try:
            PT.make_dirs(tmp_dir)
        except (OSError, IOError) as err:
            Log.error(f'Error: Unable to create directory "{tmp_dir}" for temporary files: {str(err)}')
            exit(-5)

        return tmp_dir

    def remove_tmp_dir(self):
        Log.info("Cleanup")
        try:
            if os.path.exists(self.tmp_dir):
                shutil.rmtree(self.tmp_dir)
        except (OSError, IOError) as err:
            Log.error(f'Error: Unable to remove directory "{self.tmp_dir}" for temporary files: {str(err)}')
            exit(-6)

    def get_bbb_link(self, rel_file_path: str):
        assert not rel_file_path.startswith('/') and not rel_file_path.startswith('\\')
        return self.presentation_base_url + '/' + rel_file_path

    async def readexactly(self, steam, n):
        if steam._exception is not None:
            raise steam._exception

        blocks = []
        while n > 0:
            block = await steam.read(n)
            if not block:
                break
            blocks.append(block)
            n -= len(block)

        return b''.join(blocks)

    async def get_can_continue_on_fail(self, url, session):
        try:
            headers = self.headers.copy()
            headers['Range'] = 'bytes=0-4'
            resp = await session.request("GET", url, headers=headers)
            return resp.headers.get('Content-Range') is not None and resp.status == 206
        except Exception as err:
            if self.verbose:
                Log.debug(f"Failed to check if download can be continued on fail: {err}")
        return False

    async def batch_download_from_bbb(self, dl_jobs: List[str], is_essential: bool = True) -> List[bool]:
        """
        @param dl_jobs: List of rel_file_path
        @param is_essential: Applied to all jobs
        """
        semaphore = asyncio.Semaphore(self.max_parallel_dl)
        dl_results = await asyncio.gather(
            *[self.download_from_bbb(dl_job, is_essential, semaphore) for dl_job in dl_jobs]
        )
        if is_essential:
            for idx, downloaded in enumerate(dl_results):
                if not downloaded:
                    Log.error(f'Error: {dl_jobs[idx]} is essential. Abort! Please try again later!')
                    exit(1)
        return dl_results

    async def download_from_bbb(
        self,
        rel_file_path: str,
        is_essential: bool,
        semaphore: asyncio.Semaphore,
        conn_timeout: int = 10,
        read_timeout: int = 1800,
    ) -> bool:
        """Returns True if the file was successfully downloaded or exists"""
        local_path = PT.get_in_dir(self.tmp_dir, rel_file_path)
        if os.path.exists(local_path):
            # Warning: We do not check if the file is complete
            Log.info(f'{rel_file_path} is already present')
            return True
        else:
            PT.make_base_dir(local_path)
            dl_url = self.get_bbb_link(rel_file_path)
            if self.verbose:
                Log.info(f'Downloading {rel_file_path} from: {dl_url}')
            else:
                Log.info(f'Downloading {rel_file_path}...')

            received = 0
            total = 0
            tries_num = 0
            file_obj = None
            can_continue_on_fail = False
            headers = self.headers.copy()
            finished_successfully = False
            async with semaphore, aiohttp.ClientSession(
                conn_timeout=conn_timeout, read_timeout=read_timeout
            ) as session:
                while tries_num < self.max_dl_retries:
                    try:
                        if tries_num > 0 and can_continue_on_fail:
                            headers["Range"] = f"bytes={received}-"
                        ssl_param = False if self.no_check_certificate else None
                        async with session.request(
                            "GET", dl_url, headers=headers, raise_for_status=True, ssl=ssl_param
                        ) as resp:

                            # Download the file.
                            total = int(resp.headers.get("Content-Length", 0))
                            content_range = resp.headers.get("Content-Range", "")  # Example: bytes 200-1000/67589

                            if resp.status not in [200, 206]:
                                if self.verbose:
                                    Log.debug(f"Warning {rel_file_path} got status {resp.status}")

                            if tries_num > 0 and can_continue_on_fail and not content_range and resp.status != 206:
                                raise ClientError(
                                    f"Server did not response for {rel_file_path} with requested range data"
                                )
                            file_obj = file_obj or await aiofiles.open(local_path, "wb")
                            chunk = await self.readexactly(resp.content, 1024000)
                            chunk_idx = 0
                            while chunk:
                                received += len(chunk)
                                if chunk_idx % 10 == 0:
                                    Log.info(f"{rel_file_path} got {format_bytes(received)} / {format_bytes(total)}")
                                await file_obj.write(chunk)
                                chunk = await self.readexactly(resp.content, 1024000)
                                chunk_idx += 1

                        if self.verbose:
                            Log.success(f'Downloaded {rel_file_path} to: {local_path}')
                        else:
                            Log.success(f'Successfully downloaded {rel_file_path}')

                        finished_successfully = True
                        break

                    except (ClientError, OSError, ValueError) as err:
                        if tries_num == 0:
                            can_continue_on_fail = await self.get_can_continue_on_fail(dl_url, session)
                        if not can_continue_on_fail:
                            # Clean up failed file because we can not recover
                            if file_obj is not None:
                                file_obj.close()
                            if os.path.exists(local_path):
                                os.unlink(local_path)

                        if isinstance(err, ClientResponseError) and err.status == 404 and not is_essential:
                            Log.info(f'{rel_file_path} could not be downloaded: {err.status} {err.message}')
                            if self.verbose:
                                Log.info(f'Error: {str(err)}')
                            break

                        if self.verbose:
                            Log.warning(
                                f'(Try {tries_num} of {self.max_dl_retries})'
                                + f' Unable to download "{rel_file_path}": {str(err)}'
                            )
                        tries_num += 1

            if file_obj is not None:
                file_obj.close()
            if not finished_successfully:
                return False
            return True

    def load_xml(self, rel_file_path: str, is_essential: bool = True):
        local_path = PT.get_in_dir(self.tmp_dir, rel_file_path)
        if os.path.exists(local_path):
            try:
                tree_root = ElementTree.parse(local_path).getroot()
                return tree_root
            except ParseError as err:
                Log.error(f'Unable to parse XML file "{local_path}": {str(err)}')
                if is_essential:
                    Log.error('Error: This XML file is essential. Abort! Please try again later!')
                    exit(2)
                else:
                    return None
        else:
            if is_essential:
                Log.error(f'Error: Can not find {local_path}. This XML file is essential. Please try again later!')
                exit(2)
            else:
                return None

    def final_mux(
        self,
        slideshow_path: str,
        webcams_path: str,
        webcams_rel_path: str,
        slideshow_width: int,
        slideshow_height: int,
        metadata: Metadata,
    ):

        webcam_is_empty = False
        if not self.skip_webcam_opt and not self.skip_webcam_freeze_detection_opt:
            Log.info(f'Try to detect freeze in {webcams_rel_path}...')
            with Timer() as t:
                webcam_is_empty = asyncio.run(self.ffmpeg.freeze_detect(webcams_path))

            Log.info(f'Detection of freeze finished and took: {formatSeconds(t.duration)}')
            if webcam_is_empty:
                Log.yellow('Webcam is empty, webcam will not be added to the final presentation')

        Log.info("Mux final slideshow")
        result_path = self.get_output_file_path(metadata)
        if os.path.isfile(result_path):
            Log.warning("Final Slideshow already exists. Abort!")
            exit(0)

        with Timer() as t:
            if self.skip_webcam_opt or webcam_is_empty:
                asyncio.run(
                    self.ffmpeg.add_audio_to_slideshow(
                        slideshow_path,
                        webcams_path,
                        result_path,
                    )
                )
            else:
                asyncio.run(
                    self.ffmpeg.add_webcam_to_slideshow(
                        slideshow_path,
                        webcams_path,
                        slideshow_width,
                        slideshow_height,
                        result_path,
                    )
                )

        Log.info(f'Mux final slideshow finished and took: {formatSeconds(t.duration)}')
        return result_path

    def add_deskshare_to_slideshow(
        self,
        slideshow_path: str,
        deskshare_path: str,
        deskshare_events: List[Deskshare],
        width: int,
        height: int,
        metadata: Metadata,
    ):
        if deskshare_path is None or len(deskshare_events) == 0:
            return slideshow_path

        presentation_path = PT.get_in_dir(self.tmp_dir, 'presentation.mp4')
        if os.path.isfile(presentation_path):
            Log.warning('Slideshow with deskshare does already exist! Skipping rendering!')
            return presentation_path

        Log.info('Resizing screen share...')
        resized_deskshare_path = PT.get_in_dir(self.tmp_dir, 'deskshare.mp4')
        if os.path.isfile(resized_deskshare_path):
            Log.warning('Resized screen share does already exist! Skipping rendering!')
        else:
            with Timer() as t:
                asyncio.run(self.ffmpeg.resize_deskshare(deskshare_path, resized_deskshare_path, width, height))
            Log.info(f'Resizing screen share finished and took: {formatSeconds(t.duration)}')

        Log.info('Start adding screen share to slideshow...')
        deskshare_txt_path = PT.get_in_dir(self.tmp_dir, 'deskshare.txt')
        with open(deskshare_txt_path, 'w', encoding="utf-8") as concat_file:
            for idx, event in enumerate(deskshare_events):
                if idx == 0 and event.start_timestamp > 0:
                    # Adding beginning
                    # duration = math.floor(10 * (event.start_timestamp) + 0.5) / 10
                    concat_file.write("file 'slideshow.mp4'\n")
                    concat_file.write("inpoint 0.0\n")
                    concat_file.write(f"outpoint {event.start_timestamp}\n")
                    # concat_file.write(f"duration {duration}\n")
                elif idx > 0:
                    # Adding part between deskshare
                    # duration = (
                    #     math.floor(10 * (event.start_timestamp - deskshare_events[idx - 1].stop_timestamp) + 0.5) / 10
                    # )
                    concat_file.write("file 'slideshow.mp4'\n")
                    concat_file.write(f"inpoint {deskshare_events[idx - 1].stop_timestamp}\n")
                    concat_file.write(f"outpoint {event.start_timestamp}\n")
                    # concat_file.write(f"duration {duration}\n")

                # Adding deskshare
                # duration = math.floor(10 * (event.stop_timestamp - event.start_timestamp) + 0.5) / 10
                concat_file.write("file 'deskshare.mp4'\n")
                concat_file.write(f"inpoint {event.start_timestamp}\n")
                concat_file.write(f"outpoint {event.stop_timestamp}\n")
                # concat_file.write(f"duration {duration}\n")

                if idx == (len(deskshare_events) - 1) and event.stop_timestamp < metadata.duration:
                    # Adding finish
                    # duration = math.floor(10 * (metadata.duration - event.stop_timestamp) + 0.5) / 10
                    concat_file.write("file 'slideshow.mp4'\n")
                    concat_file.write(f"inpoint {event.stop_timestamp}\n")
                    concat_file.write(f"outpoint {metadata.duration}\n")
                    # concat_file.write(f"duration {duration}\n")

        with Timer() as t:
            asyncio.run(self.ffmpeg.add_deskshare_to_slideshow(deskshare_txt_path, presentation_path))
        Log.info(f'Adding screen share to slideshow finished and took: {formatSeconds(t.duration)}')
        return presentation_path

    def create_slideshow(self, frames: Dict[float, Frame], width: int, height: int):
        Log.info('Start creating slideshow...')
        slideshow_path = PT.get_in_dir(self.tmp_dir, 'slideshow.mp4')
        if os.path.isfile(slideshow_path):
            Log.warning('Slideshow does already exist! Skipping rendering!')
            return slideshow_path

        slideshow_txt_path = PT.get_in_dir(self.tmp_dir, 'slideshow.txt')
        with open(slideshow_txt_path, 'w', encoding="utf-8") as concat_file:
            timestamps = list(frames.keys())
            for idx in range(len(timestamps) - 1):
                duration = math.floor(10 * (timestamps[idx + 1] - timestamps[idx]) + 0.5) / 10
                concat_file.write(f"file '{frames[timestamps[idx]].capture_rel_path}'\n")
                concat_file.write(f"duration {duration}\n")

            # We use the second to last frame again, because the last frame is always empty.
            # concat_file.write(f"file {frames[timestamps[-2]].capture_rel_path}\n")

        with Timer() as t:
            asyncio.run(self.ffmpeg.create_slideshow(slideshow_txt_path, slideshow_path, width, height))
        Log.info(f'Creating slideshow finished and took: {formatSeconds(t.duration)}')
        return slideshow_path


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser(
        description=('Big Blue Button Downloader that downloads a BBB lesson as MP4 video')
    )

    parser.add_argument('URL', type=str, help='URL of a BBB lesson')

    parser.add_argument(
        '-sw',
        '--skip-webcam',
        action='store_true',
        help='Skip adding the webcam video as an overlay to the final video.'
        + ' This will reduce the time to generate the final video',
    )
    parser.add_argument(
        '-swfd',
        '--skip-webcam-freeze-detection',
        action='store_true',
        help='Skip detecting if the webcam video is completely empty.'
        + ' It is assumed the webcam recording is not empty. This will reduce the time to generate the final video',
    )

    parser.add_argument(
        '-sa',
        '--skip-annotations',
        action='store_true',
        help='Skip capturing the annotations of the professor. This will reduce the time to generate the final video',
    )

    parser.add_argument(
        '-sc',
        '--skip-cursor',
        action='store_true',
        help='Skip capturing the cursor of the professor. This will reduce the time to generate the final video',
    )

    parser.add_argument(
        '-bk',
        '--backup',
        action='store_true',
        help=(
            'Downloads all the content from the server and then stops. After using this option, you can run bbb-dl'
            + ' again to create the video based on the saved files'
        ),
    )
    parser.add_argument(
        '-kt',
        '--keep-tmp-files',
        action='store_true',
        help=(
            'Keep the temporary files after finish. In case of an error bbb-dl will reuse the already generated files'
        ),
    )

    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help=('Print more verbose debug information'),
    )

    parser.add_argument(
        '--ffmpeg-location',
        type=str,
        default=None,
        help='Optional path to the directory in that your installed ffmpeg executable is located (Use it if ffmpeg is not located in your system PATH)',
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
        '--output-dir',
        type=str,
        help='Optional output directory for final video',
    )

    parser.add_argument(
        '-wd',
        '--working-dir',
        type=str,
        help='Optional output directory for all temporary directories/files',
    )

    parser.add_argument(
        '-mpc',
        '--max-parallel-chromes',
        type=int,
        default=10,
        help='Maximum number of chrome browser instances used to generate frames',
    )

    parser.add_argument(
        '-fw',
        '--force-width',
        type=int,
        default=None,
        help='Force width on final output. (e.g. 1280) This can reduce the time to generate the final video',
    )

    parser.add_argument(
        '-fh',
        '--force-height',
        type=int,
        default=None,
        help='Force height on final output. (e.g. 720) This can reduce the time to generate the final video',
    )

    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    parser = get_parser()
    args = parser.parse_args(args)

    with Timer() as final_t:
        BBBDL(
            args.URL,
            args.filename,
            args.output_dir,
            args.verbose,
            args.no_check_certificate,
            args.encoder,
            args.audiocodec,
            args.skip_webcam,
            args.skip_webcam_freeze_detection,
            args.skip_annotations,
            args.skip_cursor,
            args.keep_tmp_files,
            args.ffmpeg_location,
            args.working_dir,
            args.backup,
            args.max_parallel_chromes,
            args.force_width,
            args.force_height,
        ).run()
    Log.info(f'BBB-DL finished and took: {formatSeconds(final_t.duration)}')
