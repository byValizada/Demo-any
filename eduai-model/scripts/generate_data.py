"""
EduAI — Avtomatik Məlumat Generatoru
======================================
Azərbaycan məktəb fənləri üzrə train məlumatı yaradır.
Xarici API lazım deyil — hər şey daxildir.

İstifadə: python generate_data.py
Nəticə:   data/raw/generated_data.jsonl  (~5000+ nümunə)
"""

import json
import random
from pathlib import Path

OUT_FILE = Path(__file__).parent.parent / "data" / "raw" / "generated_data.jsonl"

SYSTEM = (
    "Sən EduAI platformasının AI müəllimsən. "
    "Azərbaycan məktəb şagirdlərinə və müəllimlərinə kömək edirsən. "
    "Həmişə Azərbaycan dilində cavab verirsən. "
    "Dəqiq, aydın və təhsilə uyğun cavablar verirsən."
)

def make(user: str, assistant: str) -> dict:
    return {"messages": [
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": user},
        {"role": "assistant", "content": assistant},
    ]}

# ═══════════════════════════════════════════════════════════════
# RİYAZİYYAT
# ═══════════════════════════════════════════════════════════════

def math_data() -> list[dict]:
    data = []

    # Toplama/Çıxma məsələləri (1-4 sinif)
    for _ in range(80):
        a, b = random.randint(1, 999), random.randint(1, 999)
        op = random.choice(["+", "-"])
        if op == "+":
            data.append(make(
                f"{a} + {b} = ?",
                f"**{a} + {b} = {a+b}**\n\nBu sadə toplama əməliyyatıdır.\n{a} + {b} = **{a+b}**"
            ))
        else:
            if a < b: a, b = b, a
            data.append(make(
                f"{a} - {b} = ?",
                f"**{a} - {b} = {a-b}**\n\nBu sadə çıxma əməliyyatıdır.\n{a} - {b} = **{a-b}**"
            ))

    # Vurma/Bölmə
    for _ in range(60):
        a = random.randint(2, 12)
        b = random.randint(2, 12)
        data.append(make(
            f"{a} × {b} = ?",
            f"**{a} × {b} = {a*b}**\n\nVurma cədvəlinə görə:\n{a} × {b} = **{a*b}**"
        ))
        c = a * b
        data.append(make(
            f"{c} ÷ {a} = ?",
            f"**{c} ÷ {a} = {b}**\n\nBölmə əməliyyatı:\n{c} ÷ {a} = **{b}**\n\nYoxlama: {b} × {a} = {c} ✓"
        ))

    # İkinci dərəcəli tənliklər
    quadratics = [
        ("x² - 5x + 6 = 0", "x₁=2, x₂=3", "(x-2)(x-3)=0 → x=2 və ya x=3"),
        ("x² - 7x + 12 = 0", "x₁=3, x₂=4", "(x-3)(x-4)=0 → x=3 və ya x=4"),
        ("x² + 5x + 6 = 0", "x₁=-2, x₂=-3", "(x+2)(x+3)=0 → x=-2 və ya x=-3"),
        ("x² - 4 = 0", "x₁=2, x₂=-2", "x²=4 → x=±2"),
        ("x² - 9 = 0", "x₁=3, x₂=-3", "x²=9 → x=±3"),
        ("2x² - 8 = 0", "x₁=2, x₂=-2", "x²=4 → x=±2"),
        ("x² - 3x = 0", "x₁=0, x₂=3", "x(x-3)=0 → x=0 və ya x=3"),
        ("x² + 4x + 4 = 0", "x=-2 (ikiqat kök)", "(x+2)²=0 → x=-2"),
    ]
    for eq, roots, method in quadratics:
        data.append(make(
            f"İkinci dərəcəli tənliyi həll et: {eq}",
            f"**{eq}**\n\n**Həll:** {method}\n\n**Köklər:** {roots}"
        ))

    # Faiz məsələləri
    for _ in range(40):
        total = random.choice([100, 200, 250, 500, 1000])
        pct = random.choice([10, 20, 25, 30, 40, 50, 75])
        result = total * pct // 100
        data.append(make(
            f"{total}-in {pct}%-i neçədir?",
            f"**{total}-in {pct}%-i = {result}**\n\nHesablama:\n{total} × {pct}/100 = {total} × 0.{pct:02d} = **{result}**"
        ))

    # Kəsrlər
    fractions = [
        ("1/2 + 1/3", "5/6", "3/6 + 2/6 = 5/6"),
        ("1/4 + 1/4", "1/2", "2/4 = 1/2"),
        ("3/4 - 1/4", "1/2", "2/4 = 1/2"),
        ("2/3 + 1/6", "5/6", "4/6 + 1/6 = 5/6"),
        ("1/2 × 1/3", "1/6", "1×1 / 2×3 = 1/6"),
        ("3/4 × 2/3", "1/2", "6/12 = 1/2"),
        ("1/2 ÷ 1/4", "2", "1/2 × 4/1 = 4/2 = 2"),
    ]
    for expr, result, method in fractions:
        data.append(make(
            f"Kəsri hesabla: {expr}",
            f"**{expr} = {result}**\n\nHəll: {method}"
        ))

    # Həndəsə
    geometry = [
        ("Düzbucaqlının sahəsini tap: uzunluq=8 sm, en=5 sm",
         "**S = uzunluq × en = 8 × 5 = 40 sm²**\n\nDüstur: S = a × b\nS = 8 × 5 = **40 sm²**"),
        ("Kvadratın perimetrini tap: tərəf=6 sm",
         "**P = 4 × tərəf = 4 × 6 = 24 sm**\n\nDüstur: P = 4a\nP = 4 × 6 = **24 sm**"),
        ("Üçbucağın sahəsini tap: əsas=10 sm, hündürlük=6 sm",
         "**S = (əsas × hündürlük) / 2 = (10 × 6) / 2 = 30 sm²**\n\nDüstur: S = (a × h) / 2"),
        ("Dairənin sahəsini tap: r=7 sm (π≈3.14)",
         "**S = π × r² = 3.14 × 49 = 153.86 sm²**\n\nDüstur: S = πr²\nS = 3.14 × 7² = 3.14 × 49 = **153.86 sm²**"),
        ("Dairənin uzunluğunu tap: r=5 sm",
         "**C = 2πr = 2 × 3.14 × 5 = 31.4 sm**\n\nDüstur: C = 2πr"),
    ]
    for q, a in geometry:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# FİZİKA
