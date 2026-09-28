# VolkaPortal Entegrasyon Operasyon Notlari

## Sifreleme anahtari

Webhook imza sirlarini koruyan `INTEGRATION_ENCRYPTION_KEY` uretimde zorunludur.
Anahtar uygulama reposuna veya veritabanina yazilmaz.

```bash
sudo install -d -m 750 -o root -g aksiyon /etc/aksiyon-takip
sudo -u aksiyon /var/www/aksiyon-takip/venv-py312/bin/python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
sudoedit /etc/aksiyon-takip/integrations.env
sudo chown root:aksiyon /etc/aksiyon-takip/integrations.env
sudo chmod 640 /etc/aksiyon-takip/integrations.env
```

Dosya tek satir icermelidir:

```text
INTEGRATION_ENCRYPTION_KEY=<uretilen-anahtar>
```

Anahtar kaybolursa mevcut webhook sirlarina erisilemez. Dosya, uygulama veritabanindan
ayri ve sifreli bir yedekte saklanmalidir.

## Anahtar rotasyonu

Anahtar dogrudan degistirilmez. Once veritabani ve eski anahtar yedeklenir, tum
`webhook_endpoints.secret_ciphertext` degerleri eski anahtarla cozulup yeni anahtarla
sifrelenir, ardindan servisler yeniden baslatilir. Yeniden sifreleme tamamlanmadan eski
anahtar silinmez.

## Yayin sirasi

1. Dogrulanmis tam yedek alin.
2. `integrations.env` dosyasini olustur ve izinlerini kontrol et.
3. Python bagimliliklarini kur.
4. Alembic migration'i uygula.
5. systemd unit ve drop-in dosyalarini kur, `daemon-reload` calistir.
6. Uygulama ile webhook timer'ini baslat.
7. `integration-readiness-check` ve canli smoke testlerini calistir.
8. Tum kontroller basariliysa `integration-readiness-check --mark` ile satis
   checklistini isaretle.

Terminalden calistirilan Flask komutlari systemd ortam dosyasini kendiliginden okumaz.
Migration ve readiness komutlari anahtari acikca yukleyerek calistirilmalidir:

```bash
sudo -u aksiyon bash -lc '
  set -a
  source /etc/aksiyon-takip/integrations.env
  set +a
  cd /var/www/aksiyon-takip
  ./venv-py312/bin/python -m flask --app app:create_app db upgrade
  ./venv-py312/bin/python -m flask --app app:create_app integration-readiness-check
'
```

## Geri donus

Migration downgrade entegrasyon gecmisini siler. Downgrade oncesinde webhook timer'i
durdurulur ve geri yuklenebilir yedek dogrulanir. Veri kaybi kabul edilmeden entegrasyon
tablolarinda downgrade uygulanmaz.
