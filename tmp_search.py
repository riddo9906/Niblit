import os, re
root = r'c:\Users\Riyaad\Documents\GitHub\Niblit'
for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in {'niblit-env','build','.git','__pycache__'}]
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(dirpath, name)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                txt = fh.read()
        except Exception:
            continue
        if re.search(r'search_and_ingest|ingest_pdf|pdf.*search|filedialog|askopenfilename|askopenfilenames|tkinter|win32', txt, re.I):
            print(path)
