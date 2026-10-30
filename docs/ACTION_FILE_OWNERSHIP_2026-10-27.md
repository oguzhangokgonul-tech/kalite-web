# Aksiyon Dosyasi Sahipligi

## Karar

Yeni aksiyon ekleri kanonik, kayit kimligine bagli klasorlerde saklanir:

- Ana ek: `company-NNN/actions/files/<action_id>/<uuid>.<uzanti>`
- Alt aksiyon kaniti: `company-NNN/actions/sub-actions/<action_id>/<sub_action_id>/<uuid>.<uzanti>`
- Kapanis kaniti: `company-NNN/actions/closure/<action_id>/<closure_file_id>/<uuid>.<uzanti>`
- Eski tek-dosya kapanis alanina yeni yukleme yapilmaz. Yalniz
  `company-NNN/actions/closure/<action_id>/legacy/<dosya>` bicimindeki
  dogrulanmis referans okunabilir.

Indirme ve silme, sirket, aksiyon, varsa alt kayit kimligi, tam ust klasor,
kanonik path ve kalici manifest eslesmeden dosyaya erismez. Indirme ayrica
dosya boyutunu ve SHA-256 ozetini dogrular. Uygunsuz istekte 404 doner ve
basarili indirme audit olayi olusmaz. Eski duz klasore veya upload kokune
geri dusus yoktur. Yeni dosya adi UUID ile uretilir.

Eski dosya temizligi basarili veritabani commit'inden sonra yapilir. Boylece
reddedilen form veya basarisiz DB islemi mevcut kaniti silmez. Fiziksel
temizlik basarisizsa kayit guncellemesi geri alinmaz; manifestte silme kaydi
kalir ve bakim komutu tekrar deneyebilir. Bu, DB ile dosya sistemi arasinda
tam atomiklik saglamaz.
Yeni yuklenen dosyalar DB commit'ine kadar izlenir; dis transaction rollback'i
veya commit hatasinda temizlenir. Bildirim akisi icindeki savepoint rollback'i
dis islemin yuklemesini silmez.

## Canli Gecis

27 Ekim 2026 salt-okunur canli envanterinde `actions.file_stored_name`,
`actions.closure_file_stored_name`, `action_sub_tasks.evidence_stored_name` ve
`action_closure_files.stored_name` dolu kayit sayilari sirasiyla `0/0/0/0`.
Bu nedenle toplu veri/dosya tasimasi gerekmiyordu. Manifest icin eklemeli
`202610300001` Alembic migration'i gerekir. Yayin hemen oncesi ayni sorgu
ve upload dizini sayimi tekrarlanir; sayilardan biri sifir degilse
release durur. Eski yol otomatik sahiplenilmez veya fiziksel dosya silinmez.

Ileride eski kayitli bir kurulum icin tasima gerekirse once DB ve upload
klasorunun tek tam yedegi, sonra yol-varlik, firma/kayit eslesmesi, birden
fazla referans ve SHA-256 envanteri alinir. Yalniz tek sahibi kanitlanan
dosya yeni yola kopyalanir; checksum dogrulandiktan sonra DB yolu guncellenir.
Eski kopya tum referanslar kontrol edilmeden silinmez. Cakisan/yetim dosyalar
otomatik tasinmaz.

## Manifest ve Bakim

`action_evidence_manifest`, her `stored_name` icin benzersiz kayit ile firma,
aksiyon, alt kayit turu/ID, SHA-256, boyut ve silinme/temizlik zamanlarini
saklar. Silinen satirlar tutulur; ayni yol veya yeniden kullanilan aksiyon
ID'si eski dosyayi yeniden yetkili kilmaz. Sahipligi kanitlanmayan eski
dosyalar otomatik manifestlenmez ve indirme/silme islemi kapali baslar.

`flask --app app:create_app reconcile-action-uploads` bekleyen temizligi
yalniz raporlar; `--apply` silinen kayitlarin dosyalarini temizler. Bu komut
root olarak degil, uygulamanin `aksiyon` kullanicisiyla calistirilir. Silme
niyeti DB'de kalici oldugundan komut yeniden calistirilabilir.

Kod rollback'i manifest, tombstone ve hash korumasini kaldirir. Manifestte
veri varsa migration downgrade'i bilincli olarak durur. Gercek DB ve upload
geri yuklemesi yayin sonrasi yazilari silebilir; ayri Lider onayi olmadan
uygulanmaz.
