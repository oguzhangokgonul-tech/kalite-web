# Sirket Admini

## Yetki sozlesmesi

- Superadmin > Sirket Admini > sirket kullanicilari.
- `company_admin` sistem rolunun hiyerarsi seviyesi 5'tir; `super_admin` degildir.
- Sirket admini yalniz kendi firmasindaki kullanicilari ve etkin modulleri yonetir.
- Admin hesabi olusturma, atama, rol kaldirma, parola degistirme ve pasife alma yalniz global `superadmin` hesabina aciktir.
- Adminler kendi hesaplarini veya diger adminleri kullanici/personel yonetiminden degistiremez.
- Sirket admini, kendi izinlerini asmayan Yonetim Temsilcisi, Yonetim, Departman Yoneticisi, Departman Personeli ve Goruntuleyici rollerini atayabilir.
- Global rol tanimlari, sirket/paket yonetimi, satis checklisti, sistem yedekleri ve platform admin paneli acilmaz.
- Mevcut kullanicilar otomatik yukseltilmez. Yeni rol, mevcut temsilci ve alt sirket rollerinin varsayilan izinlerinin bagimsiz birlesimidir; platform `roles.manage` izni verilmez.
- Firma degistirme bu ozelligin kapsaminda degildir. Duzenlenen hesap kendi firmasinda kalir.

## Kullanim

Superadmin: Sirket Yonetimi > Admin / Kullanici Ekle > hedef sirket ve kullanici bilgileri > Sirket Admini > Kaydet.
Mevcut bir kullanici Kullanici Duzenle veya Rol Yonetimi ekranindan da atanabilir.
Kurulum Sihirbazi ilk kullanici rollerinde Sirket Admini secenegi bulunur; eski varsayilan degistirilmedi.
Pasif hesaplar Kullanici listesinde gorunur; Superadmin yeniden etkinlestirebilir.

## Teknik Kontroller

- Sunucuda hedef kullanici, firma, korunan rol, izin altkumesi ve rol seviyesi denetlenir.
- Atama/geri alma islemleri eski ve yeni rol listeleriyle, aktor ve hedef firma ile audit kaydina yazilir.
- Rol geri alinirken eski boolean yetkiler de yeniden hesaplanir.
- Personel baglantilarindan dolayli admin degisikligi ve global hesabin firma personeline isimle otomatik baglanmasi engellenir.
- CSRF ve mevcut aktif kullanici kotasi korunur.
- Sema degisikligi yoktur. Dagitimda `python -m scripts.company_admin_release` yalniz yeni rolu ekler; mevcut kullanici atamalarina ve diger rollerin ozel izinlerine dokunmaz. Ikinci calistirma etkisizdir; farkli bir mevcut admin tanimi varsa durur.
- Canliya alma yapilmadi; kod ve testler yereldedir.

## Bilinen Ayrik Bulgular

- Onboarding regresyonundaki `iso_core`/`custom` paket beklentisi mevcut HEAD `c98495a` surumunde de hatali. Bu ozellik icin paket davranisi degistirilmedi.
- Eski is akislarinda bazi onay yetkileri kullanici unvanindan da turetiliyor. Admin korumasi rol bazlidir; tum eski unvan temelli onaylarin kaldirilmasi ayri bir rol gecis calismasi gerektirir.
- Planlamaci ve guvenlik ajanlari salt okunur bulgular sundu; QA ajani bagimsiz test dosyasini hazirladi. Ajan oturumu sinirlandigi icin nihai test yurutmesi ana ajan tarafindan tamamlandi.

## Dogrulama Sonucu

- `test_company_admin`, `test_company_limits`, `test_tenant_session_isolation`, `test_organization_personnel`: 94 test basarili.
- Onceki onboarding dahil regresyon: 19 basarili, 1 yukarida belirtilen eski paket beklentisi hatasi. Hata temiz HEAD worktree'sinde de tekrarlandi.
- Gercek Chrome: admin ve Superadmin icin 390, 768, 1440 pikselde liste/form, 12 HTTP 200 ve sayfa tasmasi yok.
- Mobil tarayicida CSRF'li formdan admin olusturma, diger adminin duzenleme butonunun kapali olmasi ve Superadmin ile pasife alma basarili.
- Python derleme kontrolu ve `git diff --check` basarili. Yerel Graphify AST haritasi yenilendi.
- Tum repo test paketi calistirilmadi; ilgili rol, tenant, kota ve personel regresyonlari calistirildi.
