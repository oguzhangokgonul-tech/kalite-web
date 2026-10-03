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
- Geri donus: bu degisikligin normal revert commit'i ile onceki uygulama
  davranisina donulur. DB downgrade veya veri restore'u gerekmez.
  Modul kapatma korumasi geri alinacaksa bakim modulu kapali tenant'larda
  onceki dogrudan POST aciginin yeniden olusacagi dikkate alinmalidir.
