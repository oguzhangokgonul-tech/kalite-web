# Mobil Merkez: Bakim Erisimi

## Kapsam
- Mobil Merkez hizli islemlerinin basina Ariza Ac ve Bakim Islemleri eklendi.
- Mevcut bakim akisi ve roller korundu; sirketin bakim modulu kapaliysa
  kisayollar gorunmez ve hedef route'lar erisime kapalidir.
- Eksik complete_maintenance_fault modul eslemesi tamamlandi. Modul kapaliyken
  dogrudan POST ile ariza kapatma engellendi.
- Sema, mevcut kayitlar, mail politikasi ve servis worker onbellegi degismedi.

## Dogrulama
- PWA ve bakim/arac smoke: 11 test basarili; bagimsiz QA ayni sonucu dogruladi.
- Tenant, oturum izolasyonu, paket ve rol navigasyonu: 40 test basarili.
- Playwright: 390, 768 ve 1440 px. CSRF acikken personel talep olusturma,
  yonetim temsilcisi kapatma ve bakim listesine donus basarili.
- Yatay tasma ve JavaScript hatasi yok; ekran goruntuleri incelendi.
- Rol/yetki, sirketler arasi erisim ve kapali modul POST regresyonlari mevcut.
- Tam test paketi yerine degisen akis ve tenant/paket/navigasyon testleri hedeflendi.

## Yayin Kapilari
- Lider canliya alma onayi verdi. Bagimsiz QA dar kapsam icin kabul verdi.
- Yeni migration yok; upgrade/downgrade provasi uygulanmaz.
- Yayin oncesi tum DB/upload yazarlari durdurularak tam yedek alinacak;
  backup-verify, restore dry-run ve sunucu disi SHA256 eslesmesi zorunlu.
- Temiz canli hedefe fast-forward; servis, tenant-health, HTTPS ve salt-okunur
  Mobil Merkez kontrolleri tamamlandiktan sonra timer'lar tekrar acilacak.
- Geri donus: normal commit ile pwa.py kisayollari geri alinabilir;
  routes.py modul kapatma korumasi korunmalidir. DB downgrade veya veri
  restore'u gerekmez.

## Canli Sonuc
- Uygulama surumu: `3090f21`; GitHub ve canli HEAD eslesmesi dogrulandi.
- Web, reminder ve webhook yazarlari durdurularak tam yedek alindi.
  Arsiv: `/var/data/aksiyon-takip/backups/mobile-maintenance-20261003/volkaportal-backup-20261003-064707.zip`.
- 204 upload; checksum, quick_check, integrity_check ve restore dry-run
  basarili. Dry-run gercek geri yukleme degil, arsiv dogrulamasidir.
- Sunucu disi kopya: `C:/Users/Asus/VolkaPortalBackups/20261003-mobile-maintenance/`.
  Her iki kopyanin SHA256 degeri:
  `05ca3c4b9f53eede8c4e5b5f6bff8e9587a96aa41bf678ebc68b8d37d460230f`.
- Tenant-health basarili; migration head `202610020002` degismedi.
- Ana alan adi ve iki musteri alan adinin HTTPS girisleri 200.
- Mail ve otomatik hatirlatma kapali izole test process'inde iki musteri icin
  oturumlu /mobil, /bakim ve /bakim/ariza/yeni kontrolleri 200. Canliya test
  ariza kaydi eklenmedi. Ilk kontrol script'indeki slug varsayimi primary_domain
  sorgusuyla duzeltildi; bu uygulama hatasi degildi.
- Uygulama ve daha once aktif iki timer yeniden aktif; yayin sonrasi uygulama
  hata logunda kayit yok. Bagimsiz QA ve release/veri incelemesi tamamlandi.
