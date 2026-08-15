content = open(r'c:/Users/Riyaad/Documents/GitHub/Niblit/main.py', 'r', encoding='utf-8').read()
lines = [l for l in content.splitlines() if 'INSTRUMENT' in l]
if lines:
    for line in lines[:20]:
        print(line)
else:
    print('No INSTRUMENT lines found')