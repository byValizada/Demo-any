# -*- coding: utf-8 -*-
import json, urllib.request

BASE = "http://127.0.0.1:8000"

data = json.dumps({"email": "turalvalizada32@gmail.com", "password": "Tural2026"}).encode()
tok = json.loads(urllib.request.urlopen(
    urllib.request.Request(BASE + "/auth/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
).read())["access_token"]

h = {"Authorization": f"Bearer {tok}"}
courses = json.loads(urllib.request.urlopen(
    urllib.request.Request(BASE + "/courses/teacher", headers=h)
).read())

KEEP = {"informatika", "riyaziyyat"}
deleted = kept = 0

for c in courses:
    subj = c["subject"].lower().strip()
    if subj not in KEEP:
        cid = c["id"]
        req = urllib.request.Request(BASE + f"/courses/teacher/{cid}", headers=h, method="DELETE")
        try:
            urllib.request.urlopen(req)
            print(f"SİLİNDİ : {c['title'][:55]}")
            deleted += 1
        except Exception as e:
            print(f"XƏTA    : {c['title'][:40]} → {e}")
    else:
        print(f"SAXLANDI: {c['title'][:55]}  ({c['subject']})")
        kept += 1

print(f"\nSilindi: {deleted}  |  Saxlanıldı: {kept}")