# ═══════════════════════════════════════════════════════════════

def physics_data() -> list[dict]:
    data = []

    concepts = [
        ("Sürət nədir?",
         "**Sürət** — cismin vahid zamanda qət etdiyi yoldur.\n\n**Düstur:** v = s/t\n- v = sürət (m/s)\n- s = yol (m)\n- t = zaman (s)\n\n**Nümunə:** Avtomobil 100 m yolu 10 s-də qət edir.\nv = 100/10 = **10 m/s**"),

        ("Nyutonun 1-ci qanunu nədir?",
         "**Nyutonun 1-ci qanunu (Ətalət qanunu):**\n\nXarici qüvvənin təsiri olmadıqda cisim ya sükunətdə qalır, ya da düzxətli bərabərsürətli hərəkət edir.\n\n**Sadə dillə:** Cisim öz vəziyyətini saxlamağa çalışır.\n\n**Nümunə:**\n- Avtomobil əyiləndə sürücü irəli gedir (ətalət)\n- Süfrə sürüşdürüldükdə qablar yerindən tərpənmir"),

        ("Nyutonun 2-ci qanunu nədir?",
         "**Nyutonun 2-ci qanunu:**\n\n**Düstur:** F = m × a\n- F = qüvvə (N — Nyuton)\n- m = kütlə (kq)\n- a = sürətlənmə (m/s²)\n\n**Nümunə:** 5 kq cisimə 20 N qüvvə təsir edir.\na = F/m = 20/5 = **4 m/s²**"),

        ("Nyutonun 3-cü qanunu nədir?",
         "**Nyutonun 3-cü qanunu:**\n\nHər fəaliyyətə bərabər, əks istiqamətli əks-fəaliyyət uyğun gəlir.\n\n**Sadə dillə:** Hər itələmə əks istiqamətdə eyni güclə cavab alır.\n\n**Nüm ünələr:**\n- Raket: qaz aşağı → raket yuxarı\n- Üzmə: əl suyu geri itələyir → bədən irəli gedir\n- Top: yerdən sıçrayır"),

        ("İş nədir? Düsturu nədir?",
         "**Mexaniki İş:**\n\n**Düstur:** A = F × s × cos(α)\n- A = iş (C — Cuol)\n- F = qüvvə (N)\n- s = yerdəyişmə (m)\n- α = qüvvə ilə yerdəyişmə arasındakı bucaq\n\n**Ən sadə hal** (α=0°): A = F × s\n\n**Nümunə:** 10 N qüvvə ilə cismi 5 m irəli çəkirik.\nA = 10 × 5 = **50 C**"),

        ("Enerjinin saxlanması qanunu nədir?",
         "**Enerjinin saxlanması qanunu:**\n\nQapalı sistemdə enerji yaranmır və yox olmur — yalnız bir formadan digərinə çevrilir.\n\n**Nümunə:**\n- Çağlayan: potensial enerji → kinetik enerji → elektrik enerjisi\n- Qaynayan su: istilik enerjisi → kinetik enerji (buxar)\n\n**Mexaniki enerjinin saxlanması:**\nEk + Ep = const\n½mv² + mgh = const"),

        ("Ohm qanunu nədir?",
         "**Ohm Qanunu:**\n\n**Düstur:** I = U/R\n- I = cərəyan (A — Amper)\n- U = gərginlik (V — Volt)\n- R = müqavimət (Ω — Om)\n\n**Nümunə:** 12V gərginlik, 4Ω müqavimət\nI = 12/4 = **3 A**\n\n**Üçbucaq qaydası:** U=IR, I=U/R, R=U/I"),

        ("Dalğa uzunluğu nədir?",
         "**Dalğa uzunluğu (λ)** — dalğanın bir tam dövrünün uzunluğudur.\n\n**Düstur:** λ = v/f\n- λ = dalğa uzunluğu (m)\n- v = yayılma sürəti (m/s)\n- f = tezlik (Hz)\n\n**Nümunə:** Sürət 340 m/s, tezlik 170 Hz\nλ = 340/170 = **2 m**"),
    ]

    for q, a in concepts:
        data.append(make(q, a))

    # Hesablama məsələləri
    problems = [
        ("Cisim 60 m yolu 12 s-də qət edir. Sürəti tapın.",
         "**Verilən:** s = 60 m, t = 12 s\n**Tapmaq:** v = ?\n\n**Düstur:** v = s/t\n\n**Həll:** v = 60/12 = **5 m/s**"),
        ("10 kq kütlə 30 N qüvvə ilə itələnir. Sürətlənməni tapın.",
         "**Verilən:** m = 10 kq, F = 30 N\n**Tapmaq:** a = ?\n\n**Düstur:** a = F/m\n\n**Həll:** a = 30/10 = **3 m/s²**"),
        ("Gərginlik 220V, cərəyan 2A. Müqaviməti tapın.",
         "**Verilən:** U = 220 V, I = 2 A\n**Tapmaq:** R = ?\n\n**Düstur:** R = U/I\n\n**Həll:** R = 220/2 = **110 Ω**"),
    ]
    for q, a in problems:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# KİMYA
