function install_ffmpeg {
    cd install/ffmpeg-static
    ./build-ubuntu.sh
    cp .target/bin/* /usr/bin 
    cd ../..
}

# Get root
sudo su

# Install python
apt-get install -y python

# Install ffmpeg
install_ffmpeg

# Create log directory
mkdir -p /var/log/bigbluebutton/download
chown tomcat7:tomcat7 /var/log/bigblubutton/download

# Copy python scripts to post_publish directory
cp src/*.py /usr/local/bigbluebutton/core/scripts/post_publish

# Copy ruby script that controlls the download process
cp src/*.rb /usr/local/bigbluebutton/core/scripts/post_publish

# Drop root
exit
