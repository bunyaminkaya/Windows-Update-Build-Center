# USB Kurulum Aracı — Özelleştirme ve SHA-256 Test Rehberi

Bu özellikler Windows'ta gerçek USB ve gerçek Windows Kurulumu gerektirir; geliştirme ortamında yalnızca
XML üretimi, doğrulamalar ve arayüz akışı otomatik test edildi (tests/test_usb_media_service.py,
tests/test_usb_page_options.py). Aşağıdaki denemeleri **yedeği alınmış bir USB** ve tercihen **sanal makine**
(Hyper-V / VirtualBox / VMware) ya da önemli verisi olmayan bir test bilgisayarıyla yapın.

## 1. ISO SHA-256 doğrulaması

1. PowerShell'de beklenen değeri üretin: `Get-FileHash "C:\yol\Win11.iso" -Algorithm SHA256`
2. USB Kurulum Aracı > ISO Kaynağı: ISO'yu seçin, **"ISO'nun SHA-256 değerini doğrula"** anahtarını açın.
3. **Doğru değer:** "Beklenen SHA-256" kutusuna yapıştırın (boşluk/küçük harf olabilir) ve USB'yi oluşturun.
   - Beklenen: Doğrulama aşamasında "SHA-256 hesaplanıyor • %… • … MB/sn" görünür, günlükte
     `ISO SHA-256: …` ve `Beklenen değerle eşleşti ✓` yazar, sonra normal akış sürer.
4. **Yanlış değer:** değerin son hanesini değiştirin.
   - Beklenen: İşlem Doğrulama aşamasında **hata verir**, "USB'ye dokunulmadı" yazar; USB'deki dosyalarınız **silinmemiş** olmalıdır.
5. **Değer boş:** anahtar açık, kutu boş. Beklenen: hash hesaplanıp günlükte gösterilir, akış sürer.
6. **Geçersiz değer** (ör. `123`): işlem başlamadan "64 haneli onaltılık" uyarısı çıkar.
7. **İptal:** hash hesaplanırken "İşlemi Durdur"a basın. Beklenen: birkaç saniye içinde iptal olur, USB silinmez.
8. Anahtar kapalıyken hash hesaplanmaz (eski davranış).

Not: 5-6 GB'lık ISO'nun hash'i diske göre 20-90 sn sürebilir.

## 2. Kurulum özelleştirme

USB oluşturduktan sonra USB'nin kökündeki `autounattend.xml` dosyasını Not Defteri'yle açıp kontrol edin.

| Seçenek | autounattend.xml'de görülmesi gereken |
|---|---|
| Windows 11 donanım gereksinimlerini kaldır | `windowsPE` bölümünde 3 adet `reg.exe add ...LabConfig` komutu |
| Yerel hesap | `oobeSystem` içinde `HideOnlineAccountScreens` ve `LocalAccount` (Ad + Administrators) |
| Bilgisayar adı | `specialize` içinde `<ComputerName>` |
| Gizlilik sayfalarını atla | `oobeSystem` > `OOBE` > `ProtectYourPC` = 3 |
| Hiçbiri | `autounattend.xml` **yazılmaz** (ISO'da varsa olduğu gibi kalır) |

Ardından USB'den gerçek bir kurulum deneyin (sanal makinede USB'yi aktararak ya da ISO'yu doğrudan bağlayarak
aynı `autounattend.xml`'i ISO'nun kökü gibi veren ikinci bir sanal USB ile):

1. **Yerel hesap:** Kurulum sonunda Microsoft hesabı/ağ ekranı çıkmamalı; yazdığınız adla hesap açılmalı,
   parola istenmemeli. (Parola yok: ilk girişten sonra Ayarlar > Hesaplar'dan belirleyin.)
2. **Bilgisayar adı:** Ayarlar > Sistem > Hakkında'da ad görünmeli.
3. **Gizlilik sayfaları:** İlk açılışta gizlilik/ekspres ayar soruları çıkmamalı. Lisans sözleşmesi sayfası
   **çıkabilir** (bilerek gizlenmiyor).
4. **Donanım atlama:** TPM/Secure Boot olmayan sanal makinede "Bu bilgisayar Windows 11'i çalıştıramıyor" uyarısı çıkmamalı.
5. Kurulum sonrası **Windows Update** çalışıyor mu kontrol edin (`ProtectYourPC=3` bazı sürümlerde otomatik
   güncelleme ayarını etkileyebilir; etkilenirse "Gizlilik sayfalarını atla"yı kapatıp bize bildirin).

### Bilinen belirsizlikler (gerçek cihazda doğrulanmalı)
- Windows 11'in yeni sürümleri unattend ayarlarını farklı yorumlayabilir; bir seçenek uygulanmazsa sürüm numarasını not edin.
- ARM64 ISO'lar dosya adındaki `arm64` ifadesinden tanınır; adı değiştirilmiş ARM ISO'larda ayarlar uygulanmayabilir.
- ISO'nun kendi `autounattend.xml` dosyası varsa ve bir özelleştirme seçtiyseniz dosya **değiştirilir** (günlükte yazar).

## 3. Doğrulama mesajları (işlem başlamadan çıkar)

| Girdi | Beklenen uyarı |
|---|---|
| Yerel hesap açık, ad boş | "Yerel hesap için bir ad yazın…" |
| Ad: `Administrator`, `Guest` | ayrılmış ad uyarısı |
| Ad: `a/b`, `x:y` | geçersiz karakter uyarısı |
| Bilgisayar adı: `Çalışma`, `my pc`, `12345`, `-pc` | ilgili uyarı |
| 16+ karakterli bilgisayar adı | en çok 15 karakter |

## 4. Beklenmeyen bir şey olursa
Programın günlüğünü (`%LOCALAPPDATA%\Windows Update & Build Center\logs\app.log`), USB'deki `autounattend.xml`
dosyasını ve işlem günlüğü ekran görüntüsünü gönderin.