# ═══════════════════════════════════════════════════════════════

def chemistry_data() -> list[dict]:
    data = []

    concepts = [
        ("Atom nədir?",
         "**Atom** — maddənin ən kiçik hissəciyi, kimyəvi üsullarla daha kiçik hissələrə bölünmür.\n\n**Atom quruluşu:**\n- **Nüvə** (mərkəz): protonlar (+) + neytronlar (0)\n- **Elektron buludu**: elektronlar (-)\n\n**Ölçüsü:** ~10⁻¹⁰ m (çox kiçikdir!)\n\n**Nümunə:** Hidrogen atomu — 1 proton, 1 elektron"),

        ("Kimyəvi element nədir?",
         "**Kimyəvi element** — eyni nüvə yükünə (proton sayına) malik atomların məcmusudur.\n\n**Yer kürəsindəki elementlər:** 118\n\n**Nümunələr:**\n- Hidrogen (H) — 1 proton\n- Karbon (C) — 6 proton\n- Oksigen (O) — 8 proton\n- Dəmir (Fe) — 26 proton\n\nMendeleyev cədvəlindən tapıla bilər."),

        ("Fotosintezin kimyəvi tənliyi",
         "**Fotosintez tənliyi:**\n\n6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂\n\n**Azərbaycan dili ilə:**\nKarbon dioksid + Su → Qlükoza + Oksigen\n\n**Şərt:** Günəş işığı + Xlorofil\n\n**Bu tənlik tarazlıdır:** Hər tərəfdə 6C, 12H, 18O var."),

        ("Su molekulu necə yazılır?",
         "**Su:** H₂O\n\n**Quruluş:**\n- 2 hidrogen atomu\n- 1 oksigen atomu\n\n**Xassələri:**\n- Həlledici (poliqəbulçu)\n- Qaynama nöqtəsi: 100°C\n- Donma nöqtəsi: 0°C\n- Sıxlıq: 1 q/sm³ (20°C-də)"),

        ("Turşu nədir? Nümunə ver.",
         "**Turşu** — suda həll olduqda H⁺ ion verən maddədir.\n\n**Xüsusiyyətləri:**\n- pH < 7\n- Turş dad\n- Lakmusu qırmızıya çevirir\n- Metallarla reaksiyaya girir\n\n**Nümunələr:**\n- HCl — xlorid turşusu (duz turşusu)\n- H₂SO₄ — sulfat turşusu\n- HNO₃ — nitrat turşusu\n- CH₃COOH — sirkə turşusu"),

        ("Əsas (qələvi) nədir?",
         "**Əsas (qələvi)** — suda həll olduqda OH⁻ ion verən maddədir.\n\n**Xüsusiyyətləri:**\n- pH > 7\n- Sabunvari hiss\n- Lakmusu mavi rəngə çevirir\n\n**Nümunələr:**\n- NaOH — natrium hidroksid (kaustik soda)\n- Ca(OH)₂ — kalsium hidroksid (söndürülmüş əhəng)\n- NH₃ — ammonyak"),
    ]

    for q, a in concepts:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# BİOLOGİYA
