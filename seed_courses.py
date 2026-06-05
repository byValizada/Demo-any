# -*- coding: utf-8 -*-
"""3 geniş professional kurs yaradır (teacher hesabı ilə)."""
import json, urllib.request

BASE = "http://127.0.0.1:8000"

def post(path, body, token=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    return json.loads(urllib.request.urlopen(req).read())

def L(title, content, minutes, t="text", url=None):
    return {"title": title, "content": content, "lesson_type": t, "url": url, "duration_min": minutes}

# Login
tok = post("/auth/login", {"email": "turalvalizada32@gmail.com", "password": "Tural2026"})["access_token"]

COURSES = [
    {
        "title": "Sıfırdan Python Proqramlaşdırma",
        "subtitle": "Heç bir təcrübə tələb olunmur — addım-addım real proqramçı ol",
        "subject": "İnformatika",
        "level": "beginner",
        "cover_color": "#7C3AED",
        "description": "Bu kurs proqramlaşdırmanı sıfırdan öyrənmək istəyənlər üçündür. Python dünyanın ən populyar və oxunaqlı dillərindən biridir. Kursun sonunda öz kiçik proqramlarını yaza biləcəksən.",
        "objectives": [
            "Dəyişənlər və məlumat tiplərini başa düşmək",
            "Şərt operatorları və dövrlərlə işləmək",
            "Öz funksiyalarını yazmaq",
            "Siyahı, lüğət və çoxluqlardan istifadə etmək",
            "Real kiçik proqramlar qurmaq",
        ],
        "is_published": True,
        "modules": [
            {"title": "Giriş", "lessons": [
                L("Python nədir?", "**Python** — sadə sintaksisi olan, güclü və populyar proqramlaşdırma dilidir. Veb saytlar, süni intellekt, data analizi və avtomatlaşdırma üçün istifadə olunur.\n\nNiyə Python?\n- Oxunması asandır\n- Böyük cəmiyyəti var\n- Hər sahədə işlənir", 6),
                L("Mühitin qurulması", "Python ilə işləmək üçün:\n1. **python.org** saytından Python yükləyin\n2. Bir kod redaktoru quraşdırın (VS Code tövsiyə olunur)\n3. Terminalda `python --version` yazıb yoxlayın", 8),
                L("İlk proqram: Salam Dünya", "Ənənəvi ilk proqram:\n```\nprint(\"Salam, Dünya!\")\n```\n`print()` funksiyası ekrana mətn çap edir. Mətn dırnaq içində yazılır.", 7),
            ]},
            {"title": "Əsaslar", "lessons": [
                L("Dəyişənlər", "Dəyişən məlumatı saxlayan bir qutudur:\n```\nad = \"Tural\"\nyas = 16\n```\nDəyişənə istənilən vaxt yeni dəyər vermək olar.", 9),
                L("Məlumat tipləri", "Əsas tiplər:\n- **int** — tam ədəd (5, 100)\n- **float** — onluq (3.14)\n- **str** — mətn (\"salam\")\n- **bool** — doğru/yanlış (True/False)", 10),
                L("Operatorlar", "Riyazi operatorlar: `+  -  *  /  %  **`\nMüqayisə: `==  !=  <  >  <=  >=`\nMəntiqi: `and  or  not`", 8),
                L("İstifadəçidən giriş (input)", "`input()` istifadəçidən məlumat alır:\n```\nad = input(\"Adın nədir? \")\nprint(\"Salam\", ad)\n```\nDiqqət: input həmişə mətn (str) qaytarır.", 8),
            ]},
            {"title": "İdarəetmə strukturları", "lessons": [
                L("if / else şərtləri", "Şərtə görə qərar vermək:\n```\nif yas >= 18:\n    print(\"Böyük\")\nelse:\n    print(\"Kiçik\")\n```", 10),
                L("for dövrü", "Təkrarlanan əməliyyatlar üçün:\n```\nfor i in range(5):\n    print(i)\n```\nBu 0-dan 4-ə qədər çap edir.", 9),
                L("while dövrü", "Şərt doğru olduqca təkrarlanır:\n```\nn = 0\nwhile n < 3:\n    print(n)\n    n += 1\n```", 9),
                L("break və continue", "`break` dövrü dayandırır, `continue` cari addımı keçir və növbətiyə keçir.", 7),
            ]},
            {"title": "Funksiyalar", "lessons": [
                L("Funksiya nədir?", "Funksiya təkrar istifadə olunan kod bloğudur:\n```\ndef salamla():\n    print(\"Salam!\")\nsalamla()\n```", 9),
                L("Parametrlər və qaytarılan dəyər", "```\ndef topla(a, b):\n    return a + b\nnəticə = topla(3, 5)  # 8\n```\n`return` nəticəni geri qaytarır.", 10),
                L("Lokal və qlobal dəyişənlər", "Funksiya daxilində yaradılan dəyişən **lokaldır** — yalnız orada görünür. Funksiyadan kənarda yaradılan isə **qlobaldır**.", 8),
            ]},
            {"title": "Məlumat strukturları", "lessons": [
                L("Siyahılar (list)", "Siyahı bir neçə dəyəri saxlayır:\n```\nmeyvələr = [\"alma\", \"armud\"]\nmeyvələr.append(\"üzüm\")\n```", 10),
                L("Lüğətlər (dict)", "Açar-dəyər cütləri:\n```\nşagird = {\"ad\": \"Anar\", \"yas\": 15}\nprint(şagird[\"ad\"])\n```", 10),
                L("Çoxluqlar (set)", "Təkrarsız elementlər toplusu:\n```\nrənglər = {\"qırmızı\", \"mavi\", \"qırmızı\"}\n# {\"qırmızı\", \"mavi\"}\n```", 8),
            ]},
        ],
    },
    {
        "title": "Riyaziyyat: Tənliklər və Funksiyalar",
        "subtitle": "Orta məktəb riyaziyyatının əsas mövzuları aydın izahla",
        "subject": "riyaziyyat",
        "level": "intermediate",
        "cover_color": "#2196F3",
        "description": "Bu kurs tənliklər, funksiyalar və triqonometriyanın əsaslarını əhatə edir. Hər mövzu nümunələrlə izah olunur. İmtahanlara hazırlaşanlar üçün idealdır.",
        "objectives": [
            "Xətti və kvadrat tənlikləri həll etmək",
            "Funksiya anlayışını mənimsəmək",
            "Funksiya qrafiklərini qurmaq",
            "Tənliklər sistemini həll etmək",
            "Triqonometriyanın əsaslarını bilmək",
        ],
        "is_published": True,
        "modules": [
            {"title": "Tənliklər", "lessons": [
                L("Xətti tənliklər", "Xətti tənlik: **ax + b = 0**\nMisal: 2x + 4 = 0 → x = -2.\nHəll: dəyişəni bir tərəfə keçirib təcrid edirik.", 11),
                L("Kvadrat tənliklər", "Kvadrat tənlik: **ax² + bx + c = 0**\nDiskriminant: D = b² - 4ac\nKöklər: x = (-b ± √D) / 2a", 13),
                L("Tənliklər sistemi", "İki naməlumlu sistem üsulları:\n- Yerinə qoyma üsulu\n- Toplama üsulu\nNümunə ilə hər ikisini öyrənəcəyik.", 12),
            ]},
            {"title": "Funksiyalar", "lessons": [
                L("Funksiya anlayışı", "Funksiya hər bir x dəyərinə yalnız bir y dəyəri qarşı qoyan qaydadır. Yazılışı: **y = f(x)**.", 10),
                L("Xətti funksiya", "**y = kx + b** — düz xətt verir.\n- k — bucaq əmsalı (mailliyi)\n- b — y oxunu kəsdiyi nöqtə", 11),
                L("Kvadratik funksiya", "**y = ax² + bx + c** — parabola verir.\na > 0 olduqda budaqlar yuxarı, a < 0 olduqda aşağı yönəlir.", 12),
            ]},
            {"title": "Qrafiklər", "lessons": [
                L("Koordinat sistemi", "Dekart koordinat sistemi iki oxdan ibarətdir: üfüqi (x) və şaquli (y). Hər nöqtə (x, y) cütü ilə təyin olunur.", 9),
                L("Funksiya qrafikləri", "Qrafik qurmaq üçün bir neçə x dəyəri seçib uyğun y-ləri hesablayır və nöqtələri birləşdiririk.", 11),
            ]},
            {"title": "Triqonometriya", "lessons": [
                L("Sinus, kosinus, tangens", "Düzbucaqlı üçbucaqda:\n- sin = qarşı / hipotenuz\n- cos = qonşu / hipotenuz\n- tan = qarşı / qonşu", 12),
                L("Triqonometrik eyniliklər", "Əsas eynilik: **sin²α + cos²α = 1**\nBu, bütün triqonometriyanın təməlidir.", 10),
            ]},
        ],
    },
    {
        "title": "Veb Proqramlaşdırmaya Giriş",
        "subtitle": "HTML, CSS və JavaScript ilə ilk veb saytını qur",
        "subject": "İnformatika",
        "level": "beginner",
        "cover_color": "#0891B2",
        "description": "Bu kursda sıfırdan veb saytların necə qurulduğunu öyrənəcəksən. HTML ilə struktur, CSS ilə dizayn, JavaScript ilə interaktivlik yaradacaqsan.",
        "objectives": [
            "HTML ilə səhifə strukturu qurmaq",
            "CSS ilə dizayn və rəngləmə",
            "JavaScript əsaslarını öyrənmək",
            "İnteraktiv elementlər yaratmaq",
            "İlk tam veb səhifəni hazırlamaq",
        ],
        "is_published": True,
        "modules": [
            {"title": "HTML — Struktur", "lessons": [
                L("HTML nədir?", "**HTML** (HyperText Markup Language) veb səhifələrin skeletini qurur. Teqlərdən istifadə edərək başlıq, mətn, şəkil və linkləri yerləşdiririk.", 8),
                L("Teqlər və elementlər", "Teq nümunələri:\n- `<h1>` başlıq\n- `<p>` paraqraf\n- `<a>` link\n- `<img>` şəkil\nƏksər teqlər açılış və bağlanış cütü olur.", 10),
                L("Linklər və şəkillər", "Link: `<a href=\"...\">Mətn</a>`\nŞəkil: `<img src=\"...\" alt=\"təsvir\">`", 9),
                L("Cədvəllər və formalar", "Formalar istifadəçidən məlumat alır: `<input>`, `<button>`, `<form>`. Cədvəllər `<table>` ilə qurulur.", 11),
            ]},
            {"title": "CSS — Dizayn", "lessons": [
                L("CSS nədir?", "**CSS** (Cascading Style Sheets) səhifəyə rəng, şrift, boşluq və yerləşmə verir. HTML strukturdursa, CSS görünüşdür.", 8),
                L("Selektorlar", "Elementi seçmək üçün:\n- teq adı: `p { }`\n- class: `.qutu { }`\n- id: `#başlıq { }`", 10),
                L("Rəng və şriftlər", "`color` mətn rəngi, `background` fon rəngi, `font-size` şrift ölçüsü, `font-family` şrift növü.", 9),
                L("Box model", "Hər element qutudur: məzmun + `padding` + `border` + `margin`. Bunu başa düşmək yerləşdirmənin açarıdır.", 11),
                L("Flexbox ilə yerləşdirmə", "`display: flex` elementləri sətir və ya sütun üzrə asanlıqla düzür. Mərkəzləşdirmə üçün ən rahat üsuldur.", 12),
            ]},
            {"title": "JavaScript — İnteraktivlik", "lessons": [
                L("JavaScript nədir?", "**JavaScript** səhifəni canlandırır — düymə basışları, animasiyalar, məlumat yoxlanışı. Brauzerdə işləyən proqramlaşdırma dilidir.", 9),
                L("Dəyişənlər və funksiyalar", "```\nlet ad = \"Tural\";\nfunction salamla() {\n  alert(\"Salam \" + ad);\n}\n```", 11),
                L("DOM ilə işləmək", "DOM səhifənin elementlərinə kodla çatmağa imkan verir:\n```\ndocument.querySelector(\"h1\").textContent = \"Yeni başlıq\";\n```", 12),
                L("Hadisələr (events)", "İstifadəçi əməllərinə reaksiya:\n```\nbutton.addEventListener(\"click\", salamla);\n```", 10),
            ]},
        ],
    },
]

for c in COURSES:
    res = post("/courses/teacher", c, tok)
    lc = sum(len(m["lessons"]) for m in c["modules"])
    print(f"YARADILDI: {c['title']} | {len(c['modules'])} bölmə · {lc} dərs")

print("\nHamısı hazır!")
