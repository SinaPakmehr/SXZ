# Structural-relations — complete file comparisons

Savings = strongest matched conventional archive minus the smaller of the two measured parametric policies.
No positive savings are credited to any exposed representation, deduplication, copy/insert, grammar or specialist.
Only the lab header, Zstd-compressed layout, descriptor stream and payload stream sum to archive bytes.

## Zstd-3 / bytes

| File | Family | Input | Raw Zstd | Plain exposed | Exact dedup | Diff | Best grammar* | Best conventional | Parametric | Savings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| docx-shapes.docx | xml | 122,610 | 104,095 | 99,374 | 99,451 | 99,864 | 99,383 | 99,374 | 99,862 | -488 |
| docx-table.docx | xml | 50,294 | 34,593 | 30,525 | 30,549 | 30,705 | 30,529 | 30,525 | 30,703 | -178 |
| docx-images.docx | xml | 132,875 | 124,098 | 118,412 | 118,438 | 118,786 | 118,419 | 118,412 | 118,897 | -485 |
| pptx-chart.pptx | xml | 1,393,564 | 242,855 | 204,382 | 204,026 | 204,530 | 204,467 | 204,026 | 204,287 | -261 |
| irs1040.pdf | pdf | 220,237 | 154,360 | 130,991 | 130,715 | 131,000 | 130,804 | 130,715 | 130,987 | -272 |
| bert.pdf | pdf | 775,166 | 553,259 | 449,427 | 445,614 | 452,889 | 448,429 | 445,614 | 453,871 | -8,257 |
| attention.pdf | pdf | 2,215,244 | 1,093,946 | 732,873 | 732,873 | 732,976 | 739,085 | 732,873 | 732,297 | 576 |
| squeezenet1.1-7.onnx | tensor | 4,956,208 | 4,590,041 | 4,243,374 | 4,243,374 | 4,243,374 | 4,243,484 | 4,243,374 | 4,243,374 | 0 |
| squeezenet1.0-12.onnx | tensor | 4,952,956 | 4,588,863 | 4,244,347 | 4,244,347 | 4,244,347 | 4,246,069 | 4,244,347 | 4,244,347 | 0 |
| mobilenetv2-7.onnx | tensor | 14,246,826 | 13,100,395 | 12,075,018 | 12,075,018 | 12,076,892 | 12,075,224 | 12,075,018 | 12,076,922 | -1,904 |
| zstd.exe | binary | 1,548,299 | 656,625 | 655,269 | 655,829 | 658,010 | 655,496 | 655,269 | 658,006 | -2,737 |
| djxl.exe | binary | 4,199,936 | 1,718,395 | 1,709,940 | 1,710,042 | 1,712,854 | 1,710,459 | 1,709,940 | 1,712,780 | -2,840 |
| cjxl.exe | binary | 5,347,840 | 2,250,582 | 2,239,824 | 2,238,077 | 2,239,452 | 2,239,698 | 2,238,077 | 2,239,352 | -1,275 |
| python-logo.png | image | 45,187 | 4,581 | 4,242 | 4,329 | 4,331 | 4,247 | 4,242 | 4,271 | -29 |
| hopper.png | image | 30,605 | 30,619 | 37,781 | 37,781 | 38,278 | 37,787 | 37,781 | 38,135 | -354 |
| flower_thumbnail.png | image | 35,617 | 35,631 | 48,283 | 48,283 | 49,047 | 48,285 | 48,283 | 48,832 | -549 |
| exif.png | image | 179,336 | 179,355 | 115,631 | 115,973 | 127,112 | 115,711 | 115,631 | 128,523 | -12,892 |

* Includes grammar alone and grammar after conventional differential.

| Family | Files | Net over matched baseline (bytes) | Max fallback saving | ≥1% and ≥256 B wins |
|---|---:|---:|---:|---:|
| xml | 4 | -1,412 | 0 | 0 |
| pdf | 3 | -7,953 | 576 | 0 |
| tensor | 3 | -1,904 | 0 | 0 |
| binary | 3 | -6,852 | 0 | 0 |
| image | 4 | -13,824 | 0 | 0 |
## Zstd-9 / bytes

