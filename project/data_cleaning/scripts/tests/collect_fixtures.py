import os, requests, time
H = {"User-Agent": "JNU-Training-Bot/0.1 (JNU student training project)"}
HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
os.makedirs(FIX, exist_ok=True)

def fetch_save(url, name):
    r = requests.get(url, headers=H, timeout=15)
    r.encoding = r.apparent_encoding
    p = os.path.join(FIX, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"{name}: status={r.status_code} len={len(r.text)}")
    time.sleep(1.5)

fetch_save("https://jwc.jnu.edu.cn/xsbszn/list.htm", "xsbszn_list.html")
fetch_save("https://jwc.jnu.edu.cn/2019/0419/c11805a310286/page.htm", "detail_xk.html")
