# -*- coding: utf-8 -*-
import json, urllib.request

BASE = "http://127.0.0.1:8000"

def post(path, body, tok):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
          headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def L(title, content, m, t="text"):
    return {"title": title, "content": content, "lesson_type": t, "duration_min": m}

tok = post("/auth/login", {"email": "turalvalizada32@gmail.com", "password": "Tural2026"}, "")["access_token"]
# login düzəlt
data = json.dumps({"email":"turalvalizada32@gmail.com","password":"Tural2026"}).encode()
tok = json.loads(urllib.request.urlopen(urllib.request.Request(BASE+"/auth/login", data=data, headers={"Content-Type":"application/json"}, method="POST")).read())["access_token"]

COURSES = [
    # ── İNFORMATİKA (10 kurs) ────────────────────────────────────────────────
    {
        "title": "Sıfırdan Python",
        "subtitle": "Proqramlaşdırmanı sıfırdan öyrən",
        "subject": "İnformatika", "level": "beginner", "cover_color": "#7C3AED",
        "objectives": ["Dəyişənlər və tiplər", "Şərt operatorları", "Funksiyalar", "Siyahı və lüğətlər"],
        "is_published": True,
        "modules": [
            {"title": "Əsaslar", "lessons": [L("Python nədir?","Python populyar proqramlaşdırma dilidir.",7), L("Dəyişənlər","ad = 'Tural'; yas = 16",8), L("if/else","if yas>=18: print('böyük')",9)]},
            {"title": "Funksiyalar", "lessons": [L("Funksiya yazmaq","def topla(a,b): return a+b",9), L("Parametrlər","Funksiyanın girişi və çıxışı.",8)]},
            {"title": "Məlumat strukturları", "lessons": [L("Siyahılar","meyveler = ['alma','armud']",9), L("Lüğətlər","şagird = {'ad':'Anar','yas':15}",9)]},
        ]
    },
    {
        "title": "Veb: HTML & CSS",
        "subtitle": "Öz veb səhifəni sıfırdan qur",
        "subject": "İnformatika", "level": "beginner", "cover_color": "#0891B2",
        "objectives": ["HTML teqlərini öyrənmək", "CSS ilə dizayn", "Flexbox layout", "İlk veb səhifə"],
        "is_published": True,
        "modules": [
            {"title": "HTML", "lessons": [L("Teqlər","h1, p, a, img, div...",8), L("Linklər & şəkillər","<a href='...'> <img src='...'>",9)]},
            {"title": "CSS", "lessons": [L("Selektorlar","p{} .class{} #id{}",8), L("Flexbox","display:flex; justify-content; align-items",11)]},
        ]
    },
    {
        "title": "JavaScript Əsasları",
        "subtitle": "Veb səhifəni canlandır",
        "subject": "İnformatika", "level": "beginner", "cover_color": "#F59E0B",
        "objectives": ["Dəyişənlər let/const", "DOM ilə işləmək", "Hadisələr", "Funksiyalar"],
        "is_published": True,
        "modules": [
            {"title": "Giriş", "lessons": [L("let və const","let ad='Tural'; const PI=3.14;",8), L("Funksiyalar","function salam(){alert('Salam!')}",9)]},
            {"title": "DOM", "lessons": [L("Element seçmək","document.querySelector('h1')",9), L("Event listener","btn.addEventListener('click', f)",10)]},
        ]
    },
    {
        "title": "ES6+ Müasir JavaScript",
        "subtitle": "Arrow function, async/await, destructuring",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#6366F1",
        "objectives": ["Arrow functions", "Promise & async/await", "Destructuring", "Spread operator"],
        "is_published": True,
        "modules": [
            {"title": "Yeni sintaksis", "lessons": [L("Arrow functions","const f = (a,b) => a+b;",8), L("Template literals","`Salam, ${ad}!`",7)]},
            {"title": "Asinxron JS", "lessons": [L("Promise",".then() zənciri",10), L("Async/Await","async function yükle(){ const r = await fetch(...) }",11)]},
        ]
    },
    {
        "title": "Verilənlər Bazası: SQL",
        "subtitle": "SELECT-dən JOIN-ə real sorğular",
        "subject": "İnformatika", "level": "beginner", "cover_color": "#0D3B6E",
        "objectives": ["SELECT sorğuları", "WHERE filtrasiyası", "JOIN əməliyyatları", "Subquery"],
        "is_published": True,
        "modules": [
            {"title": "Əsas sorğular", "lessons": [L("SELECT","SELECT * FROM users;",7), L("WHERE","SELECT ad FROM users WHERE yas>18;",8)]},
            {"title": "Birləşdirmə", "lessons": [L("INNER JOIN","Uyğun sətirləri birləşdirir.",10), L("LEFT JOIN","Sol cədvəlin hamısını saxlayır.",10)]},
        ]
    },
    {
        "title": "Alqoritmlər & Məlumat Strukturları",
        "subtitle": "Stack, queue, ağac, axtarış alqoritmləri",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#7C3AED",
        "objectives": ["Massiv və lüğət fərqi", "Stack, Queue", "Rekursiya", "Binary search"],
        "is_published": True,
        "modules": [
            {"title": "Massivlər", "lessons": [L("Massiv əməliyyatları","Əlavə etmə, silmə, axtarış O(n).",8), L("Dinamik massiv","Python list necə böyüyür.",7)]},
            {"title": "Stack & Queue", "lessons": [L("Stack","LIFO: append() və pop()",8), L("Queue","FIFO: collections.deque",8)]},
            {"title": "Rekursiya", "lessons": [L("Rekursiv funksiyalar","Baza halı mütləq lazımdır.",10), L("Fibonacci","f(n)=f(n-1)+f(n-2)",9)]},
        ]
    },
    {
        "title": "Kompüter Şəbəkələri",
        "subtitle": "TCP/IP, DNS, HTTP — internetin daxili aləmi",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#1B7A4A",
        "objectives": ["OSI modeli", "IP ünvanlama", "HTTP protokolu", "DNS sistemi"],
        "is_published": True,
        "modules": [
            {"title": "OSI Modeli", "lessons": [L("7 qat","Fiziki→Kanal→Şəbəkə→Nəqliyyat→Sessiya→Təsvir→Tətbiq",10), L("TCP vs UDP","Etibarlı vs sürətli ötürmə.",9)]},
            {"title": "Protokollar", "lessons": [L("IP ünvanlama","IPv4: 192.168.1.1",9), L("HTTP/HTTPS","GET, POST, 200, 404, 500",9)]},
        ]
    },
    {
        "title": "React.js ilə Frontend",
        "subtitle": "Komponent, state, props — müasir UI",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#0891B2",
        "objectives": ["JSX sintaksisi", "useState hook", "Props ötürmə", "useEffect"],
        "is_published": True,
        "modules": [
            {"title": "Komponentlər", "lessons": [L("JSX","function Salam(){return <h1>Salam</h1>}",9), L("Props","<Kart ad='Tural' yas={16} />",9)]},
            {"title": "Hooklar", "lessons": [L("useState","const [sayi, setSayi] = useState(0)",10), L("useEffect","Yan effektlər: API çağırışı, timer",11)]},
        ]
    },
    {
        "title": "Python: OOP Proqramlaşdırma",
        "subtitle": "Siniflər, miras, polimorfizm",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#6366F1",
        "objectives": ["Sinif yaratmaq", "__init__ metodu", "Miras (inheritance)", "Polimorfizm"],
        "is_published": True,
        "modules": [
            {"title": "Siniflər", "lessons": [L("class yaratmaq","class İt:\n    def __init__(self, ad):\n        self.ad = ad",10), L("Metodlar","def hürü(self): print('hav!')",8)]},
            {"title": "Miras", "lessons": [L("Inheritance","class Çoban(İt): pass",10), L("super()","super().__init__(ad)",9)]},
        ]
    },
    {
        "title": "Süni İntellekt Əsasları",
        "subtitle": "ML, neyron şəbəkələr, praktik AI",
        "subject": "İnformatika", "level": "advanced", "cover_color": "#DB2777",
        "objectives": ["ML növlərini bilmək", "Neyron şəbəkə quruluşu", "Model qiymətləndirmə", "Python sklearn"],
        "is_published": True,
        "modules": [
            {"title": "ML Giriş", "lessons": [L("Supervised vs Unsupervised","Nəzarətli vs nəzarətsiz öyrənmə.",10), L("Overfitting","Model həddən artıq öyrənərsə...",9)]},
            {"title": "Alqoritmlər", "lessons": [L("Xətti reqressiya","y = wx + b",10), L("Qərar ağacları","if/else kimi ağac strukturu.",10), L("k-NN","Ən yaxın k qonşuya bax.",9)]},
        ]
    },
    # ── RİYAZİYYAT (10 kurs) ─────────────────────────────────────────────────
    {
        "title": "Riyaziyyat: Tənliklər",
        "subtitle": "Xətti, kvadrat, tənliklər sistemi",
        "subject": "riyaziyyat", "level": "beginner", "cover_color": "#2196F3",
        "objectives": ["Xətti tənliklər", "Kvadrat tənlik", "Diskriminant", "Tənliklər sistemi"],
        "is_published": True,
        "modules": [
            {"title": "Xətti tənliklər", "lessons": [L("ax + b = 0","2x + 4 = 0 → x = -2",9), L("Tənliklər sistemi","Yerinə qoyma və toplama üsulları.",11)]},
            {"title": "Kvadrat tənliklər", "lessons": [L("ax² + bx + c = 0","D = b²-4ac, x = (-b±√D)/2a",12), L("Viyet teoremi","x₁+x₂ = -b/a, x₁·x₂ = c/a",9)]},
        ]
    },
    {
        "title": "Riyaziyyat: Funksiyalar",
        "subtitle": "Xətti, kvadratik, üstlü funksiyalar",
        "subject": "riyaziyyat", "level": "beginner", "cover_color": "#0D3B6E",
        "objectives": ["Funksiya anlayışı", "Qrafik qurmaq", "Xətti funksiya", "Parabola"],
        "is_published": True,
        "modules": [
            {"title": "Funksiya anlayışı", "lessons": [L("y = f(x)","Hər x üçün bir y — tərif.",9), L("Xətti funksiya","y = kx + b, k — maillik",10)]},
            {"title": "Kvadratik funksiya", "lessons": [L("y = ax² + bx + c","Parabola, a>0 yuxarı, a<0 aşağı",11), L("Minimun/Maksimum","Verteksin koordinatları.",9)]},
        ]
    },
    {
        "title": "Riyaziyyat: Həndəsə",
        "subtitle": "Fiqurlar, sahə, perimetr, Pifaqor",
        "subject": "riyaziyyat", "level": "beginner", "cover_color": "#1B7A4A",
        "objectives": ["Üçbucaq növləri", "Sahə hesablamaları", "Pifaqor teoremi", "Dairə"],
        "is_published": True,
        "modules": [
            {"title": "Üçbucaqlar", "lessons": [L("Növlər","Bərabərtərəfli, bərabəryanlı, ümumi",8), L("Sahə","S = a·h/2",8)]},
            {"title": "Pifaqor", "lessons": [L("a² + b² = c²","Hipotenuz hesablaması",10), L("Tətbiq","Diaqonal, hündürlük tapma",9)]},
            {"title": "Dairə", "lessons": [L("Sahə və çevrə","S = πr², C = 2πr",8)]},
        ]
    },
    {
        "title": "Riyaziyyat: Loqarifm",
        "subtitle": "Üstlü ifadələr, loqarifm xassələri",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#7C3AED",
        "objectives": ["Üstün xassələri", "Loqarifm anlayışı", "Xassələr", "Loqarifmik tənliklər"],
        "is_published": True,
        "modules": [
            {"title": "Üstlü ifadələr", "lessons": [L("Xassələr","aⁿ·aᵐ = aⁿ⁺ᵐ",9), L("Üstlü tənliklər","2ˣ = 8 → x = 3",10)]},
            {"title": "Loqarifm", "lessons": [L("Anlayış","log_a(b) = x ⟺ aˣ = b",10), L("Xassələr","log(ab) = log(a)+log(b)",9), L("Tənliklər","log₂(x) = 3 → x = 8",10)]},
        ]
    },
    {
        "title": "Riyaziyyat: Triqonometriya",
        "subtitle": "Sin, cos, tan — dərəcədən radiana",
        "subject": "riyaziyyat", "level": "intermediate", "cover_color": "#DC2626",
        "objectives": ["sin, cos, tan", "Triqonometrik eyniliklər", "Tənliklər", "Radian ölçü"],
        "is_published": True,
        "modules": [
            {"title": "Əsas anlayışlar", "lessons": [L("sin, cos, tan","Düzbucaqlı üçbucaqda nisbətlər.",11), L("Dövri cədvəl","30°, 45°, 60°, 90° dəyərləri",9)]},
            {"title": "Eyniliklər", "lessons": [L("sin²α + cos²α = 1","Pifaqor triqonometrik eynilik.",9), L("Toplama düsturları","sin(a+b) = sin(a)cos(b)+cos(a)sin(b)",10)]},
        ]
    },
    {
        "title": "Riyaziyyat: Statistika",
        "subtitle": "Verilənlər analizi, orta, ehtimal",
        "subject": "riyaziyyat", "level": "intermediate", "cover_color": "#C75B00",
        "objectives": ["Orta, median, mod", "Ehtimal əsasları", "Kombinatorika", "Diaqramlar"],
        "is_published": True,
        "modules": [
            {"title": "Statistika", "lessons": [L("Orta qiymət","Cəm ÷ Say",8), L("Median və Mod","Sıralanmış siyahının ortası vs tez-tez gələn.",9)]},
            {"title": "Ehtimal", "lessons": [L("P = m/n","0 ≤ P ≤ 1",9), L("Klassik nümunələr","Zər, kart, top çıxarma.",10)]},
        ]
    },
    {
        "title": "Riyaziyyat: Limit və Törəmə",
        "subtitle": "Diferensial hesab əsasları",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#6366F1",
        "objectives": ["Limit anlayışı", "Törəmənin tərifi", "Diferensiallaşdırma qaydaları", "Ekstremal nöqtələr"],
        "is_published": True,
        "modules": [
            {"title": "Limit", "lessons": [L("Limit anlayışı","lim(x→a) f(x) = L",10), L("Limit hesablamaları","Əvəzetmə, L'Hôpital qaydası",11)]},
            {"title": "Törəmə", "lessons": [L("Törəmənin tərifi","f'(x) = lim(Δx→0) Δy/Δx",11), L("Diferensiallaşdırma","(xⁿ)' = nxⁿ⁻¹, (sinx)' = cosx",10), L("Ekstremumlər","f'(x)=0 nöqtəsini tap.",10)]},
        ]
    },
    {
        "title": "Riyaziyyat: İntegral",
        "subtitle": "Belirsiz, müəyyən inteqral, tətbiqlər",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#0891B2",
        "objectives": ["İntegral anlayışı", "İnteqrasiya qaydaları", "Müəyyən inteqral", "Sahə hesablaması"],
        "is_published": True,
        "modules": [
            {"title": "Belirsiz inteqral", "lessons": [L("∫f(x)dx","Törəmənin əksi əməliyyatı.",10), L("Əsas düsturlar","∫xⁿdx = xⁿ⁺¹/(n+1)+C",10)]},
            {"title": "Müəyyən inteqral", "lessons": [L("Newton-Leibniz","∫ₐᵇf(x)dx = F(b)-F(a)",11), L("Sahə tətbiqi","İki əyri arasındakı sahə.",10)]},
        ]
    },
    {
        "title": "Riyaziyyat: Kompleks Ədədlər",
        "subtitle": "i² = -1 — xəyali ədədlər dünyası",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#DB2777",
        "objectives": ["Kompleks ədəd anlayışı", "Əməliyyatlar", "Modul və argument", "Euler düsturu"],
        "is_published": True,
        "modules": [
            {"title": "Kompleks ədədlər", "lessons": [L("z = a + bi","Real və xəyali hissə",9), L("Əməliyyatlar","Toplama, çıxma, vurma, bölmə",10)]},
            {"title": "Triqonometrik forma", "lessons": [L("Modul |z|","r = √(a²+b²)",9), L("Euler düsturu","eⁱˣ = cos(x) + i·sin(x)",11)]},
        ]
    },
    {
        "title": "Riyaziyyat: Vektorlar",
        "subtitle": "Koordinat sistemi, uzunluq, skalar hasili",
        "subject": "riyaziyyat", "level": "intermediate", "cover_color": "#1B7A4A",
        "objectives": ["Vektor anlayışı", "Uzunluq hesablaması", "Skalar hasili", "Proyeksiya"],
        "is_published": True,
        "modules": [
            {"title": "Vektorlar", "lessons": [L("Vektor nədir?","İstiqamətli parça — modul + istiqamət.",8), L("Koordinatlar","a = (a₁, a₂, a₃)",9)]},
            {"title": "Əməliyyatlar", "lessons": [L("Toplama","a + b = (a₁+b₁, a₂+b₂)",8), L("Skalar hasil","a·b = |a||b|cos(θ)",10), L("Vektorial hasil","c ⊥ a, c ⊥ b",10)]},
        ]
    },
]

for c in COURSES:
    try:
        res = post("/courses/teacher", c, tok)
        lc = sum(len(m["lessons"]) for m in c["modules"])
        print(f"✓ {c['title']:<45} ({c['subject']}) | {len(c['modules'])}b {lc}d")
    except Exception as e:
        print(f"✗ {c['title'][:40]} XETA: {e}")

print(f"\nCəmi {len(COURSES)} kurs yaradıldı")
