# `sxz-image-math` - Mathematical Image Representation

Historical Phase 15 diagnostics over decoded pixels: analytical regions,
adaptive quadtree partitioning and shared compositional function networks.

```text
cd lab/sxz-image-math
python -B scripts/run_phase15.py
python -B scripts/run_phase15_ep2.py
python -B scripts/run_phase15_ep3.py
```

Images are **not redistributed**. The scripts expect the reviewed image files at
the relative `datasets/` paths in source; absent inputs are documented rather
than substituted. All reported comparisons are pixel-level, not original-file
reconstruction. No JPEG XL encoder was available.

Evidence:

- `results/phase15.json` - fixed regions, controls, exactness.
- `results/phase15_ep2.json` - adaptive quadtree and matched control.
- `results/phase15_ep3.json` - compositional networks and serialized decode.

The only isolated positive is the gull crop: `C`/network 86,632 B versus
spatial 86,641 B, i.e. `9/86,641=0.0104%`, not below 0.01%. Complete-image
results are negative. See `research/phases/15-image-math.md`.
