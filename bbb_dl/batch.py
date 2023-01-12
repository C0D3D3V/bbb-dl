import argparse
import os
import subprocess

from subprocess import CalledProcessError
from typing import List

from colorama import just_fix_windows_console

from bbb_dl.utils import (
    formatSeconds,
    Log,
    PathTools as PT,
    Timer,
)
from bbb_dl.version import __version__


class BatchProcessor:
    def __init__(
        self,
        dl_urls_file_path: str,
        bbb_dl_path: str,
        output_dir: str,
        verbose: bool,
        no_check_certificate: bool,
        encoder: str,
        audiocodec: str,
        audio_only: bool,
        skip_webcam: bool,
        skip_webcam_freeze_detection: bool,
        skip_annotations: bool,
        skip_cursor: bool,
        skip_zoom: bool,
        keep_tmp_files: bool,
        ffmpeg_location: str,
        working_dir: str,
        backup: bool,
        max_parallel_chromes: int,
        force_width: int,
        force_height: int,
        preset: str,
        crf: int,
    ):
        self.bbb_dl_path = bbb_dl_path
        option_list = []
        self.add_bool_option(option_list, '--audio-only', audio_only)
        self.add_bool_option(option_list, '--skip-webcam', skip_webcam)
        self.add_bool_option(option_list, '--skip-webcam-freeze-detection', skip_webcam_freeze_detection)
        self.add_bool_option(option_list, '--skip-annotations', skip_annotations)
        self.add_bool_option(option_list, '--skip-cursor', skip_cursor)
        self.add_bool_option(option_list, '--skip-zoom', skip_zoom)
        self.add_bool_option(option_list, '--backup', backup)
        self.add_bool_option(option_list, '--verbose', verbose)
        self.add_bool_option(option_list, '--no-check-certificate', no_check_certificate)
        self.add_bool_option(option_list, '--keep-tmp-files', keep_tmp_files)
        self.add_value_option(option_list, '--ffmpeg-location', ffmpeg_location)
        self.add_value_option(option_list, '--working-dir', working_dir)
        self.add_value_option(option_list, '--output-dir', output_dir)
        self.add_value_option(option_list, '--encoder', encoder)
        self.add_value_option(option_list, '--audiocodec', audiocodec)
        self.add_value_option(option_list, '--max-parallel-chromes', max_parallel_chromes)
        self.add_value_option(option_list, '--force-width', force_width)
        self.add_value_option(option_list, '--force-height', force_height)
        self.add_value_option(option_list, '--preset', preset)
        self.add_value_option(option_list, '--crf', crf)
        self.default_option_list = option_list
        self.dl_urls_file_path = dl_urls_file_path

        self.output_dir_path = self.get_output_dir(output_dir)

    def get_output_dir(
        self,
        output_dir: str,
    ):
        return self.check_directory(output_dir, os.getcwd(), 'output', '--output-dir')

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

    def add_value_option(self, option_list, option_name, option):
        if option is not None:
            if option_name not in option_list:
                option_list.append(option_name)
                option_list.append(str(option))

    def add_bool_option(self, option_list, option_name, option):
        if option:
            if option_name not in option_list:
                option_list.append(option_name)

    def add_url_to_file(self, url: str, file_name: str):
        file_path = PT.get_in_dir(self.output_dir_path, file_name)
        with open(file_path, mode='a+', encoding='utf-8') as fh:
            fh.write(f"{url}\n")

    def run(self):
        if not os.path.isfile(self.dl_urls_file_path):
            Log.error(f'Can not find URLs file: {self.dl_urls_file_path}')
            exit(-1)

        URL_List = []
        try:
            with open(self.dl_urls_file_path, mode='r', encoding='utf-8') as fh:
                URL_List = [line.strip() for line in fh.readlines()]
        except OSError as err:
            Log.error(f'Error: {str(err)}')
            exit(-1)

        for url in URL_List:
            successful = self.execute_bbb_dl(url)
            if successful:
                self.add_url_to_file(url, 'successful.txt')
            else:
                self.add_url_to_file(url, 'failed.txt')

    def build_arguments(self, dl_url: str) -> List[str]:
        arguments = [self.bbb_dl_path, dl_url]
        arguments.extend(self.default_option_list)
        return arguments

    def execute_bbb_dl(self, url: str) -> bool:
        arguments = self.build_arguments(url)

        try:
            result = subprocess.run(
                arguments,
                check=True,
            )
        except CalledProcessError as err:
            print(f"BBB-DL exited with Error: {err}")
            return False

        if result.returncode == 0:
            Log.success('Completed successfully')
            return True
        else:
            Log.error(f'BBB-DL failed with Error: {result.returncode}')
            return False


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser(description=('Big Blue Button Batch Downloader'))

    parser.add_argument(
        'URLs',
        type=str,
        help='Path to a text file containing URLs of BBB lessons, one line per URL',
    )

    parser.add_argument(
        '-ao',
        '--audio-only',
        action='store_true',
        help='Extract only the audio from the presentations, do not generate videos.',
    )

    parser.add_argument(
        '-bp',
        '--bbb-dl-path',
        type=str,
        default='bbb-dl',
        help='Path to bbb-dl. Use it if bbb-dl is not in your system PATH',
    )
    parser.add_argument(
        '-sw',
        '--skip-webcam',
        action='store_true',
        help='Skip adding the webcam video as an overlay to the final videos.',
    )
    parser.add_argument(
        '-swfd',
        '--skip-webcam-freeze-detection',
        action='store_true',
        help='Skip detecting if the webcam video is completely empty.'
        + ' It is assumed the webcam recordings are not empty.',
    )
    parser.add_argument(
        '-sa',
        '--skip-annotations',
        action='store_true',
        help='Skip capturing the annotations of the professor',
    )
    parser.add_argument(
        '-sc',
        '--skip-cursor',
        action='store_true',
        help='Skip capturing the cursor of the professor',
    )
    parser.add_argument(
        '-sz',
        '--skip-zoom',
        action='store_true',
        help=(
            'Skip zooming into the presentations. All presentation slides are rendered in full size,'
            + ' which may result in sharper output videos. However, consequently also to smaller font.'
        ),
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
        help=(
            'Optional path to the directory in that your installed ffmpeg executable is located'
            + ' (Use it if ffmpeg is not located in your system PATH)'
        ),
    )

    parser.add_argument(
        '-ncc',
        '--no-check-certificate',
        action='store_true',
        help=('Suppress HTTPS certificate validation'),
    )

    parser.add_argument(
        '--version',
        action='version',
        version='bbb-dl ' + __version__,
        help='Print program version and exit',
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
        '--preset',
        dest='preset',
        type=str,
        default='fast',
        help='Optional preset to pass to ffmpeg (default fast, a preset that can be used with all encoders)',
    )
    parser.add_argument(
        '--crf',
        dest='crf',
        type=int,
        default=23,
        help=(
            'Optional crf to pass to ffmpeg'
            + ' (default 23, lower crf (e.g 22) usually means larger file size and better video quality)'
        ),
    )

    parser.add_argument(
        '-od',
        '--output-dir',
        type=str,
        default=None,
        help='Optional output directory for final videos',
    )

    parser.add_argument(
        '-wd',
        '--working-dir',
        type=str,
        default=None,
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
        help='Force width on final outputs',
    )

    parser.add_argument(
        '-fh',
        '--force-height',
        type=int,
        default=None,
        help='Force height on final outputs',
    )

    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    just_fix_windows_console()
    parser = get_parser()
    args = parser.parse_args(args)

    with Timer() as final_t:
        BatchProcessor(
            args.URLs,
            args.bbb_dl_path,
            args.output_dir,
            args.verbose,
            args.no_check_certificate,
            args.encoder,
            args.audiocodec,
            args.audio_only,
            args.skip_webcam,
            args.skip_webcam_freeze_detection,
            args.skip_annotations,
            args.skip_cursor,
            args.skip_zoom,
            args.keep_tmp_files,
            args.ffmpeg_location,
            args.working_dir,
            args.backup,
            args.max_parallel_chromes,
            args.force_width,
            args.force_height,
            args.preset,
            args.crf,
        ).run()
    Log.info(f'BBB-DL finished and took: {formatSeconds(final_t.duration)}')
