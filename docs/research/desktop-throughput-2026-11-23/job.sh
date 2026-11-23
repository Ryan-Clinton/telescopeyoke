#!/bin/bash
# job.sh prepare | job.sh train WORKERS : the same mixed workload each time, so steps per second compare.
T=~/telescopeyoke-laptop/training; D=/mnt/d/telescopyokearchive/training-data; PY=~/telescopeyoke-laptop/venv/bin/python
cd ~/telescopeyoke-laptop/remote/code; export TY_DATA=~/telescopeyoke-laptop/remote/data TY_CAMERA=183m TY_NO_WATCH=1 PYTHONWARNINGS=ignore
SRC="--survey $HOME/telescopeyoke-laptop/igaps/frames --masters $D/seti/downloads $D/astrophotomarket"
if [ "$1" = prepare ]; then exec $PY denoiser.py prepare --data $T/pairs3 $SRC; fi
exec $PY denoiser.py train --data $T/pairs3 --out $T/bench/w$2.pt --steps 600 --workers $2 $SRC --repeats $T/repeat-pairs
