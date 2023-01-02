import collections
import functools
import html
import itertools
import math
import os
import re
import socket
import sys
import time
import unicodedata

from contextlib import closing
from http.server import SimpleHTTPRequestHandler
from pathlib import Path


class QuietRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def get_free_port():
    """
    Ask the system for a free port.
    In case of error return error message.
    :return: {Tuple}
    """
    port = None
    error = {}
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as soc:
        try:
            soc.bind(('127.0.0.1', 0))
            sock_name = soc.getsockname()
            if isinstance(sock_name, tuple) and len(sock_name) == 2:
                port = sock_name[1]
        except socket.error as e:
            error = {'errno': e.errno, 'msg': str(e)}

        return port, error


def check_verbose() -> bool:
    """Return if the verbose mode is active"""
    return '-v' in sys.argv or '--verbose' in sys.argv


def check_debug() -> bool:
    """Return if the debugger is currently active"""
    return 'pydevd' in sys.modules or (hasattr(sys, 'gettrace') and sys.gettrace() is not None)


_timetuple = collections.namedtuple('Time', ('hours', 'minutes', 'seconds', 'milliseconds'))


def float_or_none(v, scale=1, invscale=1, default=None):
    if v is None:
        return default
    try:
        return float(v) * invscale / scale
    except (ValueError, TypeError):
        return default


def format_decimal_suffix(num, fmt='%d%s', *, factor=1000):
    """Formats numbers with decimal sufixes like K, M, etc"""
    num, factor = float_or_none(num), float(factor)
    if num is None or num < 0:
        return None
    POSSIBLE_SUFFIXES = 'kMGTPEZY'
    exponent = 0 if num == 0 else min(int(math.log(num, factor)), len(POSSIBLE_SUFFIXES))
    suffix = ['', *POSSIBLE_SUFFIXES][exponent]
    if factor == 1024:
        suffix = {'k': 'Ki', '': ''}.get(suffix, f'{suffix}i')
    converted = num / (factor**exponent)
    return fmt % (converted, suffix)


def format_bytes(bytes):
    return format_decimal_suffix(bytes, '%.2f%sB', factor=1024) or 'N/A'


def append_get_idx(list_obj, item):
    idx = len(list_obj)
    list_obj.append(item)
    return idx


def timetuple_from_msec(msec):
    secs, msec = divmod(msec, 1000)
    mins, secs = divmod(secs, 60)
    hrs, mins = divmod(mins, 60)
    return _timetuple(hrs, mins, secs, msec)


def formatSeconds(secs, delim=':', msec=False):
    time = timetuple_from_msec(secs * 1000)
    if time.hours:
        ret = '%d%s%02d%s%02d' % (time.hours, delim, time.minutes, delim, time.seconds)
    elif time.minutes:
        ret = '%d%s%02d' % (time.minutes, delim, time.seconds)
    else:
        ret = '%d' % time.seconds
    return '%s.%03d' % (ret, time.milliseconds) if msec else ret


def xpath_text(node, xpath):
    n = node.find(xpath)
    if n is None:
        return n
    if n.text is None:
        return None
    return n.text


def xpath_with_ns(path, ns_map):
    components = [c.split(':') for c in path.split('/')]
    replaced = []
    for c in components:
        if len(c) == 1:
            replaced.append(c[0])
        else:
            ns, tag = c
            replaced.append('{%s}%s' % (ns_map[ns], tag))
    return '/'.join(replaced)


