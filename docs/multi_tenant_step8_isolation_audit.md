# Multi-Tenant Adim 8 Izolasyon Denetimi

Bu denetim firma bazli kullanimda veri ve bildirim izolasyonunu kontrol etmek
icin hazirlandi.

## Bu Adimda Yapilan Kod Degisikligi

- `oguzhan_user()` yardimcisi firma kapsamina alindi.
- Artik baska bir firma baglaminda Er Prefabrik firmasina ait `oguzhan`
  kullanicisi fallback onayci/bildirim alicisi olarak secilmez.
- Bu durum test ile guvenceye alindi.

## Guvenli Gorunen Alanlar

- Aksiyon, alt aksiyon, IF, ic denetim, dokuman, bakim, kalite deneyi ve
  organizasyon detay route'larinda ana kayit alindiktan sonra
  `ensure_same_company(...)` kontrolu genis sekilde uygulanmis durumda.
- Liste sorgularinda ana kayitlar cogunlukla `scoped_query(...)` ile firma
  kapsamina aliniyor.
- Bildirim listeleri `Notification` icin `scoped_query(...)` kullaniyor.
- Dosya indirme route'lari once ana kayit uzerinden firma kontrolu yapiyor.

## Kontrol Edilen Kritik Noktalar

- `active_users()` ve `active_user_by_id()` mevcut firma kapsamindaki aktif
  kullanicilari getiriyor.
- Superadmin ana domainde global gorunum alabiliyor.
- Superadmin firma subdomainindeyse ilgili firma kapsami otomatik seciliyor.
- Yeni yuklenen dosyalar firma klasoru altinda saklaniyor.

## Sonraki Adimlarda Ele Alinacak Riskler

- `DocumentCategory.slug` global unique oldugu icin dokuman kategorilerini firma
  bazli cogaltma ayri migration gerektirir.
- Aksiyon, IF, ic denetim ve bakim numaralari bazi alanlarda global sayaç veya
  global unique mantigina bagli kalabilir.
- `AppSetting` sayaç keyleri firma bazli hale getirilecekse geriye donuk veri
  tasima ve unique index plani gerekir.
- Tum bildirim/e-posta alici secimlerinde rol bazli onayci mantigi uzun vadede
  kisi adina bagli fallbacklerden tamamen arindirilmali.

## Uygulama Notu

Bu adim canli veri yapisini degistirmez, migration eklemez. Sadece firma disi
bildirim riskini azaltir ve mevcut izolasyon davranisini testlerle kayit altina
alir.
