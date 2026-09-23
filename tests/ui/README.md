# Mobil ve Tablet Tarayıcı Kontrolleri

Bu araçlar yalnızca `tests.ui.server` ile oluşturulan geçici önizleme içindir.
Sunucu `127.0.0.1` adresinde çalışır; kendi geçici SQLite veritabanını ve dosya
klasörünü oluşturur. Gerçek müşteri veritabanını kullanmaz ve e-posta göndermez.
`/__ui/*` yardımcı uçları uygulamanın normal kurulumunda bulunmaz.

## Çalıştırma

Python bağımlılıklarını ve pytest'i içeren ortamda, bir terminalde:

```powershell
python -m tests.ui.server --port 5067
```

Önizlemeyi açmak için:
`http://127.0.0.1:5067/__ui/login/super_admin?open=1`

Başka bir terminalde Node.js, Playwright ve Google Chrome kullanarak:

```powershell
$env:UI_BASE_URL = 'http://127.0.0.1:5067'
node tests/ui/responsive.mjs
node tests/ui/interactions.mjs
node tests/ui/workflows.mjs
node tests/ui/touch.mjs
node tests/ui/supplier_quality.mjs
node tests/ui/dynamic_forms.mjs
```

Playwright proje dışında kuruluysa `PLAYWRIGHT_MODULE_PATH` değişkenini kurulu
`playwright` veya `playwright-core` klasörünün mutlak yoluna ayarlayın. Projeye
üretim bağımlılığı eklenmesi gerekmez. Önizleme sunucusunun hazır olduğundan emin
olun; testleri aynı veritabanında sırayla çalıştırın.

## Kapsam

- `responsive.mjs`: menüdeki modüller, oluşturma ekranları ve örnek detaylar;
  HTTP yanıtı, JavaScript hatası, sayfa taşması, form sınırları, altı temel rolün
  menü bağlantıları. Telefon/tablet/masaüstü ekran görüntülerini üretir.
- `interactions.mjs`: liste/tablo geçişi, dinamik satırlar ve başlıklar, sıralama,
  menü kaydırma, beton ölçümü değiştirme/silme, personel ekleme/düzenleme/rapor,
  iç denetimde kaydedilmemiş cevap uyarısı ve taslak kaydı.
- `workflows.mjs`: gerçek giriş, beni hatırla, çıkış; aksiyon kapanış kanıtı,
  öneri puanlama, atanmış form ve saha kontrol taslağı, doküman okuma/onay ve
  revizyon talebi, anonim müşteri bildirimi/doğrulama/takip mesajı.
- `touch.mjs`: 320 px telefon, yatay kısa ekran ve 1366 px dokunmatik tablet;
  uzun menü, çıkış, ekran döndürme, organizasyon haritasında dokunarak kaydırma,
  ikinci parmak ve iptal edilen sürüklemenin geri alınması.
- `supplier_quality.mjs`: mobil ve tablette tedarikçi kalite denetimi ile anket
  formlarının taşmadan açılması; mobilde kayıtların kaydedilip geçmişte görünmesi.
- `dynamic_forms.mjs`: parametrik form tasarlama, alan sıralama, koşullu görünürlük,
  yayınlama, atama ve yanıtlama akışını telefon, tablet ve masaüstünde doğrular.

- `ebys.mjs`: resmî yazışma oluşturma ve detay ekranının mobil/tablet akışı.
- `equipment_lifecycle.mjs`: ekipman kartı oluşturma ve yaşam döngüsü detayının mobil/tablet akışı.
- `kaizen.mjs`: Kaizen projesi oluşturma ve proje detayının mobil/tablet akışı.
- `five_s.mjs`: 5S denetimi oluşturma, mobil puanlama ve taslak kaydetme akışı.
- `problem_solving.mjs`: A3 kaydı oluşturma ve mobilde aşamayı incelemeye gönderme akışı.
- `lessons_learned.mjs`: alınan ders taslağı oluşturma ve mobil/tablet taşma kontrolü.
- `help_desk.mjs`: iç talep oluşturma ile mobil/tablet taşma kontrolü.

Ekran görüntüleri ve JSON sonuçları `.tmp-ui-audit/responsive/` altında oluşur.
Bu çıktılar geçicidir. Form testleri kayıtları değiştirir; temiz başlangıç için
önizleme sunucusunu yeniden başlatın. Aynı kaydın tamamlanan işlemleri sonraki
ekran boyutlarında mevcut durum olarak doğrulanabilir; her PASS yeni bir işlem
gönderildiği anlamına gelmez.

Kontroller Chromium emülasyonudur; gerçek iOS/Safari veya fiziksel cihaz testi
yerine geçmez. Her modülün bütün iş durumlarını ve yetki birleşimlerini kapsamaz.