_s = functools.partial(
    xpath_with_ns,
    ns_map={'svg': 'http://www.w3.org/2000/svg'},
)
_x = functools.partial(
    xpath_with_ns,
    ns_map={
        # 'xmlns': 'http://www.w3.org/2000/svg',
        'xml': 'http://www.w3.org/XML/1998/namespace',
        'ttml': 'http://www.w3.org/ns/ttml',
        'tts': 'http://www.w3.org/ns/ttml#styling',
        'xlink': 'http://www.w3.org/1999/xlink',
    },
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
    def success_str(logString: str):
        return COLOR_SEQ % GREEN + logString + RESET_SEQ

    @staticmethod
    def warning_str(logString: str):
        return COLOR_SEQ % YELLOW + logString + RESET_SEQ

    @staticmethod
    def yellow_str(logString: str):
        return COLOR_SEQ % YELLOW + logString + RESET_SEQ

    @staticmethod
    def error_str(logString: str):
        return COLOR_SEQ % RED + logString + RESET_SEQ

    @staticmethod
    def debug_str(logString: str):
        return COLOR_SEQ % CYAN + logString + RESET_SEQ

    @staticmethod
    def blue_str(logString: str):
        return COLOR_SEQ % BLUE + logString + RESET_SEQ

    @staticmethod
    def magenta_str(logString: str):
        return COLOR_SEQ % MAGENTA + logString + RESET_SEQ

    @staticmethod
    def info(logString: str):
        print(Log.info_str(logString))

    @staticmethod
    def success(logString: str):
        print(Log.success_str(logString))

    @staticmethod
    def warning(logString: str):
        print(Log.warning_str(logString))

    @staticmethod
    def yellow(logString: str):
        print(Log.yellow_str(logString))

    @staticmethod
    def error(logString: str):
        print(Log.error_str(logString))

    @staticmethod
    def debug(logString: str):
        print(Log.debug_str(logString))

    @staticmethod
    def blue(logString: str):
        print(Log.blue_str(logString))

    @staticmethod
    def magenta(logString: str):
        print(Log.magenta_str(logString))


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


NO_DEFAULT = object()

# needed for sanitizing filenames in restricted mode
ACCENT_CHARS = dict(
    zip(
        'ÂÃÄÀÁÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖŐØŒÙÚÛÜŰÝÞßàáâãäåæçèéêëìíîïðñòóôõöőøœùúûüűýþÿ',
        itertools.chain(
            'AAAAAA',
            ['AE'],
            'CEEEEIIIIDNOOOOOOO',
            ['OE'],
            'UUUUUY',
            ['TH', 'ss'],
            'aaaaaa',
            ['ae'],
            'ceeeeiiiionooooooo',
            ['oe'],
            'uuuuuy',
            ['th'],
            'y',
        ),
    )
)


class PathTools:
    """A set of methods to create correct paths."""

    restricted_filenames = False

    @staticmethod
    def to_valid_name(name: str) -> str:
        """Filtering invalid characters in filenames and paths.

        Args:
            name (str): The string that will go through the filtering

        Returns:
            str: The filtered string, that can be used as a filename.
        """

        if name is None:
            return None

        name = html.unescape(name)

        name = name.replace('\n', ' ')
        name = name.replace('\r', ' ')
        name = name.replace('\t', ' ')
        name = name.replace('\xad', '')
        while '  ' in name:
            name = name.replace('  ', ' ')
        name = PathTools.sanitize_filename(name, PathTools.restricted_filenames)
        name = name.strip('. ')
        name = name.strip()

        return name

    @staticmethod
    def sanitize_filename(s, restricted=False, is_id=NO_DEFAULT):
        """Sanitizes a string so it could be used as part of a filename.
        @param restricted   Use a stricter subset of allowed characters
        @param is_id        Whether this is an ID that should be kept unchanged if possible.
                            If unset, yt-dlp's new sanitization rules are in effect
        """
        if s == '':
            return ''

        def replace_insane(char):
            if restricted and char in ACCENT_CHARS:
                return ACCENT_CHARS[char]
            elif not restricted and char == '\n':
                return '\0 '
            elif is_id is NO_DEFAULT and not restricted and char in '"*:<>?|/\\':
                # Replace with their full-width unicode counterparts
                return {'/': '\u29F8', '\\': '\u29f9'}.get(char, chr(ord(char) + 0xFEE0))
            elif char == '?' or ord(char) < 32 or ord(char) == 127:
                return ''
            elif char == '"':
                return '' if restricted else '\''
            elif char == ':':
                return '\0_\0-' if restricted else '\0 \0-'
            elif char in '\\/|*<>':
                return '\0_'
            if restricted and (char in '!&\'()[]{}$;`^,#' or char.isspace() or ord(char) > 127):
                return '\0_'
            return char

        if restricted and is_id is NO_DEFAULT:
            s = unicodedata.normalize('NFKC', s)
        s = re.sub(r'[0-9]+(?::[0-9]+)+', lambda m: m.group(0).replace(':', '_'), s)  # Handle timestamps
        result = ''.join(map(replace_insane, s))
        if is_id is NO_DEFAULT:
            result = re.sub(r'(\0.)(?:(?=\1)..)+', r'\1', result)  # Remove repeated substitute chars
            STRIP_RE = r'(?:\0.|[ _-])*'
            result = re.sub(f'^\0.{STRIP_RE}|{STRIP_RE}\0.$', '', result)  # Remove substitute chars from start/end
        result = result.replace('\0', '') or '_'

        if not is_id:
            while '__' in result:
                result = result.replace('__', '_')
            result = result.strip('_')
            # Common case of "Foreign band name - English song title"
            if restricted and result.startswith('-_'):
                result = result[2:]
            if result.startswith('-'):
                result = '_' + result[len('-') :]
            result = result.lstrip('.')
            if not result:
                result = '_'
        return result

    @staticmethod
    def remove_start(s, start):
        return s[len(start) :] if s is not None and s.startswith(start) else s

    @staticmethod
    def sanitize_path(path: str):
        """
        @param path: A path to sanitize.
        @return: A path where every part was sanitized using to_valid_name.
        """
        drive_or_unc, _ = os.path.splitdrive(path)
        norm_path = os.path.normpath(PathTools.remove_start(path, drive_or_unc)).split(os.path.sep)
        if drive_or_unc:
            norm_path.pop(0)

        sanitized_path = [
            path_part if path_part in ['.', '..'] else PathTools.to_valid_name(path_part) for path_part in norm_path
        ]

        if drive_or_unc:
            sanitized_path.insert(0, drive_or_unc + os.path.sep)
        return os.path.join(*sanitized_path)

    @staticmethod
    def get_abs_path(path: str):
        return str(Path(path).resolve())

    @staticmethod
    def get_in_dir(path: str, filename: str):
        return str(Path(path) / filename)

    @staticmethod
    def make_base_dir(path_to_file: str):
        Path(path_to_file).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_dirs(path_to_dir: str):
        Path(path_to_dir).mkdir(parents=True, exist_ok=True)

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
        data_dir = Path(PathTools.get_user_data_directory()) / "bbb-dl"
        if not data_dir.is_dir():
            data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)

    @staticmethod
    def get_feeds_directory():
        feeds_dir = Path(PathTools.get_project_data_directory()) / "feeds"
        if not feeds_dir.is_dir():
            feeds_dir.mkdir(parents=True, exist_ok=True)
        return str(feeds_dir)

    @staticmethod
    def get_unused_filename(destination: str, filename: str, file_extension: str):
        count = 0
        new_file_path = str(Path(destination) / f'{filename}_{count:04d}{file_extension}')
        while os.path.exists(new_file_path):
            count += 1
            new_file_path = str(Path(destination) / f'{filename}_{count:04d}{file_extension}')

        return new_file_path

    @staticmethod
    def get_path_of_new_feed_json(downloader_name: str):
        feeds_dir = PathTools.get_feeds_directory()
        return PathTools.get_unused_filename(feeds_dir, downloader_name, '.json')