# ═══════════════════════════════════════════════════════════════

def biology_data() -> list[dict]:
    data = []

    concepts = [
        ("Hüceyra nədir?",
         "**Hüceyra** — bütün canlıların əsas quruluş vahididir.\n\n**Hüceyra nəzəriyyəsi:**\n1. Bütün canlılar hüceyradən ibarətdir\n2. Hüceyra həyatın əsas vahididir\n3. Hüceyralar yalnız hüceyradan yaranır\n\n**Hüceyra hissələri:**\n- **Nüvə** — irsiyyət mərkəzi (DNT)\n- **Sitoplazma** — daxili maye\n- **Membran** — xarici qişa\n- **Mitoxondriya** — enerji (ATP)"),

        ("DNT nədir?",
         "**DNT (Deoksiribonuklein turşusu):**\n\nİrsiyyət məlumatını saxlayan molekuldur.\n\n**Quruluş:** İkiqat sarmal (2 zəncir)\n\n**Nukliotidlər (4 əsas):**\n- Adenin (A)\n- Timin (T)\n- Quanin (Q)\n- Sitozin (S)\n\n**Cütləşmə qaydası:** A-T, Q-S\n\n**Funksiyası:** Protein sintezini idarə edir, nəslə ötürülür."),

        ("Fotosintez nədir?",
         "**Fotosintez** — yaşıl bitkilərin işıq enerjisindən istifadə edərək üzvi maddə sintez etməsidir.\n\n**Tənlik:** 6CO₂ + 6H₂O + işıq → C₆H₁₂O₆ + 6O₂\n\n**Yerləşmə:** Xloroplastda (xlorofil)\n\n**İki mərhələ:**\n1. **İşıq mərhələsi** — ATP yaranır\n2. **Qaranlıq mərhələsi** — qlükoza yaranır\n\n**Əhəmiyyəti:** O₂ istehsalı, üzvi maddə sintezi"),

        ("Tənəffüs nədir?",
         "**Tənəffüs** — üzvi maddənin parçalanması ilə enerji (ATP) alınması prosesidir.\n\n**Ümumi tənlik:**\nC₆H₁₂O₆ + 6O₂ → 6CO₂ + 6H₂O + 38ATP\n\n**Növləri:**\n- **Aerob** (oksigenli): tam parçalanma, 38 ATP\n- **Anaerob** (oksigensiz): natamam, 2 ATP + laktik turşu\n\n**Fotosintezdən fərqi:** Tənəffüs enerji sərf etmir, istehsal edir."),

        ("İnsan qanının funksiyaları nələrdir?",
         "**Qanın funksiyaları:**\n\n🔴 **Nəqliyyat:**\n- O₂ daşıyır (eritrositlər)\n- CO₂ daşıyır\n- Qida maddələri daşıyır\n- Hormonları daşıyır\n\n🛡️ **Müdafiə:**\n- Leykositlər mikroorqanizmlərə qarşı\n- Antitellər\n\n⚖️ **Tənzimləmə:**\n- İstilik tarazlığı\n- pH tənzimlənməsi\n- Su-duz balansı\n\n**Qan hissələri:** Eritrositlər (qırmızı) + Leykositlər (ağ) + Trombositlər + Plazma"),
    ]

    for q, a in concepts:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# TARİX