| File | Family | Input | Raw Zstd | Plain exposed | Exact dedup | Diff | Best grammar* | Best conventional | Parametric | Savings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| docx-shapes.docx | xml | 122,610 | 102,940 | 97,159 | 97,254 | 97,786 | 97,168 | 97,159 | 97,782 | -623 |
| docx-table.docx | xml | 50,294 | 33,985 | 29,314 | 29,337 | 29,529 | 29,318 | 29,314 | 29,531 | -217 |
| docx-images.docx | xml | 132,875 | 123,460 | 117,650 | 117,676 | 118,114 | 117,659 | 117,650 | 118,231 | -581 |
| pptx-chart.pptx | xml | 1,393,564 | 240,125 | 199,491 | 199,550 | 199,863 | 199,638 | 199,491 | 199,600 | -109 |
| irs1040.pdf | pdf | 220,237 | 153,604 | 111,537 | 111,462 | 111,706 | 111,609 | 111,462 | 111,683 | -221 |
| bert.pdf | pdf | 775,166 | 547,431 | 423,810 | 422,552 | 429,352 | 423,721 | 422,552 | 429,650 | -7,098 |
| attention.pdf | pdf | 2,215,244 | 1,076,667 | 680,626 | 680,626 | 682,248 | 680,932 | 680,626 | 681,397 | -771 |
| squeezenet1.1-7.onnx | tensor | 4,956,208 | 4,585,541 | 4,218,368 | 4,218,368 | 4,218,368 | 4,219,504 | 4,218,368 | 4,218,368 | 0 |
| squeezenet1.0-12.onnx | tensor | 4,952,956 | 4,584,666 | 4,215,742 | 4,215,742 | 4,215,742 | 4,215,854 | 4,215,742 | 4,215,742 | 0 |
| mobilenetv2-7.onnx | tensor | 14,246,826 | 13,082,475 | 12,017,777 | 12,017,777 | 12,020,177 | 12,017,369 | 12,017,369 | 12,020,456 | -3,087 |
| zstd.exe | binary | 1,548,299 | 621,613 | 620,326 | 621,366 | 622,133 | 620,348 | 620,326 | 622,125 | -1,799 |
| djxl.exe | binary | 4,199,936 | 1,612,738 | 1,604,017 | 1,604,221 | 1,604,897 | 1,604,521 | 1,604,017 | 1,604,809 | -792 |
| cjxl.exe | binary | 5,347,840 | 2,086,380 | 2,075,472 | 2,075,548 | 2,075,451 | 2,075,429 | 2,075,429 | 2,075,373 | 56 |
| python-logo.png | image | 45,187 | 4,291 | 3,975 | 4,048 | 4,055 | 3,980 | 3,975 | 4,011 | -36 |
| hopper.png | image | 30,605 | 30,619 | 35,870 | 35,870 | 36,425 | 35,873 | 35,870 | 36,387 | -517 |
| flower_thumbnail.png | image | 35,617 | 35,631 | 45,880 | 45,880 | 46,724 | 45,884 | 45,880 | 46,810 | -930 |
| exif.png | image | 179,336 | 179,355 | 102,777 | 103,208 | 113,251 | 102,835 | 102,777 | 114,410 | -11,633 |

* Includes grammar alone and grammar after conventional differential.

| Family | Files | Net over matched baseline (bytes) | Max fallback saving | ≥1% and ≥256 B wins |
|---|---:|---:|---:|---:|
| xml | 4 | -1,530 | 0 | 0 |
| pdf | 3 | -8,090 | 0 | 0 |
| tensor | 3 | -3,087 | 0 | 0 |
| binary | 3 | -2,535 | 56 | 0 |
| image | 4 | -13,116 | 0 | 0 |

## Zstd-9 decoding, checksum and original framing included

| File | Relational distinct records with a proposed parent | Conventional ref. count | Params chosen | Raw MB/s | Conventional MB/s | Parametric MB/s | Reconstruction ms | Special bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| docx-shapes.docx | 61 | 0 | 1 | 6192.4 | 59.8 | 30.2 | 1.62 | 96,829 |
| docx-table.docx | 24 | 0 | 1 | 2406.4 | 52.2 | 15.2 | 2.14 | 29,161 |
| docx-images.docx | 41 | 0 | 4 | 7725.3 | 32.9 | 32.9 | 3.06 | 117,676 |
| pptx-chart.pptx | 97 | 0 | 28 | 6696.6 | 148.3 | 140.0 | 6.52 | 199,920 |
| irs1040.pdf | 49 | 72 | 1 | 6256.7 | 15.9 | 16.2 | 12.03 | 112,673 |
| bert.pdf | 610 | 22 | 6 | 4554.4 | 18.8 | 16.5 | 36.26 | 423,606 |
| attention.pdf | 3304 | 0 | 107 | 2837.1 | 30.7 | 30.2 | 45.19 | 680,937 |
| squeezenet1.1-7.onnx | 26 | 0 | 0 | 914.1 | 341.4 | 341.4 | 5.56 | 4,212,834 |
| squeezenet1.0-12.onnx | 26 | 0 | 0 | 742.8 | 257.4 | 257.4 | 5.15 | 4,211,097 |
| mobilenetv2-7.onnx | 224 | 0 | 6 | 866.2 | 127.4 | 199.9 | 37.26 | 11,991,058 |
| zstd.exe | 359 | 0 | 5 | 966.2 | 293.3 | 315.8 | 0.86 | 513,232 |
| djxl.exe | 717 | 0 | 18 | 818.2 | 345.7 | 300.8 | 2.46 | 1,285,268 |
| cjxl.exe | 816 | 433 | 27 | 864.6 | 233.0 | 357.1 | 3.59 | 1,653,196 |
| python-logo.png | 60 | 0 | 4 | 2722.1 | 44.5 | 42.2 | 0.46 | 3,219 |
| hopper.png | 189 | 0 | 19 | 11771.1 | 7.6 | 11.3 | 1.79 | 20,485 |
| flower_thumbnail.png | 234 | 0 | 23 | 11872.4 | 13.2 | 10.7 | 2.23 | 25,602 |
| exif.png | 2831 | 0 | 130 | 13186.5 | 6.4 | 5.9 | 19.00 | 77,201 |

