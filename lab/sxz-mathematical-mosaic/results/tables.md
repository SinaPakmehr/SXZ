# Mathematical-mosaic measured results

`A` = independent slices. `B` = local fragment reuse. Net is relative to the same framed hybrid, not raw size.
A candidate's raw coverage is union of exact hits; the economic column counts only mathematical bytes in a smaller final hybrid.
Dictionary-reference price includes a paid-once dictionary amortized across 19 test files in `external`.

## Held-out byte view, one million reference symbols

| Whole file | Input | Hit starts | Max | Raw union % | Selected hybrid | Direct hybrid | Net | Zstd-3 | Best external | SXZ4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| plrabn12.txt | 481,861 | 24,461 | 4 | 14.160 | 191,731 | 191,731 | 0 | 191,688 | 165,412 | 195,292 |
| book2 | 610,856 | 31,325 | 5 | 14.198 | 203,831 | 203,831 | 0 | 203,788 | 169,824 | — |
| bert.pdf | 775,166 | 58,841 | 13 | 17.305 | 553,352 | 553,302 | -50 | 553,259 | 545,636 | 572,495 |
| docx-table.docx | 50,294 | 7,911 | 24 | 28.421 | 34,651 | 34,636 | -15 | 34,593 | 33,576 | 34,037 |
| tree-test.xlsx | 1,018,212 | 38,476 | 6 | 10.776 | 1,018,292 | 1,018,292 | 0 | 1,018,249 | 1,010,040 | — |
| pptx-fill.pptx | 778,084 | 32,687 | 24 | 11.165 | 774,304 | 774,290 | -14 | 774,247 | 769,424 | — |
| wiki.html | 534,613 | 36,627 | 6 | 16.812 | 88,299 | 88,299 | 0 | 88,256 | 69,648 | — |
| linux-tree.json | 17,594,055 | 3,309,266 | 8 | 40.974 | 2,804,320 | 2,804,320 | 0 | 2,804,276 | 2,326,184 | — |
| xml | 5,345,280 | 268,697 | 6 | 12.734 | 635,347 | 635,347 | 0 | 635,303 | 453,260 | — |
| banana.jpg | 2,085,213 | 75,228 | 24 | 9.860 | 1,698,992 | 1,699,756 | 764 | 1,699,713 | 1,654,308 | — |
| hopper.png | 30,605 | 1,403 | 4 | 12.429 | 30,662 | 30,662 | 0 | 30,619 | 30,609 | — |
| hopper.bmp | 49,290 | 4,384 | 6 | 22.345 | 39,810 | 39,810 | 0 | 39,767 | 32,960 | 34,797 |
| sample5.mp4 | 2,848,208 | 122,957 | 9 | 11.293 | 2,834,669 | 2,834,669 | 0 | 2,834,625 | 2,833,256 | — |
| sample15.mp3 | 307,453 | 19,909 | 6 | 15.718 | 282,793 | 282,793 | 0 | 282,750 | 280,711 | — |
| audio-slice.wav | 1,048,620 | 150,786 | 13 | 34.470 | 878,591 | 879,058 | 467 | 879,015 | 757,964 | — |
| 7zr.exe | 602,624 | 105,419 | 10 | 31.325 | 354,826 | 354,820 | -6 | 354,777 | 288,748 | 339,438 |
| libzstd.dll | 980,290 | 200,893 | 27 | 35.548 | 396,777 | 396,759 | -18 | 396,716 | 313,364 | — |
| silesia.zip | 67,633,896 | 2,476,001 | 10 | 10.509 | 67,587,459 | 67,547,321 | -40,138 | 67,547,277 | 67,425,136 | — |
| squeezenet1.1-7.onnx | 4,956,208 | 184,236 | 5 | 10.655 | 4,590,085 | 4,590,085 | 0 | 4,590,041 | 4,566,872 | 4,244,930 |

## Growth / math versus controls

| Symbols | Library | File–seed rows | Mean length | Max | Mean raw % | Mean economic % | Fallback total gain |
|---:|---|---:|---:|---:|---:|---:|---:|
| 8,192 | math | 5 | 12.6785 | 23 | 18.235 | 0.000000 | 0 |
| 8,192 | uniform | 15 | 3.0074 | 4 | 0.148 | 0.000000 | 0 |
| 8,192 | matched | 15 | 8.6106 | 19 | 18.547 | 0.000399 | 8 |
| 8,192 | shuffled | 15 | 7.1544 | 18 | 18.468 | 0.000723 | 9 |
| 100,000 | math | 5 | 7.9866 | 13 | 20.719 | 0.000278 | 1 |
| 100,000 | uniform | 15 | 3.0035 | 4 | 1.733 | 0.000000 | 0 |
| 100,000 | matched | 15 | 5.2325 | 17 | 20.488 | 0.000287 | 4 |
| 100,000 | shuffled | 15 | 4.9872 | 21 | 20.661 | 0.000000 | 0 |
| 1,000,000 | math | 5 | 4.1032 | 24 | 33.940 | 0.000000 | 0 |
| 1,000,000 | uniform | 15 | 3.0040 | 5 | 14.117 | 0.000000 | 0 |
| 1,000,000 | matched | 15 | 4.6586 | 31 | 31.122 | 0.000185 | 2 |
| 1,000,000 | shuffled | 15 | 4.7007 | 30 | 30.347 | 0.000093 | 1 |
| 10,000,000 | math | 5 | 3.1174 | 21 | 74.445 | 0.000000 | 0 |
| 10,000,000 | uniform | 15 | 3.0051 | 5 | 74.220 | 0.000000 | 0 |
| 10,000,000 | matched | 15 | 3.3248 | 28 | 80.018 | 0.000000 | 0 |
| 10,000,000 | shuffled | 15 | 3.3781 | 30 | 79.646 | 0.000000 | 0 |

