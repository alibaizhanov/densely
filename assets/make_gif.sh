#!/bin/sh
# demo_raw.mp4 (vhs assets/demo.tape) -> demo.gif
# Speeds the real-time recording up 3x and renders a palette-optimized GIF.
set -e
cd "$(dirname "$0")"
ffmpeg -y -i demo_raw.mp4 -vf "crop=1080:596:0:0,setpts=PTS/3,fps=10,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer" demo.gif
ls -lh demo.gif
