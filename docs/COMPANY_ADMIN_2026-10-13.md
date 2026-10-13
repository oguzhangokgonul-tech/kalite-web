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
- Lider onayiyla 13 Ekim 2026 tarihinde `81dfc56b51b483f309783db549a314e6840851b7` uygulama surumu canliya alindi.

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

## Canli Dagitim Kaniti

- Izole release worktree testleri: 97 basarili; onboarding rol audit testi ve dar kapsamli kurulum testleri dahil.
- Dar kapsamli kurulum yalniz `company_admin` rolunu 242 izinle ekledi. Mevcut kullanicilara otomatik atama yapilmadi.
- Tam yedek: `/var/data/aksiyon-takip/backups/company-admin-release.vJ1cF4H9/archive/volkaportal-backup-20261013-170718.zip`.
- Sunucu disi kopya: `backups/company-admin-20261013/volkaportal-backup-20261013-170718.zip`.
- Iki kopyada SHA256: `04d33dd7388398a161c32a231bfeb08c9bf86c8e6a91bea890d1e5704455ad4e`.
- Gercek geri yukleme yalniz izole gecici ortamda yapildi: 204 dosya, integrity_check OK. Rol kurulumunun iki calistirmasi ve 167 mevcut tablonun korunmasi dogrulandi.
- Canli kurulumdan sonra sema/revizyon degismedi (`202610120002`); mevcut is verileri ve 204 upload dosyasi hash karsilastirmasiyla korundu.
- Sunucu verisinin izole kopyasinda 3 sirket icin alt rol atama/audit, platform reddi, diger admini koruma ve tenant sinirlari dogrulandi. Canli is kaydi yazilmadi.
- `volkaportal.com`, `erprefabrik.volkaportal.com`, `sagiroglucelik.volkaportal.com` HTTPS girisleri 200.
- Uygulama, nginx, hatirlatma ve webhook zamanlayicilari aktif; yeni worker baslangicinda hata yok. Onceki worker SIGTERM mesajlari planli durdurmaya ait.
- Musteri geri bildirimi silme degisiklikleri bu dagitima alinmadi.
- Geri donus gerekirse: once yazicilari durdurup yeni yedek alin. Henuz yeni role hesap atanmamissa onceki kodla uyumlu bos rol korunabilir; atama varsa eski kodun admin korumalarini icermedigi dikkate alinmali ve rol/izin geri donus plani onaylanmali. Canli tam restore ayri acik onay gerektirir.