# ═══════════════════════════════════════════════════════════════

def history_data() -> list[dict]:
    data = []

    events = [
        ("Azərbaycan nə vaxt müstəqillik qazandı?",
         "**Azərbaycan müstəqilliyi:**\n\n📅 **Tarix:** 18 oktyabr 1991\n\n**Azərbaycan Respublikasının Dövlət Müstəqilliyi haqqında Konstitusiya Aktı** SSRİ dağılanadək qəbul edildi.\n\n**Əsas hadisələr:**\n- 28 may 1918 — Azərbaycan Xalq Cümhuriyyəti (ilk müstəqillik)\n- 28 aprel 1920 — Sovet işğalı\n- 18 oktyabr 1991 — Yenidən müstəqillik\n\n**İlk prezident:** Ayaz Mütəllibov (1991), sonra Heydər Əliyev (1993-2003)"),

        ("Birinci Dünya Müharibəsi nə vaxt başladı?",
         "**Birinci Dünya Müharibəsi:**\n📅 **Başlanğıc:** 28 iyul 1914\n📅 **Son:** 11 noyabr 1918\n\n**Səbəb:** Avstriya şahzadəsi Frans Ferdinandın öldürülməsi (28 iyun 1914, Sarayevo)\n\n**İki blok:**\n- Antanta: Fransa, Britaniya, Rusiya, sonra ABŞ\n- Üçlər İttifaqı: Almaniya, Avstriya-Macarıstan, Osmanlı\n\n**Nəticə:** ~20 mln ölü, 4 imperiya dağıldı, Versay müqaviləsi"),

        ("İkinci Dünya Müharibəsi haqqında məlumat ver.",
         "**İkinci Dünya Müharibəsi:**\n📅 **1939-1945**\n\n**Başlanğıc:** 1 sentyabr 1939 — Almaniyanın Polşaya hücumu\n\n**İki blok:**\n- Hitlerin Almaniyası, Yaponiya, İtaliya (Ox dövlətləri)\n- SSRİ, ABŞ, Britaniya, Fransa (Müttəfiqləri)\n\n**Əsas döyüşlər:**\n- Stalinqrad döyüşü (1942-43) — dönüş nöqtəsi\n- Normandiya çıxarılması (1944)\n\n**Son:** 8 may 1945 (Avropa), 2 sentyabr 1945 (Yaponiya)\n\n**İtki:** ~70-85 mln insan"),

        ("Xilafət nədir?",
         "**Xilafət** — İslamda Məhəmməd peyğəmbərin vəfatından sonra müsəlman dövlətinin idarəetmə formasıdır.\n\n**Xəlifə** — dövlət başçısı\n\n**Əsas xilafətlər:**\n- Raşidin xilafəti (632-661)\n- Əməvilər (661-750)\n- Abbasilər (750-1258)\n- Osmanlı sultanları (1517-1924)\n\n**Son:** 1924-cü ildə Türkiyə tərəfindən ləğv edildi"),

        ("Azərbaycan Xalq Cümhuriyyəti haqqında məlumat ver.",
         "**Azərbaycan Xalq Cümhuriyyəti (AXC):**\n\n📅 **28 may 1918 — 28 aprel 1920**\n\n**Əhəmiyyəti:**\n- Müsəlman Şərqinin **ilk demokratik respublikası**\n- Qadınlara seçki hüququ verildi (dünyada ilklərdən)\n- Azərbaycan dili dövlət dili elan edildi\n- Bakı Dövlət Universiteti açıldı (1919)\n\n**Süqut səbəbi:** 1920-ci ildə Sovet Rusiyasının işğalı\n\n**Liderlər:** Məmməd Əmin Rəsulzadə (milli lider)"),
    ]

    for q, a in events:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# İNGİLİS DİLİ
