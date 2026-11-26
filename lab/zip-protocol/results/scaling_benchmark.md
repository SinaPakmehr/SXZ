# SXZ scaling benchmark

Python 3.13.14, Windows AMD64; zlib 1.3.1.
Probe window 128 B; maximum verified span 65536 B; Deflate level 9. 1 run(s) per profile; times are medians in seconds.
Fixed reference index cold start: 0.343 s (not included in rows).
All sizes are in bytes. `zlib+16` is Deflate with SXZ header; `FLAC` uses FFmpeg level 8 and verifies PCM samples only, not original WAV bytes.
Each SXZ row verifies the complete input byte for byte. Times exclude file I/O, SHA-256 and FLAC. Scan and prediction are subdivisions of pack time; they are not extra time.
`predict` means no formula scan; `full` is the usual adaptive stride with no fixed probe cap, not every byte.
With a positive cap the cheap pi/e/phi lookup still checks skipped positions in uncommitted ranges.

| Input | Input B | zlib+16 | FLAC | Profile | SXZ B | Probes | Formula B | Known hit/planted B | Codec | Scan s | Predict s | Pack s | Unpack s |
|---|---:|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| speech.wav | 474924 | 420506 | 275850 | predict | 317437 | 0 | 0 | - | pcm-residual (delta2/planes/zigzag) | 0.000 | 1.136 | 1.192 | 0.271 |
| speech.wav | 474924 | 420506 | 275850 | budget 512 | 317437 | 512 | 0 | - | pcm-residual (delta2/planes/zigzag) | 1.361 | 1.030 | 2.447 | 0.238 |
| speech.wav | 474924 | 420506 | 275850 | full | 317437 | 7421 | 0 | - | pcm-residual (delta2/planes/zigzag) | 15.363 | 1.032 | 16.450 | 0.225 |
| whale.wav | 5716198 | 4444415 | 1984297 | predict | 3109131 | 0 | 0 | - | pcm-residual (delta2/planes/zigzag) | 0.000 | 14.497 | 15.306 | 3.095 |
| whale.wav | 5716198 | 4444415 | 1984297 | budget 512 | 3109131 | 512 | 0 | - | pcm-residual (delta2/planes/zigzag) | 3.128 | 14.223 | 18.165 | 2.613 |
| music.wav | 10841388 | 9844600 | 3844644 | predict | 4680598 | 0 | 0 | - | pcm-residual (mid-side/delta2/planes/zigzag) | 0.000 | 18.331 | 19.483 | 7.349 |
| music.wav | 10841388 | 9844600 | 3844644 | budget 512 | 4680598 | 512 | 0 | - | pcm-residual (mid-side/delta2/planes/zigzag) | 4.625 | 18.919 | 25.878 | 7.049 |
| music.ogg | 1452719 | 1428484 | - | predict | 1428484 | 0 | 0 | - | deflate-whole | 0.000 | 0.000 | 0.151 | 0.023 |
| music.ogg | 1452719 | 1428484 | - | budget 512 | 1428484 | 512 | 0 | - | deflate-whole | 1.623 | 0.000 | 1.767 | 0.022 |
| hubble_deep_field.ppm | 2616016 | 1687812 | - | predict | 1687812 | 0 | 0 | - | deflate-whole | 0.000 | 6.180 | 6.591 | 0.045 |
| hubble_deep_field.ppm | 2616016 | 1687812 | - | budget 512 | 1687812 | 512 | 0 | - | deflate-whole | 1.986 | 6.399 | 8.807 | 0.047 |
| motorcycle_left.ppm | 1111515 | 950312 | - | predict | 663878 | 0 | 0 | - | pnm-residual (paeth) | 0.000 | 3.312 | 3.434 | 1.209 |
| motorcycle_left.ppm | 1111515 | 950312 | - | budget 512 | 663878 | 512 | 0 | - | pnm-residual (paeth) | 1.447 | 3.218 | 4.785 | 1.223 |
| photo-montage.ppm | 9437201 | 7622664 | - | predict | 4892806 | 0 | 0 | - | pnm-residual (paeth) | 0.000 | 36.071 | 37.159 | 10.573 |
| photo-montage.ppm | 9437201 | 7622664 | - | budget 512 | 4892806 | 512 | 0 | - | pnm-residual (paeth) | 4.019 | 30.828 | 35.924 | 8.483 |
| flights-200k.json | 9863892 | 856506 | - | predict | 856506 | 0 | 0 | - | deflate-whole | 0.000 | 0.000 | 3.059 | 0.047 |
| flights-200k.json | 9863892 | 856506 | - | budget 512 | 856506 | 512 | 0 | - | deflate-whole | 3.194 | 0.000 | 6.248 | 0.050 |
| hubble_deep_field.jpg | 527940 | 517686 | - | predict | 517686 | 0 | 0 | - | deflate-whole | 0.000 | 0.000 | 0.037 | 0.002 |
| hubble_deep_field.jpg | 527940 | 517686 | - | budget 512 | 517686 | 512 | 0 | - | deflate-whole | 1.026 | 0.000 | 1.065 | 0.001 |
| hubble_deep_field.jpg | 527940 | 517686 | - | full | 517286 | 8254 | 214 | - | deflate+formula+raw | 13.099 | 0.000 | 13.174 | 0.004 |
| random-1MiB | 1048576 | 1048918 | - | predict | 1048592 | 0 | 0 | - | stored | 0.000 | 0.000 | 0.076 | 0.001 |
| random-1MiB | 1048576 | 1048918 | - | budget 512 | 1048592 | 512 | 0 | - | stored | 1.173 | 0.000 | 1.244 | 0.001 |
| random-1MiB | 1048576 | 1048918 | - | full | 1048592 | 16384 | 0 | - | stored | 27.210 | 0.000 | 27.294 | 0.001 |
| random-4MiB | 4194304 | 4195606 | - | predict | 4194320 | 0 | 0 | - | stored | 0.000 | 0.000 | 0.322 | 0.007 |
| random-4MiB | 4194304 | 4195606 | - | budget 512 | 4194320 | 512 | 0 | - | stored | 1.394 | 0.000 | 1.575 | 0.004 |
| random-16MiB | 16777216 | 16782358 | - | predict | 16777232 | 0 | 0 | - | stored | 0.000 | 0.000 | 0.732 | 0.014 |
| random-16MiB | 16777216 | 16782358 | - | budget 512 | 16777232 | 512 | 0 | - | stored | 2.824 | 0.000 | 3.521 | 0.015 |
| random-32MiB | 33554432 | 33564694 | - | predict | 33554448 | 0 | 0 | - | stored | 0.000 | 0.000 | 1.406 | 0.028 |
| random-32MiB | 33554432 | 33564694 | - | budget 512 | 33554448 | 512 | 0 | - | stored | 5.262 | 0.000 | 6.639 | 0.027 |
| planted-mix-4MiB | 4194304 | 4191330 | - | predict | 4191330 | 0 | 0 | 0/340462 | deflate-whole | 0.000 | 0.000 | 0.178 | 0.012 |
| planted-mix-4MiB | 4194304 | 4191330 | - | budget 512 | 3855013 | 477 | 339440 | 339440/340462 | raw+formula | 1.085 | 0.000 | 1.425 | 0.477 |
| planted-mix-4MiB | 4194304 | 4191330 | - | budget 64 | 3863746 | 64 | 330680 | 330680/340462 | raw+formula | 0.667 | 0.000 | 0.999 | 0.480 |
| planted-mix-4MiB | 4194304 | 4191330 | - | full | 3854012 | 60227 | 340462 | 340462/340462 | raw+formula | 65.118 | 0.000 | 65.684 | 0.844 |

