#!/bin/bash

function install_ffmpeg {
    wget https://github.com/stvs/ffmpeg-static/archive/master.zip
    unzip master.zip
    rm master.zip
    cd ffmpeg-static-master
    ./build-ubuntu.sh
    cp ./target/bin/* /usr/bin 
    cd ../
    rm -rf ffmpeg-static-master
}

# Install python
apt-get install -y python

# Install ffmpeg
install_ffmpeg

# Create log directory
mkdir -p /var/log/bigbluebutton/download
chown tomcat7:tomcat7 /var/log/bigbluebutton/download

# Copy python scripts to post_publish directory
cp src/*.py /usr/local/bigbluebutton/core/scripts/post_publish

# Copy ruby script that controlls the download process
cp src/*.rb /usr/local/bigbluebutton/core/scripts/post_publish
