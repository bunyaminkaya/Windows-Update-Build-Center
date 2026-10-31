# Sürücü Yedekleme – Windows'ta test rehberi

Bu özelliğin komutları yalnızca gerçek Windows'ta çalışır. Aşağıdaki sırayla deneyin; her adımda "Beklenen" ile karşılaştırın.
Önemli: Önce **geri yükleme noktası** alın ve ilk denemeyi kendi bilgisayarınızda, önemli iş yokken yapın.

## 0. Hazırlık
- Programı normal kullanıcı olarak açın (yönetici olarak açmanız gerekmez; UAC penceresi gelecek).
- Soldaki menüde **Araçlar > Sürücü Yedekleme** görünmeli.

## 1. Liste
1. Sayfayı açın. Birkaç saniye "Sürücüler okunuyor…" yazar, sonra tablo dolar.
   - Beklenen: ekran kartı, Wi-Fi/Ethernet, ses, yonga seti gibi üreticinin sürücüleri. Microsoft'un kendi sürücüleri listelenmez.
2. Kontrol: PowerShell'de `Get-CimInstance Win32_PnPSignedDriver | ? InfName -match '^oem\d+\.inf$' | select DeviceName,InfName`
   - Beklenen: aynı INF'ler (tabloda aynı INF'i kullanan aygıtlar tek satırda "(+N)" ile birleşir).
3. Arama kutusuna "intel" yazın → yalnızca eşleşen satırlar kalır. "Tümünü Seç / Seçimi Kaldır" deneyin.

## 2. Yedekleme (klasöre)
1. Bir klasör seçin (ör. `D:\Yedek`), birkaç sürücüyü işaretleyin, **Seçili Sürücüleri Yedekle**.
2. Onay penceresi çıkar → UAC penceresi çıkar → Evet.
   - Beklenen: ilerleme çubuğu 1/N… N/N ilerler; sonunda "Yedekleme tamamlandı" ve boyut yazar.
3. Hedef klasörde şunlar olmalı:
   - `Surucu_Yedegi_<BilgisayarAdı>_<tarih>\Drivers\…` içinde her sürücü için alt klasör ve .inf/.sys/.cat dosyaları
   - `yedek_bilgisi.json`, `OKU.txt`, `Suruculeri_Geri_Yukle.bat`
4. UAC penceresinde **Hayır** deneyin → "Yönetici izni kullanıcı tarafından iptal edildi" benzeri hata, hiçbir şey yazılmamalı.
5. Yedek sırasında **İptal**'e basın → geçerli sürücü bitince durur, "iptal edildi" der, o ana kadarki sürücüler kalır.

## 3. USB'ye ekleme
1. Önce **USB Kurulum Aracı** ile bir kurulum belleği hazırlayın (bellek silinir).
2. Sürücü Yedekleme'de USB kutusunda belleğin harfi görünmeli (görünmezse yenile düğmesine basın).
3. **USB'ye Yedekle** → bellekte `Surucu_Yedegi_…` klasörü oluşmalı.
4. Uyarı: kurulum belleğini yeniden oluşturursanız yedek silinir; önce kurulum belleğini, sonra yedeği ekleyin.

## 4. Geri yükleme (önce güvenli deneme)
1. Sanal makine (Hyper-V/VirtualBox) ya da yedeklediğiniz aynı bilgisayar kullanın. Farklı donanıma yüklemeyin.
2. "Geri yükle" bölümünde yedek klasörünü (içinde `Drivers` olan klasör ya da Drivers'ın kendisi) seçin.
3. "Önce geri yükleme noktası oluştur" açık olsun → **Sürücüleri Geri Yükle** → onay → UAC.
   - Beklenen: işlem birkaç dakika sürer; sonunda günlük kutusunda pnputil çıktısı görünür.
   - Aynı sürücüler zaten yüklüyse "yeni sürücü bulunamadı" ya da "başarıyla eklendi" benzeri mesaj normaldir.
   - Geri yükleme noktası oluşmazsa (Sistem Koruması kapalı ya da 24 saat içinde başka nokta var) program uyarır ama sürücüleri yine yükler.
4. Yedek klasöründeki `Suruculeri_Geri_Yukle.bat` dosyasına çift tıklayın → UAC → pnputil çıktısı → "Bitti". Bu, program olmadan geri yüklemenin yoludur; gerçek bir temiz kurulumda bunu deneyin.

## 5. Sorunlu aygıtlar
- Aygıt Yöneticisi'nde sarı ünlemli aygıt varsa sağ panelde adı, sınıfı ve kod açıklaması görünmeli. Yoksa "Sorunlu aygıt bulunmadı" yazar.
- Devre dışı bırakılmış bir aygıt (kod 22) "sürücü sorunu sayılmaz" satırında sayılır.

## 6. Hata ve uç durumlar
- Boş alanı az olan diske yedek almayı deneyin → onay penceresinde boş alan uyarısı çıkmalı.
- Yedek sırasında programı kapatın → program takılmadan kapanmalı; yarım yedeğin klasörü kalır, silebilirsiniz.
- Sayfa açıkken USB'yi çıkarıp yenileyin → "USB bellek bulunamadı".

## Sorun olursa bana gönderin
- Sayfadaki geri yükleme günlüğü (kutudaki metin)
- `%LOCALAPPDATA%\Windows Update & Build Center\logs` içindeki son günlük dosyası
- Ekran görüntüsü ve hangi adımda ne olduğu