## Input SHA-256

- `speech.wav`: `f1fdfe44b3bd358c48955f4aad9d440ff1da8fb5e7f5de972e0a608169c7e026`
- `whale.wav`: `fbf97c03c9ddb7948f7f1468f95a0d0fec91d9caef11988ba2eb0357e2a7ea73`
- `music.wav`: `783e5d7412beb8c3ac8acb3f91c1360953fb3e9e37f2798b4559a769aece95dd`
- `music.ogg`: `73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779`
- `hubble_deep_field.ppm`: `6ee245985328633073fdda7fe8bbfebaee416e50ff86e27c73df2eca4e70f31e`
- `motorcycle_left.ppm`: `cd597e492ffec724dfe509951b6e041f9f51c7998c356f7258f0472b677d66cb`
- `photo-montage.ppm`: `f2debfb5b296009fb6bc53e77238ae977cb1e7d2d2e732ff5d3533d23136cbe9`
- `flights-200k.json`: `82c60682ccdec1a9cf1102b2a011bef789243053f1ac01a531580c72be3d8bc0`
- `hubble_deep_field.jpg`: `3a19c5dd8a927a9334bb1229a6d63711b1c0c767fb27e2286e7c84a3e2c2f5f4`
- `random-1MiB`: `5abb7516a980fe68dd201e83b813bd0f47fb91bc6a238fcca5d1b9d8e31a99f4`
- `random-4MiB`: `b569f93fe80816f45645df355d05c28f1a026df55247d98cc5213b021fed1bec`
- `random-16MiB`: `fca869b04431f050dae72352bd23b6212084f67b0ca0b24633a1ceda8b0c502c`
- `random-32MiB`: `b856ee2c6fb73d872e966c1943565d3ba1b9a9a4cd297656619f73c3416efb88`
- `planted-mix-4MiB`: `c682a83e18133b6763d9a441d8a8274de36473f2d34738d227afa1106c521ce5`