## Whole-file radix panel at 100k reference symbols

| Representation | Library | Mean raw union % (symbols) | Max symbols | Fallback gain | Criterion passes |
|---|---|---:|---:|---:|---:|
| bytes | math | 20.6784 | 13 | 0 | 0 |
| bytes | uniform | 1.5812 | 4 | 0 | 0 |
| bytes | matched | 20.6718 | 17 | 0 | 0 |
| bytes | shuffled | 20.6098 | 21 | 0 | 0 |
| b2 | math | 26.4519 | 135 | 129 | 0 |
| b2 | uniform | 5.6509 | 40 | 0 | 0 |
| b2 | matched | 25.0940 | 211 | 0 | 0 |
| b2 | shuffled | 24.9688 | 290 | 0 | 0 |
| b4 | math | 25.1834 | 81 | 6 | 0 |
| b4 | uniform | 4.2603 | 19 | 0 | 0 |
| b4 | matched | 24.5350 | 117 | 0 | 0 |
| b4 | shuffled | 24.2100 | 85 | 67 | 0 |
| b8 | math | 24.7625 | 49 | 99 | 0 |
| b8 | uniform | 3.4115 | 12 | 0 | 0 |
| b8 | matched | 22.8926 | 55 | 6 | 0 |
| b8 | shuffled | 22.8692 | 49 | 0 | 0 |
| b16 | math | 24.0781 | 25 | 0 | 0 |
| b16 | uniform | 2.8974 | 9 | 0 | 0 |
| b16 | matched | 22.9269 | 32 | 0 | 0 |
| b16 | shuffled | 22.6699 | 46 | 0 | 0 |
| dec3 | math | 24.6403 | 45 | 0 | 0 |
| dec3 | uniform | 0.4964 | 12 | 0 | 0 |
| dec3 | matched | 24.5904 | 66 | 0 | 0 |
| dec3 | shuffled | 24.9779 | 50 | 0 | 0 |
| dec20 | math | 16.0723 | 48 | 0 | 0 |
| dec20 | uniform | 0.6878 | 12 | 0 | 0 |
| dec20 | matched | 15.7303 | 13 | 0 | 0 |
| dec20 | shuffled | 15.7024 | 18 | 0 | 0 |
| decvar | math | 1.7974 | 45 | 0 | 0 |
| decvar | uniform | 0.7482 | 11 | 0 | 0 |
| decvar | matched | 0.7098 | 11 | 0 | 0 |
| decvar | shuffled | 0.7665 | 11 | 0 | 0 |

## Held-out bank comparison

| Library | File–seed rows | Mean raw % | Max | Net positive files/seeds | Economic % | Net forced | Fallback gain |
|---|---:|---:|---:|---:|---:|---:|---:|
| math | 19 | 18.9841 | 27 | 2 | 0.000126 | -39,010 | 1,231 |
| uniform | 57 | 16.3613 | 6 | 0 | 0.000000 | 0 | 0 |
| matched | 57 | 18.3959 | 33 | 8 | 0.001812 | 1,967 | 3,213 |
| shuffled | 57 | 18.3760 | 33 | 9 | 0.007565 | 1,122 | 4,388 |

## Runtime per held-out full file
For selected exact branch, measured decode is emitted when input is ≤6 MiB. `candidate campaign` includes building multiple experimental variants, not just one encoder.

| File | Search (s) | Candidate campaign (s) | Best math warm MB/s | Cold MB/s | Zstd-3 MB/s |
|---|---:|---:|---:|---:|---:|
| plrabn12.txt | 0.0158 | 0.056 | 628.00 | 524.73 | 528.82 |
| book2 | 0.0113 | 0.058 | 461.79 | 748.23 | 864.50 |
| bert.pdf | 0.0274 | 0.087 | 1189.45 | 825.61 | 2292.03 |
| docx-table.docx | 0.0027 | 0.027 | 902.94 | 5.76 | 3960.16 |
| tree-test.xlsx | 0.0317 | 0.042 | 1929.16 | 781.92 | 6810.78 |
| pptx-fill.pptx | 0.0277 | 0.103 | 612.95 | 132.68 | 2894.66 |
| wiki.html | 0.0189 | 0.040 | 969.56 | 921.75 | 1154.17 |
| linux-tree.json | 0.6564 | 0.568 | — | — | 1445.01 |
| xml | 0.0776 | 0.408 | 603.84 | 463.71 | 1375.49 |
| banana.jpg | 0.0738 | 0.308 | 1391.26 | 212.15 | 3111.79 |
| hopper.png | 0.0055 | 0.002 | 1545.71 | 713.40 | 6120.99 |
| hopper.bmp | 0.0019 | 0.004 | 659.84 | 484.18 | 860.21 |
| sample5.mp4 | 0.1073 | 0.177 | 1584.63 | 1542.24 | 3537.71 |
| sample15.mp3 | 0.0158 | 0.051 | 513.71 | 754.12 | 2692.23 |
| audio-slice.wav | 0.0451 | 0.088 | 311.16 | 184.30 | 848.60 |
| 7zr.exe | 0.0404 | 0.094 | 559.85 | 493.15 | 695.15 |
| libzstd.dll | 0.0610 | 0.203 | 427.51 | 405.46 | 831.53 |
| silesia.zip | 1.9488 | 2.564 | — | — | 2900.69 |
| squeezenet1.1-7.onnx | 0.1455 | 0.360 | 498.85 | 495.97 | 896.47 |
