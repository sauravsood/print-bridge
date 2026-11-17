"""Write small test PDFs by hand (no libraries): a 4x6 label, and an A4 sheet
with a landscape label in the top-left corner like many courier portals."""
import sys

def pdf(pages):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for (w, h), content in pages:
        stream = content.encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{content}\nendstream")
        cidx = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Contents {cidx} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out

def label(x, y, w, h):
    bars = "".join(f"{x+20+i*3} {y+20} {1+(i*7)%3} 60 re f\n" for i in range(60))
    return (f"2 w {x} {y} {w} {h} re S\n" + bars +
            f"BT /F1 22 Tf {x+20} {y+h-40} Td (SHIP TO: Test Customer) Tj ET\n"
            f"BT /F1 14 Tf {x+20} {y+h-70} Td (221B Baker St, Gurugram 122001) Tj ET\n"
            f"BT /F1 14 Tf {x+20} {y+h-95} Td (AWB 1234567890  COD Rs 499) Tj ET\n")

if __name__ == "__main__":
    open(sys.argv[1] + "/label-4x6.pdf", "wb").write(pdf([((288, 432), label(10, 10, 268, 412))]))
    # A4 portrait, landscape label 400x260pt near the top-left
    open(sys.argv[1] + "/a4-sheet.pdf", "wb").write(pdf([((595, 842), label(40, 540, 400, 260)), ((288, 432), label(10, 10, 268, 412))]))
