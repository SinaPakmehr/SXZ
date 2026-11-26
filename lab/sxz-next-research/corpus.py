"""Fixed whole-file panel; previous corpus is opened read-only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parents[1] / "datasets/sxz5-data"
PUBLIC = ROOT.parents[1]/"datasets"
WIKI = "https://upload.wikimedia.org/wikipedia/commons/"
ONNX = "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/"
FILES = [
    ("dev","TXT",DATA/"alice29.txt","https://corpus.canterbury.ac.nz/descriptions/"),
    ("test","TXT",DATA/"plrabn12.txt","https://corpus.canterbury.ac.nz/descriptions/"),
    ("dev","PDF",DATA/"raw/irs1040.pdf","https://www.irs.gov/pub/irs-pdf/f1040.pdf"),
    ("test","PDF",DATA/"raw/bert.pdf","https://arxiv.org/pdf/1810.04805"),
    ("dev","DOCX",DATA/"raw/docx-shapes.docx","https://github.com/python-openxml/python-docx"),
    ("test","DOCX",DATA/"raw/docx-table.docx","https://github.com/python-openxml/python-docx"),
    ("dev","JPEG",DATA/"raw/banana.jpg",WIKI+"8/8a/Banana-Single.jpg"),
    ("test","JPEG",DATA/"raw/gull.jpg",WIKI+"9/9a/Gull_portrait_ca_usa.jpg"),
    ("dev","PNG",ROOT.parents[1]/"datasets/corpus/python-logo.png","https://www.python.org/static/community_logos/python-logo.png"),
    ("test","PNG",ROOT.parents[1]/"datasets/corpus/hopper.png","https://raw.githubusercontent.com/python-pillow/Pillow/main/Tests/images/hopper.png"),
    ("test-negative","PNG",DATA/"raw/transparency.png",WIKI+"4/47/PNG_transparency_demonstration_1.png"),
    ("dev","EXE",PUBLIC/"audit-assets/7zr.exe","https://www.7-zip.org/download.html"),
    ("dev","ONNX",ROOT.parents[1]/"datasets/corpus/mnist-8.onnx",ONNX+"mnist/model/mnist-8.onnx"),
    ("test","ONNX",ROOT.parents[1]/"datasets/corpus/squeezenet1.1-7.onnx",ONNX+"squeezenet/model/squeezenet1.1-7.onnx"),
    ("test","ONNX",ROOT.parents[1]/"datasets/corpus/mnist-12-int8.onnx",ONNX+"mnist/model/mnist-12-int8.onnx"),
]
