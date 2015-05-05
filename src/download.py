__author__ = 'palexang'
__email__ = 'palexang@it.auth.gr'

from xml.dom import minidom
import sys
import os
import shutil
import zipfile
import ffmpeg
import re
import time

# Python script that produces downloadable material from a published bbb recording.
# http://xkcd.com/1513/

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

def extract_timings():
    doc = minidom.parse(events_file)
    dictionary = {}
    total_length = 0
    j = 0

    for image in doc.getElementsByTagName('image'):
        path = image.getAttribute('xlink:href')
        if j == 0:
            path = u'/usr/local/bigbluebutton/core/scripts/logo.png'
            j += 1

        in_times = str(image.getAttribute('in')).split(' ')
        out_times = image.getAttribute('out').split(' ')

        temp = float( out_times[len(out_times) - 1] )
        if temp > total_length:
            total_length = temp

        occurrences = len(in_times)
        for i in range(occurrences):
            dictionary[float(in_times[i])] = temp_dir + str(path)
    return dictionary, total_length


def create_slideshow(dictionary, length, result):
    video_list = 'video_list.txt'
    f = open(video_list, 'w')

    times = dictionary.keys()
    times.sort()

    for i, t in enumerate(times):
        if i < 1:
            continue

        tmp_name = '%d.mp4' % i
        image = dictionary[t]

        if i == len(times) - 1:
            duration = length - t
        else:
            duration = times[i + 1] - t

        out_file = temp_dir + tmp_name

        ffmpeg.create_video_from_image(image, duration, out_file)
        f.write('file ' + out_file + '\n')
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


def rescale_presentation(new_height, new_width, dictionary):
    times = dictionary.keys()
    times.sort()
    for i, t in enumerate(times):
        if i < 1:
            continue
        ffmpeg.rescale_image(dictionary[t], new_height, new_width, dictionary[t])


def check_presentation_dims(dictionary, dims):
    print 'dims = ', dims
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

    rescale_presentation(new_height, new_width, dictionary)


def prepare():
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
    dictionary, length = extract_timings()
    dims = get_different_presentations(dictionary)
    check_presentation_dims(dictionary, dims)
    return dictionary, length, dims


def get_different_presentations(dictionary):
    times = dictionary.keys()
    presentations = []
    dims = {}
    for t in times:
        if t < 1:
            continue

        name = dictionary[t].split("/")[7]  # ******* MUST CHANGE ***** #
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


def zipdir(path):
    filename = meetingId + '.zip'
    zipf = zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(path):
        for f in files:
            zipf.write(os.path.join(root, f) )
    zipf.close()

    #Create symlink instead so that files are deleted
    if not os.path.exists('/var/bigbluebutton/playback/presentation/download/' + filename):
        os.symlink(source_dir + filename, '/var/bigbluebutton/playback/presentation/download/' + filename)


def main():
    sys.stderr = open(LOGFILE, 'a')
    print >> sys.stderr, "\n<-------------------" + time.strftime("%c") + "----------------------->\n"
    os.chdir(source_dir)

    dictionary, length, dims = prepare()

    audio = audio_path + 'audio.ogg'
    audio_trimmed = temp_dir + 'audio_trimmed.m4a'
    result = target_dir + 'meeting.mp4'
    slideshow = temp_dir + 'slideshow.mp4'

    try:
        create_slideshow(dictionary, length, slideshow)
        ffmpeg.trim_audio_start(dictionary, length, audio, audio_trimmed)
        ffmpeg.mux_slideshow_audio(slideshow, audio_trimmed, result)
        serve_webcams()
        zipdir('./download/')
    finally:
        print >> sys.stderr, "Cleaning up temp files..."
        cleanup()
        print >> sys.stderr, "Done"

if __name__ == "__main__":
    main()
