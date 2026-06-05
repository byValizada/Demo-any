# -*- coding: utf-8 -*-
import json, urllib.request

BASE = "http://127.0.0.1:8000"

def post(path, body, token=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def L(title, content, minutes, t="text"):
    return {"title": title, "content": content, "lesson_type": t, "duration_min": minutes}

tok = post("/auth/login", {"email": "turalvalizada32@gmail.com", "password": "Tural2026"})["access_token"]

COURSES = [
    {
        "title": "Alqoritmlər və Məlumat Strukturları",
        "subtitle": "Stack, queue, ağac, qraf — əsasdan mükəmmələ",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#6366F1",
        "objectives": ["Massiv və lüğət fərqlərini başa düşmək", "Stack və Queue tətbiqləri", "Rekursiya ilə işləmək", "Axtarış alqoritmlərini bilmək"],
        "is_published": True,
        "modules": [
            {"title": "Massivlər", "lessons": [L("Massiv nədir?", "Massiv eyni tipli məlumatları ardıcıl saxlayan strukturdur.", 8), L("Dinamik massivlər", "Python-da list dinamik massivdir — lazım olduqca böyüyür.", 9)]},
            {"title": "Stack və Queue", "lessons": [L("Stack (Yığın)", "LIFO prinsipi: son gələn ilk çıxır. `append()` və `pop()`.", 8), L("Queue (Növbə)", "FIFO prinsipi: ilk gələn ilk çıxır. `collections.deque`.", 8)]},
            {"title": "Rekursiya", "lessons": [L("Rekursiv funksiyalar", "Funksiya özünü çağırır. Baza halı mütləqdir.", 10), L("Fibonacci rekursiya ilə", "f(n) = f(n-1) + f(n-2), baza: f(0)=0, f(1)=1", 9)]},
        ]
    },
    {
        "title": "Verilənlər Bazası: SQL Əsasları",
        "subtitle": "SELECT-dən JOIN-ə — real layihələr üçün SQL",
        "subject": "İnformatika", "level": "beginner", "cover_color": "#0891B2",
        "objectives": ["SQL sorğuları yazmaq", "Cədvəl yaratmaq və idarə etmək", "JOIN əməliyyatları", "Subquery istifadəsi"],
        "is_published": True,
        "modules": [
            {"title": "Giriş", "lessons": [L("SQL nədir?", "SQL — verilənlər bazası ilə danışmaq üçün dil. SELECT, INSERT, UPDATE, DELETE.", 7), L("İlk sorğu", "SELECT * FROM istifadəçilər;", 8)]},
            {"title": "Filtrasiya", "lessons": [L("WHERE şərti", "SELECT ad FROM users WHERE yas > 18;", 9), L("ORDER BY və LIMIT", "Nəticəni sıralamaq və məhdudlaşdırmaq.", 8)]},
            {"title": "JOIN", "lessons": [L("INNER JOIN", "İki cədvəldəki uyğun sətirləri birləşdirir.", 11), L("LEFT JOIN", "Sol cədvəlin hamısını saxlayır.", 10)]},
        ]
    },
    {
        "title": "Fizika: Mexanika",
        "subtitle": "Qüvvə, hərəkət, enerji — Nyuton qanunları",
        "subject": "Fizika", "level": "beginner", "cover_color": "#7C3AED",
        "objectives": ["Nyuton qanunlarını tətbiq etmək", "İmpuls və enerji hesablamaq", "Sadə maşınları başa düşmək"],
        "is_published": True,
        "modules": [
            {"title": "Kinematika", "lessons": [L("Düzxətli hərəkət", "v = s/t, a = Δv/Δt", 10), L("Serbəst düşmə", "g = 9.8 m/s², h = gt²/2", 9)]},
            {"title": "Dinamika", "lessons": [L("Nyutonun I qanunu", "Xarici qüvvə olmasa cisim hərəkət vəziyyətini saxlayır.", 9), L("Nyutonun II qanunu", "F = ma — qüvvə kütlə x təcil.", 10), L("Nyutonun III qanunu", "Hər təsirə bərabər əks-təsir var.", 8)]},
        ]
    },
    {
        "title": "İngilis Dili: A1 Başlanğıc",
        "subtitle": "Sıfırdan mükalimə qurmaq öyrən",
        "subject": "İngilis dili", "level": "beginner", "cover_color": "#C75B00",
        "objectives": ["Özünü tanıtmaq", "Günlük söz ehtiyatı", "Sadə cümlələr qurmaq", "Rəqəmlər və rənglər"],
        "is_published": True,
        "modules": [
            {"title": "Salamlaşma", "lessons": [L("Hello & Goodbye", "Hello, Hi, Good morning, Good night, Bye!", 6), L("Özünü tanıtmaq", "My name is..., I am from..., I am ... years old.", 7)]},
            {"title": "Günlük həyat", "lessons": [L("Rəqəmlər 1-100", "One, two, three... ten, twenty, hundred.", 8), L("Rənglər", "Red, blue, green, yellow, black, white.", 7), L("Ailə üzvləri", "Mother, father, sister, brother, grandmother.", 7)]},
            {"title": "Fel zamanları", "lessons": [L("Simple Present", "I eat, She eats, They play.", 10), L("Present Continuous", "I am eating, She is playing.", 10)]},
        ]
    },
    {
        "title": "Kimya: Atom və Molekullar",
        "subtitle": "Maddənin quruluşundan kimyəvi reaksiyalara",
        "subject": "Kimya", "level": "beginner", "cover_color": "#1B7A4A",
        "objectives": ["Atom modelini başa düşmək", "Dövri cədvəli oxumaq", "Kimyəvi düsturlar yazmaq"],
        "is_published": True,
        "modules": [
            {"title": "Atomun quruluşu", "lessons": [L("Proton, nötron, elektron", "Atom nüvədən və elektron buludundan ibarətdir.", 9), L("Dövri cədvəl", "118 element, dövrləri və qrupları.", 10)]},
            {"title": "Kimyəvi bağlar", "lessons": [L("Kovalent bağ", "Elektronların bölüşdürülməsi — H₂O, CO₂.", 10), L("İon bağı", "Elektronların ötürülməsi — NaCl (duz).", 9)]},
        ]
    },
    {
        "title": "Tarix: Azərbaycan Tarixi",
        "subtitle": "Qədim dövrlərdən müasir dövrə",
        "subject": "Tarix", "level": "intermediate", "cover_color": "#0D3B6E",
        "objectives": ["Azərbaycanın qədim tarixini bilmək", "Xanlıqlar dövründən bəhs etmək", "Müstəqillik tarixini başa düşmək"],
        "is_published": True,
        "modules": [
            {"title": "Qədim dövr", "lessons": [L("İlk dövlət qurumları", "Manna, Midiya, Albaniya dövlətləri.", 10), L("Atropatena", "MÖ IV əsrdə yaranmış ilk Azərbaycan dövləti.", 9)]},
            {"title": "Orta əsrlər", "lessons": [L("Ərəb işğalı", "VII əsrdə ərəb xilafəti Azərbaycanı fəth etdi.", 9), L("Səfəvilər dövləti", "I Şah İsmayıl 1501-ci ildə Səfəvilər dövlətini yaratdı.", 10)]},
            {"title": "Müasir dövr", "lessons": [L("Müstəqillik", "18 oktyabr 1991 — Azərbaycan dövlət müstəqilliyini bərpa etdi.", 8)]},
        ]
    },
    {
        "title": "Riyaziyyat: Həndəsə Əsasları",
        "subtitle": "Nöqtə, xətt, bucaqdan isbatlara",
        "subject": "riyaziyyat", "level": "beginner", "cover_color": "#2196F3",
        "objectives": ["Əsas həndəsi fiqurları tanımaq", "Perimetr və sahə hesablamaq", "Pifaqor teoremini tətbiq etmək"],
        "is_published": True,
        "modules": [
            {"title": "Planimetriya", "lessons": [L("Üçbucaq növləri", "Bərabərtərəfli, bərabəryanlı, ümumi üçbucaqlar.", 8), L("Dördbucaqlılar", "Kvadrat, düzbucaqlı, romb, paraleloqram.", 9)]},
            {"title": "Sahə hesablamaları", "lessons": [L("Üçbucaq sahəsi", "S = (a × h) / 2", 8), L("Dairə sahəsi", "S = πr²", 8)]},
            {"title": "Pifaqor teoremi", "lessons": [L("a² + b² = c²", "Düzbucaqlı üçbucaqda hipotenuzun kvadratı...", 11), L("Tətbiqlər", "Real həyatda Pifaqor teoreminin istifadəsi.", 9)]},
        ]
    },
    {
        "title": "Biologiya: Hüceyrə Biologiyası",
        "subtitle": "Həyatın əsas vahidi — hüceyrənin sirləri",
        "subject": "Biologiya", "level": "intermediate", "cover_color": "#DC2626",
        "objectives": ["Hüceyrə quruluşunu bilmək", "Mitoz və meyoz fərqini anlamaq", "DNT replikasiyasını izah etmək"],
        "is_published": True,
        "modules": [
            {"title": "Hüceyrə quruluşu", "lessons": [L("Prokaryot vs Eukaryot", "Nüvəsiz bakteriyalar vs nüvəli hüceyrələr.", 9), L("Hüceyrə orqanoidləri", "Mitoxondri, ribozom, endoplazmatik şəbəkə.", 11)]},
            {"title": "Hüceyrə bölünməsi", "lessons": [L("Mitoz", "4 mərhələ: profaza, metafaza, anafaza, telofaza.", 11), L("Meyoz", "2 bölünmə — cinsiyyət hüceyrələri üçün.", 10)]},
        ]
    },
    {
        "title": "Coğrafiya: Dünya Coğrafiyası",
        "subtitle": "Qitələr, okeanlar, iqlim qurşaqları",
        "subject": "Coğrafiya", "level": "beginner", "cover_color": "#0891B2",
        "objectives": ["Qitə və okeanları adlandırmaq", "İqlim qurşaqlarını bilmək", "Əhali coğrafiyasını başa düşmək"],
        "is_published": True,
        "modules": [
            {"title": "Qitələr", "lessons": [L("6 qitə", "Avrasiya, Afrika, Şimali Amerika, Cənubi Amerika, Avstraliya, Antarktida.", 8), L("Okeanlar", "Sakit, Atlantik, Hind, Şimal Buzlu okeanı.", 7)]},
            {"title": "İqlim", "lessons": [L("İqlim qurşaqları", "Ekvatorial, tropik, mülayim, qütb qurşaqları.", 10), L("Azərbaycanın iqlimi", "9 iqlim tipi olan yeganə ölkə.", 9)]},
        ]
    },
    {
        "title": "JavaScript: ES6+ Müasir Sintaksis",
        "subtitle": "Arrow functions, async/await, destructuring — müasir JS",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#F59E0B",
        "objectives": ["Arrow function yazımını mənimsəmək", "Promise və async/await", "Destructuring istifadəsi", "Spread operator"],
        "is_published": True,
        "modules": [
            {"title": "Yeni sintaksis", "lessons": [L("let, const vs var", "Block scope fərqi, hoisting.", 9), L("Arrow functions", "const topla = (a, b) => a + b;", 8), L("Template literals", "`Salam, ${ad}!` — string interpolasiya.", 7)]},
            {"title": "Asinxron JS", "lessons": [L("Promise", ".then() zənciri ilə asinxron əməliyyatlar.", 11), L("Async / Await", "async function yükle() { const res = await fetch(...) }", 11)]},
            {"title": "Müasir sintaksis", "lessons": [L("Destructuring", "const {ad, yas} = istifadəçi;", 9), L("Spread operator", "[...arr1, ...arr2] birləşdirmə.", 8)]},
        ]
    },
    {
        "title": "Azərbaycan Dili: Orfoqrafiya",
        "subtitle": "Düzgün yazı qaydaları — imtahanlara hazırlıq",
        "subject": "Azərbaycan dili", "level": "beginner", "cover_color": "#DB2777",
        "objectives": ["Böyük hərfin yazı qaydaları", "Söz birləşmələrinin imlası", "Durğu işarələri"],
        "is_published": True,
        "modules": [
            {"title": "Orfoqrafiya", "lessons": [L("Böyük hərflər", "Xüsusi isimlərin, cümlənin əvvəlinin yazılışı.", 8), L("Bitişik/ayrı yazılan sözlər", "Mürəkkəb sözlər: hansılar bitişik, hansılar ayrı?", 9)]},
            {"title": "Durğu işarələri", "lessons": [L("Vergül qaydaları", "Sadalama, müraciət, ara söz.", 9), L("Nöqtə və sual", "Cümlə sonlarında durğu işarələri.", 7)]},
        ]
    },
    {
        "title": "Riyaziyyat: Statistika və Ehtimal",
        "subtitle": "Verilənlər analizi, ehtimal nəzəriyyəsi",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#0D3B6E",
        "objectives": ["Orta, median, mod hesablamaq", "Ehtimalın əsas qaydaları", "Kombinatorika əsasları"],
        "is_published": True,
        "modules": [
            {"title": "Statistika", "lessons": [L("Orta qiymət", "Bütün dəyərlərin cəmini sayına bölmək.", 8), L("Median və Mod", "Median: sıralanmış siyahının ortası. Mod: ən tez-tez rast gəlinən.", 9)]},
            {"title": "Ehtimal", "lessons": [L("Ehtimal anlayışı", "P = m/n, 0 ≤ P ≤ 1", 10), L("Klassik ehtimal", "Zər atma, kart seçimi nümunələri.", 10)]},
        ]
    },
    {
        "title": "Fizika: Elektrik və Maqnetizm",
        "subtitle": "Dövrə, cərəyan, elektromaqnit induksiya",
        "subject": "Fizika", "level": "intermediate", "cover_color": "#7C3AED",
        "objectives": ["Om qanununu tətbiq etmək", "Dövrə hesablamaları", "Elektromaqnit hadisələri"],
        "is_published": True,
        "modules": [
            {"title": "Elektrostatika", "lessons": [L("Elektrik yükü", "Müsbət və mənfi yüklər, Kulon qanunu.", 10), L("Elektrik sahəsi", "E = F/q, sahə xətləri.", 9)]},
            {"title": "Cərəyan dövrəsi", "lessons": [L("Om qanunu", "I = U/R — cərəyan, gərginlik, müqavimət.", 10), L("Ardıcıl və paralel birləşmə", "Müqavimətlərin hesablanması.", 11)]},
        ]
    },
    {
        "title": "İngilis Dili: B1 Orta Səviyyə",
        "subtitle": "Mürəkkəb cümlələr, esse yazma, qrammatika",
        "subject": "İngilis dili", "level": "intermediate", "cover_color": "#C75B00",
        "objectives": ["Past Perfect istifadəsi", "Conditional cümlələr", "Essay strukturu", "Academic söz ehtiyatı"],
        "is_published": True,
        "modules": [
            {"title": "Qrammatika", "lessons": [L("Past Perfect", "I had finished before she arrived.", 10), L("Conditional Type 1 & 2", "If I study, I will pass. / If I studied, I would pass.", 11)]},
            {"title": "Yazı bacarıqları", "lessons": [L("Essay quruluşu", "Giriş, əsas hissə (2-3 abzas), nəticə.", 9), L("Formal writing", "Dear Sir/Madam, I am writing to...", 8)]},
        ]
    },
    {
        "title": "Kompüter Şəbəkələri",
        "subtitle": "TCP/IP, DNS, HTTP — internetin arxasında nə var?",
        "subject": "İnformatika", "level": "intermediate", "cover_color": "#6366F1",
        "objectives": ["OSI modelini bilmək", "IP ünvanlama", "HTTP protokolu", "DNS necə işləyir"],
        "is_published": True,
        "modules": [
            {"title": "OSI Modeli", "lessons": [L("7 qat", "Fiziki, kanal, şəbəkə, nəqliyyat, sessiya, təsvir, tətbiq.", 11), L("TCP vs UDP", "Etibarlı vs sürətli ötürmə.", 9)]},
            {"title": "İnternet protokolları", "lessons": [L("IP ünvanlama", "IPv4: 192.168.1.1 — 4 oktet, 0-255.", 9), L("DNS", "Domain adları IP ünvanlara çevrilir.", 8), L("HTTP/HTTPS", "GET, POST, status kodları: 200, 404, 500.", 10)]},
        ]
    },
    {
        "title": "Biologiya: İnsan Anatomiyası",
        "subtitle": "Orqan sistemlərindən beyin quruluşuna",
        "subject": "Biologiya", "level": "intermediate", "cover_color": "#DC2626",
        "objectives": ["Orqan sistemlərini adlandırmaq", "Qan dövranını izah etmək", "Sinir sisteminin işini başa düşmək"],
        "is_published": True,
        "modules": [
            {"title": "Qan-damar sistemi", "lessons": [L("Ürək quruluşu", "4 kamera: 2 mədəcik, 2 qulaqcıq.", 10), L("Kiçik və böyük qan dövranı", "Ağciyər vs sistemik dövran.", 9)]},
            {"title": "Sinir sistemi", "lessons": [L("Neyron quruluşu", "Cisim, akson, dendrit — sinir impulsu.", 10), L("Mərkəzi sinir sistemi", "Beyin: böyük beyin, kiçik beyin, uzunsov beyin.", 11)]},
        ]
    },
    {
        "title": "Riyaziyyat: Loqarifm və Eksponent",
        "subtitle": "Üstlü ifadələr, loqarifm xassələri, tənliklər",
        "subject": "riyaziyyat", "level": "advanced", "cover_color": "#2196F3",
        "objectives": ["Üstlü tənlikləri həll etmək", "Loqarifm xassələrini tətbiq etmək", "Loqarifmik tənliklər"],
        "is_published": True,
        "modules": [
            {"title": "Üstlü ifadələr", "lessons": [L("Üstün xassələri", "aⁿ · aᵐ = aⁿ⁺ᵐ, (aⁿ)ᵐ = aⁿᵐ", 9), L("Üstlü tənliklər", "2ˣ = 8 → x = 3", 10)]},
            {"title": "Loqarifm", "lessons": [L("Loqarifm anlayışı", "log_a(b) = x ⟺ aˣ = b", 10), L("Loqarifmin xassələri", "log(ab) = log(a) + log(b)", 9), L("Loqarifmik tənliklər", "log₂(x) = 3 → x = 8", 10)]},
        ]
    },
    {
        "title": "Ədəbiyyat: Azərbaycan Klassikləri",
        "subtitle": "Nizami, Füzuli, Vaqif — şeir dünyası",
        "subject": "Azərbaycan dili", "level": "beginner", "cover_color": "#DB2777",
        "objectives": ["Nizami Gəncəvinin həyatını bilmək", "Füzulinin qəzəllərini təhlil etmək", "Klassik şeir formalarını tanımaq"],
        "is_published": True,
        "modules": [
            {"title": "Nizami Gəncəvi", "lessons": [L("Həyatı", "1141-1209, Gəncə — dünya ədəbiyyatının dahisi.", 8), L("Xəmsə", "Sirlər xəzinəsi, Xosrov və Şirin, Leyli və Məcnun...", 10)]},
            {"title": "Füzuli", "lessons": [L("Həyatı", "1494-1556, Kərbəla — üç dildə yazan şair.", 8), L("Lirik şeirləri", "Su qəsidəsi, Leyli və Məcnun poeması.", 9)]},
            {"title": "Molla Pənah Vaqif", "lessons": [L("Realist şair", "XVIII əsr, xalq dilinə yaxın şeir dili.", 8)]},
        ]
    },
    {
        "title": "Coğrafiya: Azərbaycanın Təbiəti",
        "subtitle": "Relyef, çaylar, göllər, meşələr",
        "subject": "Coğrafiya", "level": "beginner", "cover_color": "#1B7A4A",
        "objectives": ["Azərbaycanın relyef formalarını bilmək", "Əsas çay və gölləri adlandırmaq", "Torpaq tiplərini tanımaq"],
        "is_published": True,
        "modules": [
            {"title": "Relyef", "lessons": [L("Dağlar", "Böyük Qafqaz, Kiçik Qafqaz, Talış dağları.", 9), L("Ovalıqlar", "Kür-Araz, Mil, Muğan, Salyan düzənlikləri.", 8)]},
            {"title": "Su ehtiyatları", "lessons": [L("Çaylar", "Kür, Araz, Həkəri — əsas çaylar.", 8), L("Xəzər dənizi", "Dünyanın ən böyük qapalı su hövzəsi.", 9)]},
        ]
    },
    {
        "title": "Psixologiya: Emosional İntellekt",
        "subtitle": "Özünü tanı, hissləri idarə et, empati inkişaf etdir",
        "subject": "Digər", "level": "beginner", "cover_color": "#0891B2",
        "objectives": ["EQ nədir başa düşmək", "Özünü tənzimləmə", "Sosial bacarıqlar", "Empatiya inkişafı"],
        "is_published": True,
        "modules": [
            {"title": "EQ əsasları", "lessons": [L("EQ vs IQ", "Emosional intellekt akademik intellektdən daha güclü proqnozlaşdırıcıdır.", 9), L("4 komponentin", "Özünüdərk, özünütənzimləmə, sosial fərasət, münasibət.", 8)]},
            {"title": "Praktik bacarıqlar", "lessons": [L("Stresslə mübarizə", "Dərin nəfəs alma, meditasiya, fiziki aktivlik.", 8), L("Empati inkişafı", "Aktiv dinləmə, başqasının baxış bucağından görmək.", 9), L("Münaqişə həlli", "Win-win münaqişə həlli strategiyaları.", 10)]},
        ]
    },
]

for c in COURSES:
    try:
        res = post("/courses/teacher", c, tok)
        lc = sum(len(m["lessons"]) for m in c["modules"])
        print(f"✓ {c['title'][:45]:<45} | {len(c['modules'])}b · {lc}d")
    except Exception as e:
        print(f"✗ {c['title'][:45]} XETA: {e}")

print(f"\nCəmi: {len(COURSES)} kurs yaradıldı")