## Memory (Windows fresh child processes, absolute peak working set)

| File | Method | Peak before decode MiB | Peak after decode MiB |
|---|---|---:|---:|
| docx-shapes.docx | zstd-9 | 36.90 | 37.07 |
| docx-shapes.docx | srx-plain-9 | 37.00 | 38.50 |
| docx-shapes.docx | srx-math-margin-9 | 36.69 | 38.05 |
| docx-table.docx | zstd-9 | 36.65 | 36.72 |
| docx-table.docx | srx-plain-9 | 36.77 | 37.76 |
| docx-table.docx | srx-math-9 | 36.76 | 37.88 |
| docx-images.docx | zstd-9 | 37.03 | 37.16 |
| docx-images.docx | srx-plain-9 | 36.91 | 38.30 |
| docx-images.docx | srx-math-9 | 36.71 | 38.02 |
| pptx-chart.pptx | zstd-9 | 37.00 | 38.42 |
| pptx-chart.pptx | srx-plain-9 | 36.66 | 45.50 |
| pptx-chart.pptx | srx-math-9 | 36.74 | 45.03 |
| irs1040.pdf | zstd-9 | 37.07 | 37.33 |
| irs1040.pdf | srx-dedup-9 | 36.98 | 41.09 |
| irs1040.pdf | srx-math-9 | 36.66 | 40.98 |
| bert.pdf | zstd-9 | 37.28 | 38.09 |
| bert.pdf | srx-dedup-9 | 37.21 | 44.63 |
| bert.pdf | srx-math-margin-9 | 37.01 | 44.05 |
| attention.pdf | zstd-9 | 37.67 | 39.86 |
| attention.pdf | srx-plain-9 | 37.30 | 53.45 |
| attention.pdf | srx-math-margin-9 | 37.37 | 54.05 |
| squeezenet1.1-7.onnx | zstd-9 | 41.07 | 45.87 |
| squeezenet1.1-7.onnx | srx-plain-9 | 40.73 | 67.49 |
| squeezenet1.1-7.onnx | srx-math-9 | 40.71 | 67.46 |
| squeezenet1.0-12.onnx | zstd-9 | 40.95 | 45.74 |
| squeezenet1.0-12.onnx | srx-plain-9 | 40.69 | 64.77 |
| squeezenet1.0-12.onnx | srx-math-9 | 40.62 | 64.61 |
| mobilenetv2-7.onnx | zstd-9 | 49.12 | 62.78 |
| mobilenetv2-7.onnx | srx-grammar-forced-9 | 48.38 | 107.44 |
| mobilenetv2-7.onnx | srx-math-margin-9 | 48.22 | 107.87 |
| zstd.exe | zstd-9 | 37.30 | 38.85 |
| zstd.exe | srx-plain-9 | 37.52 | 45.21 |
| zstd.exe | srx-math-9 | 37.30 | 45.00 |
| djxl.exe | zstd-9 | 38.15 | 42.23 |
| djxl.exe | srx-plain-9 | 38.21 | 58.54 |
| djxl.exe | srx-math-9 | 38.20 | 58.65 |
| cjxl.exe | zstd-9 | 38.62 | 43.80 |
| cjxl.exe | srx-diff-grammar-local-9 | 38.83 | 64.13 |
| cjxl.exe | srx-math-9 | 38.92 | 65.17 |
| python-logo.png | zstd-9 | 36.60 | 36.71 |
| python-logo.png | srx-plain-9 | 36.66 | 37.21 |
| python-logo.png | srx-math-9 | 36.79 | 37.33 |
| hopper.png | zstd-9 | 36.86 | 36.92 |
| hopper.png | srx-plain-9 | 36.73 | 37.78 |
| hopper.png | srx-math-9 | 36.58 | 37.65 |
| flower_thumbnail.png | zstd-9 | 36.61 | 36.65 |
| flower_thumbnail.png | srx-plain-9 | 36.68 | 37.79 |
| flower_thumbnail.png | srx-math-9 | 36.56 | 38.02 |
| exif.png | zstd-9 | 36.87 | 37.10 |
| exif.png | srx-plain-9 | 36.69 | 45.04 |
| exif.png | srx-math-margin-9 | 36.66 | 44.92 |
