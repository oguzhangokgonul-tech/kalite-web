# Canli Python ve Yedek Dogrulamasi

Tarih: 2026-09-15. Kullanici Python 3.10+ kurulumu ve dogrulanmis yedek
alinmasini onayladi. Bu islem uygulama kodu/migration dagitimi degildir.

## Sonuc

- Eski sistem ve venv Python'u: 3.8.10. Sistem Python'u degistirilmedi.
- Aktif uygulama Python'u: 3.12.13.
- Yeni ortam: /var/www/aksiyon-takip/venv-py312.
- Eski ortam geri donus icin /var/www/aksiyon-takip/venv olarak korundu.
- Yerel requirements.txt yeni ortama kuruldu. pip check basarili.
- Production factory route yukleme testi basarili.
- systemd drop-in: /etc/systemd/system/aksiyon-takip.service.d/python312.conf.
- Gunicorn app:create_app() factory kullanir; eski run.py importundaki
  create_all/seed/parola islemleri calistirilmaz.
- APP_ENV=production, AUTO_BOOTSTRAP_DATABASE=false,
  RESET_DEFAULT_USER_PASSWORDS=false ayarlandi. Mevcut SECRET_KEY korunmustur;
  gizli anahtar yonetimi/rotasyonu ayri guvenlik isi olarak takip edilmeli.
- Servis active/running; iki worker yeni Python ile basladi.
- https://volkaportal.com/login ve
  https://erprefabrik.volkaportal.com/login HTTP 200 dondu.
- Son yedek icin servis 07:14:25 UTC'de durdu, 07:14:44 UTC'de basladi.
  Durdurma sirasindaki eski worker SIGTERM mesajlari yeni baslangic hatasi degildir.

## Yedekler

Son tutarli yedek, uygulama servisi dururken alindi:

```text
/var/data/aksiyon-takip/backups/full/volkaportal-backup-20260915-071428.zip
```

- 58,907,943 bayt paket.
- 203 upload dosyasi, 205 checksum girdisi.
- SQLite quick_check=ok, integrity_check=ok.
- Mevcut backup-verify komutu OK dondu.
- Bagimsiz ek kontrol: ZIP CRC, benzersiz uye/checksum yollar, manifest ve
  DB dahil eksiksiz checksum kapsami, SHA256 ve boyutlar, upload sayisi ve
  toplam upload boyutu dogrulandi. STRICT_BACKUP_OK.
- Bu kontroller dosya butunlugunu kanitlar; imza/kaynak ozgunlugu veya tam
  uygulama geri yukleme tatbikati yerine gecmez. Canli veri restore edilmedi.

Kod ve yapilandirma geri donus arsivi:

```text
/var/backups/volkaportal/20260915-runtime/code-config-before-python312.tar.gz
```

Bu arsiv .env ve sunucu yapilandirmasi gibi hassas bilgiler icerebilir;
sunucu klasoru 700, arsiv 600 yetkilidir. Git'e eklenmez veya paylasilmaz.
Sunucu disi kopyalar: C:/Users/Asus/VolkaPortalBackups/20260915/.
Her iki dosyanin sunucu ve yerel SHA256 degerleri ayni bulundu; yerel ZIP
kopyasi bagimsiz checksum kapsami kontrolunden de gecti.

## Sonraki Kod Dagitimi

Eski ./venv/bin/python komutlarini kullanmayin; halen 3.8.10 ortamidir.
Canlida yeni kodun migration/CLI islemlerinde su interpreter'i kullanin:

```bash
cd /var/www/aksiyon-takip
./venv-py312/bin/python --version
sudo -u aksiyon ./venv-py312/bin/python -m pip check
```

Kod dagitimi oncesi yeni tam yedek alinmali ve dogrulanmali. Uygulama factory
CLI girisi --app app:create_app eski run.py seed davranisini atlar.
Yeni 202609150001/202609150002 migration'lari bu runtime isleminde uygulanmadi.

Geri donus: servisi durdurun, yalnizca python312.conf dosyasini drop-in
klasorunun disina tasiyin, daemon-reload yapin ve servisi baslatin.
Eski unit bilinen varsayilan parola reset ayari icerir; geri donus gerekirse
bu ayari false yapan ayri drop-in korumasini once ekleyin. Veri geri yukleme
gerekiyorsa BACKUP_RESTORE.md ve dogrulanmis arsiv kullanilmali.

Python kurulumu sistem Python'unu degistirmeden uv managed interpreter ile
yapildi: https://docs.astral.sh/uv/guides/install-python/.
