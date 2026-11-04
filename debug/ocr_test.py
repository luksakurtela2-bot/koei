import sys; sys.path.insert(0, "pipeline")
import pymupdf, eho
from sources import _get
out = []
for u in ["ZPI-KOEI-7949b51e792050983fa26d629a7ed346", "ZPI-KOEI-e8b4aa2b46f1e3965737214d92c16776"]:
    doc = pymupdf.open(stream=_get(f"https://eho.zse.hr/fileadmin/issuers/KOEI/{u}.pdf"), filetype="pdf")
    out.append(f"===== {u}\n" + eho._ocr(doc))
open("debug/ocr.txt", "w", encoding="utf-8").write("\n".join(out))