# ═══════════════════════════════════════════════════════════════

def english_data() -> list[dict]:
    data = []

    # Qrammatika
    grammar = [
        ("Present Simple zamanı nə vaxt işlədilir?",
         "**Present Simple (İndiki Sadə Zaman):**\n\n**İşlədilmə yerləri:**\n1. Adət, vərdiş: *I drink coffee every morning.*\n2. Daimi həqiqət: *The sun rises in the east.*\n3. Cədvəl/proqram: *The train leaves at 9.*\n\n**Forma:**\n- (+) I/You/We/They **work** | He/She/It **works**\n- (-) I **don't work** | He **doesn't work**\n- (?) **Do** you work? | **Does** he work?\n\n**Azərbaycanca:** Məktəbə hər gün gedirəm → I go to school every day."),

        ("Past Simple zamanı necə istifadə edilir?",
         "**Past Simple (Keçmiş Sadə Zaman):**\n\n**İşlədilmə:** Keçmişdə başa çatmış iş\n\n**Forma:**\n- Düzgün fellər: work → **worked**, play → **played**\n- Düzgün olmayan fellər: go → **went**, see → **saw**, eat → **ate**\n\n**Cümlə quruluşu:**\n- (+) She **visited** London yesterday.\n- (-) She **didn't visit** London.\n- (?) **Did** she visit London?\n\n**Azərbaycanca:** Dünən kitab oxudum → I **read** a book yesterday."),

        ("\"to be\" felinin Present Simple-da forması",
         "**TO BE — Present Simple:**\n\n| Şəxs | Forma |\n|------|-------|\n| I | **am** |\n| You | **are** |\n| He/She/It | **is** |\n| We/They | **are** |\n\n**Nümunələr:**\n- I **am** a student.\n- She **is** happy.\n- They **are** teachers.\n\n**Qısaltma:** I'm, You're, He's, She's, It's, We're, They're"),
    ]

    for q, a in grammar:
        data.append(make(q, a))

    # Söz tərcümələri
    words = [
        ("school", "məktəb"), ("teacher", "müəllim"), ("student", "şagird"),
        ("book", "kitab"), ("pencil", "qələm"), ("notebook", "dəftər"),
        ("house", "ev"), ("family", "ailə"), ("mother", "ana"), ("father", "ata"),
        ("friend", "dost"), ("water", "su"), ("food", "yemək"), ("time", "vaxt"),
        ("day", "gün"), ("night", "gecə"), ("morning", "səhər"), ("evening", "axşam"),
        ("happy", "xoşbəxt"), ("sad", "kədərli"), ("big", "böyük"), ("small", "kiçik"),
    ]

    for eng, az in words:
        data.append(make(
            f"\"{eng}\" sözünün Azərbaycanca tərcüməsi nədir?",
            f"**{eng}** → **{az}**\n\n**Cümlə nümunəsi:**\nI have a {eng}. → Mənim bir {az}im var."
        ))
        data.append(make(
            f"\"{az}\" sözünün İngilis dilindəki qarşılığı nədir?",
            f"**{az}** → **{eng}**\n\n**Nümunə:**\nThe {eng} is here. → {az.capitalize()} buradadır."
        ))

    return data


# ═══════════════════════════════════════════════════════════════
# AZƏRBAYCAN DİLİ
# ═══════════════════════════════════════════════════════════════

