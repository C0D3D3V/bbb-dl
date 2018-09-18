__author__ = 'CreateWebinar.com'
__email__ = 'support@createwebinar.com'

from xml.dom import minidom
import sys
import os
import shutil
import zipfile
import ffmpeg
import re
import time

# Python script that produces downloadable material from a published bbb recording.

# Catch exception so that the script can be also called manually like: python download.py meetingId,
# in addition to being called from the bbb control scripts.
tmp = sys.argv[1].split('-')
try:
    if tmp[2] == 'presentation':
        meetingId = tmp[0] + '-' + tmp[1]
    else:
        sys.exit()
except IndexError:
    meetingId = sys.argv[1]

PATH = '/var/bigbluebutton/published/presentation/'
LOGS = '/var/log/bigbluebutton/download/'
source_dir = PATH + meetingId + "/"
temp_dir = source_dir + 'temp/'
target_dir = source_dir + 'download/'
audio_path = 'audio/'
events_file = 'shapes.svg'
LOGFILE = LOGS + meetingId + '.log'
ffmpeg.set_logfile(LOGFILE)
source_events = '/var/bigbluebutton/recording/raw/' + meetingId + '/events.xml'
# Deskshare
SOURCE_DESKSHARE = source_dir + 'deskshare/deskshare.webm'
TMP_DESKSHARE_FILE = temp_dir + 'deskshare.mp4'


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

    print >> sys.stderr, "-=create_slideshow=-"
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
            print >> sys.stderr, (0, i, t, duration)
            ffmpeg.trim_video_by_seconds(TMP_DESKSHARE_FILE, t, duration, out_file)
            ffmpeg.mp4_to_ts(out_file, out_ts_file)
        else:
            print >> sys.stderr, (1, i, t, duration)
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
        #print >> sys.stderr, "_rescale_presentation_"
        #print >> sys.stderr, (i, t)

        if i < 1 and '2.0.0' > bbb_version:
            continue

        #print >> sys.stderr, "_rescale_presentation_after_skip_"
        #print >> sys.stderr, (i, t)

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
    print >> sys.stderr, "dictionary"
    print >> sys.stderr, (dictionary)
    print >> sys.stderr, "length"
    print >> sys.stderr, (length)
    dims = get_different_presentations(dictionary)
    # debug
    print >> sys.stderr, "dims"
    print >> sys.stderr, (dims)
    check_presentation_dims(dictionary, dims, bbb_version)
    return dictionary, length, dims


def get_different_presentations(dictionary):
    times = dictionary.keys()
    print >> sys.stderr, "times"
    print >> sys.stderr, (times)
    presentations = []
    dims = {}
    for t in times:
        # ?if t < 1:
        # ?    continue

        name = dictionary[t].split("/")[7]
        # debug
        print >> sys.stderr, "name"
        print >> sys.stderr, (name)
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

    # Create symlink instead so that files are deleted
    # if not os.path.exists('/var/bigbluebutton/playback/presentation/download/' + filename):
    #    os.symlink(source_dir + filename, '/var/bigbluebutton/playback/presentation/download/' + filename)


def bbbversion():
    global bbb_ver
    bbb_ver = 0
    s_events = minidom.parse(source_events)
    for event in s_events.getElementsByTagName('recording'):
        bbb_ver = event.getAttribute('bbb_version')
    return bbb_ver


def main():
    sys.stderr = open(LOGFILE, 'a')
    print >> sys.stderr, "\n<-------------------" + time.strftime("%c") + "----------------------->\n"

    bbb_version = bbbversion()
    print >> sys.stderr, "bbb_version: " + bbb_version

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
        print >> sys.stderr, "Cleaning up temp files..."
        cleanup()
        print >> sys.stderr, "Done"


if __name__ == "__main__":
    main()
