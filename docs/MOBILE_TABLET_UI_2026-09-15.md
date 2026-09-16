# Mobil ve Tablet Kullanım Düzenlemesi

Tarih: 15.09.2026

## Yapılanlar

- Ortak uygulama kabuğuna son yüklenen bir cihaz düzeni katmanı eklendi.
  Menüdeki modüller bu katmanı kullanıyor; mevcut masaüstü düzeni korunuyor.
- Telefonda formlar tek sütun, listeler alan adı ve değer içeren kayıt görünümü.
  Tablette uygun formlar iki sütun, listeler karşılaştırılabilir tablo görünümü.
  Kullanıcı liste/tablo seçimini değiştirebiliyor; seçim oturum boyunca korunuyor.
- Tablo görünümünde yatay kaydırma yalnızca tablo alanında. Karmaşık birleşik
  hücreli tablolar özgün yapısıyla kalıyor. Sıralama/filtre kontrolleri ve kayıt
  açma düğmeleri görünüm değiştirince çalışmaya devam ediyor.
- Dokunmatik ekranlarda menü düğmeyle açılıyor. Alt menüler, son bağlantılar ve
  çıkış düğmesi uzun menüde ve yatay kısa ekranda erişilebilir. Büyük dokunmatik
  tablette de bu davranış uygulanıyor.
- Dokunmatik düğmeler için en az 44 px hedef, form alanları için 16 px yazı,
  okunabilir etiketler, sarılan aksiyonlar ve ekran içine sığan açılır pencereler.
- Doküman, İF/DÖF, görev, personel, kalibrasyon, öneri, kalite deneyi, denetim,
  dinamik form ve diğer modüllerin ortak tablo/form düzenleri uyarlandı.
- Beton detay panelinin hücre yüksekliği nedeniyle kesilmesi, ölçüm düğmesi
  yazı kontrastı ve tablette işlem ikonlarının doküman satırını aşırı uzatması
  giderildi. Görüntüleyici rolünde ölçüm değiştirme bağlantıları gizlendi.
- Organizasyon haritası mobil alana uyarlandı; yakınlaştırma alt sınırı düşürüldü.
  İkinci parmak etkin sürüklemeyi devralmıyor; iptal edilen hareket geri alınıyor.
- İç denetimi tamamlarken kaydedilmemiş cevapların fark edilmeden atlanmasını
  önleyen uyarı eklendi. Dinamik form tasarımında onay kutusu/etiket eşleşmesi
  düzeltildi. Telefon alanları telefon klavyesiyle açılıyor.
- Giriş ve dış müşteri bildirim/takip ekranları uyarlandı. Uzun ek dosya adları
  ekran dışına taşmadan sarılıyor. Windows üzerinde JavaScript'in yanlış MIME
  türü nedeniyle tarayıcı tarafından engellenmesi düzeltildi.

## Doğrulama Sonuçları

- Tam Python paketi: 349 başarılı test. Bu koşu son görsel düzeltmelerden önce
  tamamlandı; mevcut bağımlılıklara ait kullanımdan kaldırma uyarıları var.
- Son odaklı Python koşusu: responsive ve organizasyon/personel testlerinde
  6 başarılı test, 2 mevcut SQLAlchemy kullanımdan kaldırma uyarısı.
- Ana tarayıcı matrisi: 357 başarılı sayfa/ekran boyutu kontrolü, 0 hata.
  Boyutlar: 360, 390, 768, 820, 1024, 1180 ve 1440 px. Ana envanter dört
  boyutta; diğer boyutlarda kritik ekranlar kontrol edildi.
- Form ve kayıt etkileşimleri: 360, 820, 1024 px üzerinde 18 başarılı senaryo,
  0 hata. Son tablo satırı yüksekliği ve ölçüm düğmesi kontrastı düzeltmeleri dahil.
- Giriş ve iş akışları: 390, 768, 1024 px üzerinde 21 başarılı senaryo.
- İlave dokunmatik kontroller: 320x740, 640x400, 1366x1024 üzerinde 6 başarılı
  senaryo; menü/çıkış/ekran döndürme ve gerçek tarayıcı dokunma olayları dahil.
- Ekran görüntüleri ayrıca görsel olarak incelendi; tespit edilen satır yüksekliği,
  taşma, panel kesilmesi ve düğme kontrastı sorunları giderildi.

## Rol ve İş Akışı Kapsamı

Süper Admin, Yönetim Temsilcisi, Yönetim, Departman Yöneticisi, Departman Personeli
ve Görüntüleyici rollerinin menü bağlantıları kontrol edildi. Aksiyon sorumlusu
ve doküman kullanıcısı personel hesabıyla, müşteri bildirimleri anonim oturumla
denendi. İç denetim akışı yüksek yetkili hesapla denendi.

Bu çalışma tüm modüllerin bütün iş durumlarının hatasız olduğuna dair garanti
değildir. Özellikle sınırlı yetkili denetçi ve İF/DÖF sorumlusunun tüm onay/ret/
yeniden gönderim birleşimleri, fiziksel telefon/tablet, Safari/iOS, sanal klavye
ve ekran okuyucu testleri ayrıca tamamlanmalı. Bazı modüller boş liste ve yeni
kayıt formuyla, bazıları dolu örneklerle sınandı. Tamamlanmış okuma onayı veya
aksiyon kapatma sonraki boyutta durum kontrolü olarak doğrulanabiliyor.

## Teknik Etki

Yeni üretim tablosu, migration veya route eklenmedi. Tarayıcı önbelleği için
varsayılan `ASSET_VERSION` değeri `20260915-device-layout` oldu. Ortam değişkeniyle
ayrı sürüm kullanılıyorsa dağıtımda onun da güncellenmesi gerekir.

Önceki e-posta/link düzeltmeleri çalışma ağacında ayrı olarak duruyor.
Bu UI çalışması henüz commit/push edilmedi ve canlıya alınmadı.

Tekrar çalıştırma: `tests/ui/README.md`. Önizleme geçici test verileri kullanır.