def azerbaijani_data() -> list[dict]:
    data = []

    grammar = [
        ("İsim nədir? Nümunə ver.",
         "**İsim** — əşya, canlı, yer, anlayışı bildirən söz növüdür.\n\n**Sualları:** kim? nə? hara?\n\n**Növləri:**\n- **Xüsusi isimlər:** Bakı, Əli, Kür (böyük hərflə)\n- **Ümumi isimlər:** şəhər, adam, çay (kiçik hərflə)\n\n**Nümunələr:** kitab, ev, müəllim, Azərbaycan, dostluq, sevgi"),

        ("Sifət nədir? Hansı suallara cavab verir?",
         "**Sifət** — əşyanın əlamətini, keyfiyyətini bildirən söz növüdür.\n\n**Sualları:** necə? nə cür? neçənci?\n\n**Növləri:**\n- **Keyfiyyət sifəti:** gözəl, böyük, ağ, sürətli\n- **Nisbi sifət:** taxta (stul), dəmir (qapı)\n\n**Dərəcələr:**\n- Adi: böyük\n- Azaltma: balacaca\n- Çoxaltma: çox böyük / ən böyük"),

        ("Fel nədir? Növlərini say.",
         "**Fel** — hərəkəti, işi, vəziyyəti bildirən söz növüdür.\n\n**Sualları:** nə etmək? nə etdi? nə edir?\n\n**Növləri (növ kateqoriyası):**\n- **Məlum növ:** Adam işləyir. (feil kim tərəfindən icra edilir məlumdur)\n- **Məchul növ:** Kitab oxunur. (icraçı naməlumdur)\n- **Qayıdış növ:** O, yuyunur. (özünə icra)\n- **Şərik növ:** Onlar görüşürlər.\n- **İcbar növ:** Müəllim yazdırdı."),

        ("Cümləni ayrıştır: \"Müəllim dəftəri şagirdə verdi.\"",
         "**Cümlə: Müəllim dəftəri şagirdə verdi.**\n\n**Üzvlər:**\n- **Mübtəda:** Müəllim (kim?)\n- **Xəbər:** verdi (nə etdi?)\n- **Tamamlıq:** dəftəri (nəyi?)\n- **Tamamlıq:** şagirdə (kimə?)\n\n**Söz növləri:**\n- Müəllim — isim\n- dəftəri — isim\n- şagirdə — isim\n- verdi — fel"),
    ]

    for q, a in grammar:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# SUAL GENERASİYASI
# ═══════════════════════════════════════════════════════════════

def question_gen_data() -> list[dict]:
    data = []

    tests = [
        ("Riyaziyyat, 6-cı sinif, mövzu: Tam ədədlər üzrə 3 test sualı yarat",
         "**6-cı sinif Riyaziyyat — Tam Ədədlər**\n\n**Sual 1** (Asan)\n-5 + 3 = ?\nA) -8  B) -2  C) 2  D) 8\n✅ **B) -2**\n\n**Sual 2** (Orta)\n(-4) × (-3) = ?\nA) -12  B) -7  C) 7  D) 12\n✅ **D) 12** *(mənfi × mənfi = müsbət)*\n\n**Sual 3** (Çətin)\nHansı ədəd |-7|-dən böyükdür?\nA) 6  B) 7  C) -8  D) -9\n✅ **C) -8** *( |-8| = 8 > 7)*"),

        ("Fizika, 9-cu sinif, mövzu: Elektrik üzrə 3 test sualı yarat",
         "**9-cu sinif Fizika — Elektrik**\n\n**Sual 1**\nMüqavimət 5Ω, cərəyan 2A. Gərginlik neçədir?\nA) 2,5 V  B) 7 V  C) 10 V  D) 15 V\n✅ **C) 10 V** *(U = I×R = 2×5 = 10V)*\n\n**Sual 2**\nParallel bağlı 2 müqavimət (R₁=4Ω, R₂=4Ω). Ümumi müqavimət?\nA) 8 Ω  B) 4 Ω  C) 2 Ω  D) 1 Ω\n✅ **C) 2 Ω** *(1/R = 1/4 + 1/4 = 1/2 → R=2)*\n\n**Sual 3**\nElektrik gücü düsturu:\nA) P = U/I  B) P = U×I  C) P = I/U  D) P = U+I\n✅ **B) P = U×I**"),

        ("Biologiya, 8-ci sinif, mövzu: Hüceyra üzrə 3 test sualı yarat",
         "**8-ci sinif Biologiya — Hüceyra**\n\n**Sual 1**\nHüceyranın enerji mərkəzi hansı orqanoidddir?\nA) Nüvə  B) Ribosom  C) Mitoxondriya  D) Lizosoma\n✅ **C) Mitoxondriya**\n\n**Sual 2**\nProtein sintezi harada baş verir?\nA) Mitoxondriya  B) Ribosom  C) Nüvə  D) Membran\n✅ **B) Ribosom**\n\n**Sual 3**\nBitki hüceyrəsini heyvan hüceyrəsindən fərqləndirən nədir?\nA) Nüvə  B) Membran  C) Hüceyra divarı  D) Sitoplazma\n✅ **C) Hüceyra divarı**"),
    ]

    for q, a in tests:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# DƏRS PLANI
