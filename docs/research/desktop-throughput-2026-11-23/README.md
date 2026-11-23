# Desktop throughput, 23 November 2026

The same mixed training workload (own pairs, 767 IGAPS frames, 36 masters, repeated
survey pairs; 600 steps) on the GTX 1080, one run per setting, run by `desktopqueue.py`.
`job.sh` is the command and `usage.csv` the 30-second samples.

| CPU workers making batches | Steps/s | Time the training loop waited for data | GPU use (4-5 samples) | GPU power |
|---:|---:|---:|---:|---:|
| 0 | 3.7 | 28% | 96% | 184 W |
| 2 | 3.8 | 0% | 96% | 170 W |
| 4 | 3.8 | 0% | 96% | 172 W |
| 6 | 3.7 | 0% | 77% | 147 W |

**Prefetching removed the wait but did not speed training up.** The GPU was already at
96% without it: its work is queued, so it carries on while Python makes the next batch.
On this workload the GPU is the limit. The differences are within rounding and one run
each. Training stays at about 54 minutes for 12,000 steps; `--workers` stays off by
default, and 2 is used for the queued runs because it costs nothing.

The idle time was between jobs and in the CPU lane, which the queue addresses. The queue
had only just started when this was written, so **no before/after figure for a whole
session exists yet**. `./desktopqueue.py report` gives it from `usage.csv` as the queue runs.

Inference now batches four tiles at a time. Its speed has not been measured.
