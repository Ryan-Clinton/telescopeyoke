# Protocol step 4: colour.py with its defaults on each shared set, the background fixed beforehand
# (confirmation-results.md, step 4). A failure is counted, not fixed first.
cd /home/facepipe/telescopeyoke-laptop/freetools/pipe-new
export TY_CAMERA=183m TY_NO_WATCH=1 PYTHONWARNINGS=ignore TY_DATA=../ds-site TY_GRAXPERT=$HOME/telescopeyoke-laptop/freetools/dl/graxpert/GraXpert-linux/GraXpert TY_GRAXPERT_LIBS=$(cat ../graxpert_cuda_path) TY_SETIASTRO=$HOME/telescopeyoke-laptop/freetools/sas/bin/cosmicclarity
LEVEL=" D07 D18 D40 D44 D72 D43 D49 D56 D57 D65 "
for t in ../ds-site/frames/D*; do
  n=$(basename $t); have=$(ls $t | sed "s/combined-//" | tr "\n" " ")
  case " $have" in *" SII "*) p=SHO;; *" OIII "*) p=HOO;; *) p=LRGB;; esac
  bg=auto; case "$LEVEL" in *" $n "*) bg=level;; esac
  echo "$n $p background $bg"
  nice -n 5 ../../venv/bin/python colour.py $n --palette $p --background $bg > ../ds-site/$n.log 2>&1; code=$?
  grep -v frozen ../ds-site/$n.log | grep -E "saved|NOT|rror|Traceback|refus|could not" | sed "s/^/  /"
  echo "  exit $code"
done
echo finished