# ═══════════════════════════════════════════════════════════════

def lesson_plan_data() -> list[dict]:
    data = []

    plans = [
        ("7-ci sinif üçün Coğrafiya dərs planı hazırla. Mövzu: Azərbaycanın iqlimi",
         "**Dərs Planı**\n📚 Fənn: Coğrafiya | 🎓 Sinif: 7 | ⏱️ 45 dəq\n**Mövzu: Azərbaycanın İqlimi**\n\n**🎯 Məqsədlər:**\n- Azərbaycanın iqlim növlərini bilmək\n- İqlimə təsir edən amilləri izah etmək\n- Xəritə üzərindən iqlim zonalarını müəyyən etmək\n\n**📋 Dərs gedişi:**\n\n**Giriş (5 dəq)**\n- Sual: \"Bu gün hava necədir? Dünən Şamaxıda necə idi?\"\n\n**Əsas hissə (30 dəq)**\n1. Azərbaycanda 9 iqlim qurşağı (10 dəq)\n2. Xəritə üzərindən iş (10 dəq)\n3. İqlimə təsir edən amillər: dəniz, dağlar, relyef (10 dəq)\n\n**Təkrar (8 dəq)**\n- 3 sual-cavab oyunu\n\n**Yekun (2 dəq)**\n- Ev tapşırığı: §15"),

        ("5-ci sinif üçün Riyaziyyat dərs planı. Mövzu: Kəsrlər",
         "**Dərs Planı**\n📚 Riyaziyyat | 🎓 5-ci sinif | ⏱️ 45 dəq\n**Mövzu: Adi Kəsrlər**\n\n**🎯 Məqsədlər:**\n- Kəsr anlayışını başa düşmək\n- Kəsrin pay və məxrəcini tanımaq\n- Sadə kəsr əməliyyatları aparmaq\n\n**📋 Plan:**\n\n**Giriş (5 dəq)**\n- Pizzanı 4 hissəyə böl → 1 hissə = 1/4\n- Vizual göstəriş\n\n**Kəsr nədir? (10 dəq)**\n- Pay / Məxrəc\n- Nümunələr: 1/2, 3/4, 2/5\n\n**Əməliyyatlar (20 dəq)**\n- Toplama (eyni məxrəc): 1/4 + 2/4 = 3/4\n- Toplama (fərqli məxrəc): 1/2 + 1/3 = 5/6\n\n**Məşq (8 dəq)**\n- 5 məsələ həll et\n\n**Ev tapşırığı:** §8, məs. 1-6"),
    ]

    for q, a in plans:
        data.append(make(q, a))

    return data


# ═══════════════════════════════════════════════════════════════
# ƏSAS FUNKSIYA
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("EduAI — Məlumat Generatoru")
    print("=" * 60)

    all_data = []
    generators = [
        ("Riyaziyyat",      math_data),
        ("Fizika",          physics_data),
        ("Kimya",           chemistry_data),
        ("Biologiya",       biology_data),
        ("Tarix",           history_data),
        ("İngilis dili",    english_data),
        ("Azərbaycan dili", azerbaijani_data),
        ("Sual generasiya", question_gen_data),
        ("Dərs planı",      lesson_plan_data),
    ]

    for name, gen_fn in generators:
        samples = gen_fn()
        all_data.extend(samples)
        print(f"  {name:20s}: {len(samples):4d} nümunə")

    print(f"\nCəmi: {len(all_data)} nümunə")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\n✅ Saxlandı: {OUT_FILE}")
    print("\nNövbəti addım:")
    print("  python prepare_data.py")


if __name__ == "__main__":
    main()
