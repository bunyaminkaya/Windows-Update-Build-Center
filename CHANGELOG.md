# v6.05 — ISO Merkezi tamamlandı ve uygulama içi Yardım sayfası

- **ISO Merkezi kalıyor ve tamamlandı** (kenar çubuğunda "ISO Merkezi", USB Kurulum Aracı'ndan önce):
  - Klasör taraması arka plan iş parçacığında yapılır (büyük klasörlerde arayüz donmaz); sayfa ilk açıldığında bir kez taranır, "Yeniden Tara" ile yenilenir. `.ISO` gibi büyük harfli uzantılar da bulunur.
  - SHA-256 hesabı arka planda, ilerleme göstererek yapılır ve kapanışta güvenle durdurulur.
  - Boş durum ekranı ("Henüz ISO bulunamadı" + "ISO Klasörü Ekle").
  - Yeni "USB Hazırlamaya Gönder" düğmesi: seçili ISO'yu doğrulayıp USB Kurulum Aracı'na aktarır ve o sayfaya geçer.
  - Tarama klasörleri artık Ayarlar'da `iso_center.scan_folders` altında tutulur; eski `iso_scan_folders` değeri otomatik taşınır. Ayarlar kaydedilirken silinmez (önceden siliniyordu).
  - Sayfanın kendi dağınık stil bloğu kaldırıldı; ortak stil dosyası kullanılır. İngilizce çeviriler eklendi.
- **Yeni Yardım sayfası (menüde Ayarlar'ın altında):** programın her bölümü için "Ne işe yarar / Nasıl kullanılır / Dikkat edilecekler / Daha fazla bilgi" yazıları, arama kutusu, Türkçe ve İngilizce. Yazılar uygulamanın içindedir, internet gerekmez. "Daha fazla bilgi" altında bunyaminkaya.com yazılarına bağlantılar bulunur (tıklanınca tarayıcıda açılır; hiçbir şey kendiliğinden açılmaz).
- Sol alttaki "Bu sayfa nasıl kullanılır?" düğmesi ve F1 artık bu sayfanın ilgili bölümünü açar; siteye yönlendirmez. İçerik ve bağlantılar tek dosyada: `ui/help_content.py`.
- Önceki `help_links` mekanizması kaldırıldı (gereksiz hale geldi).
- Testler: toplam 115.

# v6.05 — USB: SHA-256 doğrulama ve kurulum özelleştirme

- **ISO SHA-256 doğrulaması:** ISO kartında yeni anahtar. ISO'nun SHA-256 değeri USB'ye dokunulmadan ÖNCE hesaplanır (ilerleme ve hız gösterilir, iptal edilebilir). İsteğe bağlı "Beklenen SHA-256" kutusuna kaynaktan değer yapıştırılırsa karşılaştırılır; eşleşmezse işlem USB silinmeden durur. Değer günlükte gösterilir.
- **Kurulum Özelleştirme (yeni 5. kart):** Microsoft hesabı yerine yerel hesap (parolasız yönetici), bilgisayar adı, gizlilik/ekspres ayar sayfalarını atlama. Mevcut "Windows 11 donanım gereksinimlerini kaldır" seçeneğiyle birlikte tek bir `autounattend.xml` olarak yazılır (windowsPE / specialize / oobeSystem). Lisans sözleşmesi sayfası gizlenmez; disk seçimi gibi sorulara dokunulmaz.
- Değerler işlem başlamadan doğrulanır (hesap adı: ≤20 karakter, yasak karakterler ve ayrılmış adlar; bilgisayar adı: ≤15 karakter, harf/rakam/tire). Onay penceresi seçilen seçenekleri listeler.
- Özelleştirme seçilmezse ISO'nun kendi `autounattend.xml` dosyası artık silinmez (önceden silinirdi).
- ARM64 ISO'lar dosya adından tanınır ve XML bileşen mimarisi buna göre yazılır.
- İşlem sırasında yeni seçenekler kilitlenir. 5. aşama adı "Kurulum Seçenekleri" oldu.
- Yeni belge: `docs/USB_Ozellestirme_Test_Rehberi.md` (Windows'ta gerçek deneme adımları).
- Testler: servis (XML, doğrulamalar, SHA-256) ve sayfa akışı için ~30 yeni test.

# v6.05 — Açılış süresi kayıtları ve açılışta karşılama rehberi

- Yeni `app/startup_timing.py`: açılışın aşamaları (modüller, Qt, arayüz modülleri, pencere oluşturma, pencere görünür, ilk olay döngüsü) ve her sayfanın oluşturulma süresi ölçülür; açılış bitince `app.log` dosyasına tek satır yazılır: `Açılış süreleri: … | sayfalar toplam … (en yavaş: …)`. Açılış 5 saniyeyi aşarsa satır `Yavaş açılış` uyarısı olarak yazılır.
- Ayarlar > Genel > "Açılışta karşılama rehberini göster" (varsayılan kapalı): açıksa rehber her açılışta pencere oturduktan hemen sonra gösterilir. "Yeniden Göster" düğmesi eskisi gibi çalışır.
- Düzeltme: açılış hatası penceresi kodunda gereksiz yerel `import logging` kaldırıldı.
- Testler: 4 yeni birim testi (toplam 78).

# v6.05 — Ortak stil dosyası

- Yeni `ui/styles.py`: ana pencerenin ve tüm sayfaların paylaştığı QSS tek dosyada, bölümlere ayrılmış (yan menü, sayfa başlığı, kartlar, girdiler, düğmeler, tablolar, menüler, kaydırma çubuğu…). Renk/ölçü değerleri `TOKENS` içinde; QSS'te `@BLUE@` gibi yazılıp `styles.qss()` ile çevrilir.
- `main_window.py` içindeki ~570 satırlık stil metni bu dosyaya taşındı (görünüm birebir aynı).
- Sayfalardaki tekrarlar kaldırıldı: kaydırma çubuğu (11 dosyada kopya), açılır liste üzerine gelme rengi, sayfa başlığı/alt başlığı (30/28/25 px farklarıyla). Başlıklar artık her sayfada aynı boyutta (28 px).
- Birbirine çok yakın dört mavi ton (#2167D5, #1768E0, #246BD8, #1E67D8) tek `BLUE` değerine (#2167D5) indirildi.
- Koyu tema aynı metinden otomatik türetilmeye devam eder. Açık ve koyu temada tüm sayfaların ekran görüntüleri öncesi/sonrası karşılaştırıldı.
- Yeni sayfa stili yazarken: `self.setStyleSheet(styles.qss("""… @BLUE@ …"""))`; ortak bileşenler için sayfaya kopya yazmayın, `ui/styles.py`'ye ekleyin.

# v6.05 — Komut satırı çevirisi ve Sürüm Takibi hata penceresi

- `main.py --help` ve konsol mesajları artık seçili dile göre (Türkçe/English) yazılır.
- Sürüm Takibi: açılışta kayıtlar alınamazsa uzun teknik hata penceresi açılmaz; boş durum ekranı kısa açıklama ve "Şimdi Güncelle" düğmesi gösterir, teknik ayrıntı "Güncelleme başarısız" yazısının ipucundadır. "Şimdi Güncelle"ye elle basılıp hata olursa kısa bir uyarı penceresi çıkar.

# v6.05 — English dil desteği (2. aşama)

- Kalan sayfaların dinamik metinleri çevrildi: Sürüm Takibi, Güncelleme Geçmişi, Yüklü Güncellemeler, Favoriler, Uyumluluk, İndirme Yöneticisi (ISO aşamaları dahil), UUP / ISO Merkezi, Sistem güncelleme adımları ve hizmet katmanı hata/durum mesajları (~900 yeni çeviri).
- Çeviri motoru: tablo hücreleri ve özel çizilen metinler (`drawText`), sekme başlıkları, ileti kutuları ve sırası değişen kalıplar (`{1} … {0}`) desteklenir. Hücre verisi (mantık) Türkçe kalır, yalnızca görüntü çevrilir.
- Sürüm grafiği İngilizce ay adlarını kullanır.
- Microsoft'tan gelen veriler (güncelleme başlıkları, açıklamalar) kaynağın dilinde kalır.
- Not: komut satırı `--help` metni henüz Türkçe.

# v6.05 — English dil desteği (1. aşama)

- Ayarlar > Genel > Dil: Otomatik (Windows dili) / Türkçe / English. Varsayılan "Otomatik": Windows arayüz dili Türkçe ise Türkçe, değilse English. Değişiklik programı yeniden açınca uygulanır.
- Çeviri katmanı (`app/i18n.py`, sözlükler `app/i18n_en_*.py`) arayüz yüklenmeden önce devreye girer; Türkçede hiçbir ek yük yoktur. Sözlükte olmayan metin Türkçe kalır, program bozulmaz.
- Çevrilenler: yan menü, sayfa başlıkları ve düğmeleri, Ayarlar, Hakkında, USB Kurulum Aracı, Sürücü Yedekleme, karşılama rehberi, ortak pencereler ve dosya seçiciler. Combo kutularının görünen metni de çevrilir (kaydedilen değerler değişmez).
- Bilinen eksik giderildi (bkz. 2. aşama).
- Düzeltme: Hakkında sayfası "Son kontrol" metnini artık dilden bağımsız okur.
- Testler: 11 yeni birim testi (toplam 68).

# v6.05 — Sürücü Yedekleme

- Yeni sayfa: Araçlar > Sürücü Yedekleme. Üçüncü taraf (OEM) sürücüleri listeler (aygıt, sağlayıcı, sınıf, sürüm, tarih), seçilenleri `pnputil /export-driver` ile klasöre ya da kurulum USB'sine yedekler.
- Yedeğin yanına `yedek_bilgisi.json`, `OKU.txt` ve `Suruculeri_Geri_Yukle.bat` yazılır; yeni kurulumdan sonra .bat çift tıklanarak sürücüler geri yüklenir.
- Geri yükleme (`pnputil /add-driver … /subdirs /install`): işlemden önce onay penceresi, isteğe bağlı sistem geri yükleme noktası, sonuç günlüğü, yeniden başlatma uyarısı.
- Aygıt Yöneticisi'nde hata gösteren aygıtlar özetlenir (devre dışı aygıtlar sürücü sorunu sayılmaz).
- Yönetici izni tek UAC penceresiyle istenir; ilerleme çubuğu ve iptal vardır. Yalnızca üçüncü taraf sürücüler yedeklenir; bu sayfada açıkça yazılıdır.
- Testler: 14 yeni birim testi (toplam 57).

# v6.05 — Açılış hızı

- Açılışta USB disk taraması (PowerShell) artık arka planda yapılır; pencere bu işi beklemez.
- Ağır modüller yüklenirken hemen görünen küçük açılış ekranı eklendi.

# v6.05 — Kararlılık düzeltmeleri

- Düzeltme: Ağ isteği ya da indirme sürerken programdan çıkınca Qt "iş parçacığı çalışırken yok edildi" hatasıyla çökebiliyordu. Kapanış artık indirmeleri güvenle durdurur (yarım dosyalar sonraki açılışta devam eder), durumu kaydeder ve süreci temiz sonlandırır.
- Düzeltme: Program iki kez açılırsa aynı indirme/ayar dosyalarını bozabiliyordu. Artık tek kopya çalışır; ikinci açılış var olan pencereyi öne getirir.
- Testler: yeni özellikler için birim testleri eklendi (43 test).

# v6.05 — Görsel iyileştirmeler

- Boş tablolar için ikonlu açıklama ekranları (Geçmiş, Yüklü Güncellemeler, Sürüm Takibi).
- Hakkında: destek bölümü, USB satırı ve "Bu sürümde neler yeni" kartı.
- Yeni sürüm bildirimi yan menüde büyütüldü; koyu temada kenarlıklar ve yan menü tonu ayarlandı.
- Grafik: çubuk üzerine gelince ay/kanal/adet ipucu. Sürüm Takibi "Son güncelleme" etiketi kırpılması giderildi.

# v6.05 — Zamanlama, grafik ve komut satırı

- İndirme: Ayarlar > İndirme altında hız sınırı (512 KB/sn–10 MB/sn) ve gece zamanlaması (yeni indirmeler yalnızca seçilen saat aralığında başlar).
- Windows Sürüm Takibi: bu bilgisayarın build numarasını en yeni yayınla karşılaştıran şerit.
- Güncelleme Geçmişi: "Grafik" sekmesi (son 12 ay, kanallara göre yayın sayısı).
- Program içi güncelleme denetimi (Ayarlar > Genel, Hakkında > Güncellemeleri Denetle). app/version.py içindeki UPDATE_INFO_URL adresinde {"version","url","notes"} JSON dosyası yayımlanmalıdır.
- Ayarlar > Genel: "Bildirimi Dene" düğmesi.
- Komut satırı: --version, --installed, --latest [--channel --limit --json], --page, --minimized, --no-update-check.

# v6.05 — Koyu tema

- Ayarlar > Genel > "Tema": Açık / Koyu / Sistem (Windows ayarını izler). Değişiklik program yeniden açılınca uygulanır.
- Koyu mod tüm sayfaları, tabloları, rozetleri ve ikonları kapsar; yan menü her temada aynı koyu görünümde kalır.
- Altyapı: ui/theme.py (çalışma mantığına dokunmaz; açık tema davranışı değişmedi).

# v6.05 — Kısayollar, dışa aktarma ve yardım

- Klavye kısayolları: Ctrl+1…9 sayfa geçişi, Ctrl+0 Ayarlar, Ctrl+F sayfadaki arama kutusu, F1 yardım.
- Güncelleme Geçmişi ve Yüklü Güncellemeler sayfalarına "Dışa Aktar" (Excel ile açılabilen CSV) eklendi.
- USB onay penceresinde silinecek diskin adı, boyutu ve sürücü harfi belirginleştirildi.
- İndirme tablosunda doğrulama başarısız olursa "Tamamlandı ⚠ Doğrulanamadı" gösterilir.
- Yeni build kayıtları geldiğinde "Windows Sürüm Takibi" menü satırında okunmamış sayı rozeti görünür.
- Ayarlar > Gelişmiş: "Sorun bildirim paketi oluştur" (log + sistem bilgisi ZIP).
- Sol menüde "Bu sayfa nasıl kullanılır?" bağlantısı (adresler ui/help_links.py içinde).
- USB sayfasında açılışta kısa süre beliren boş pencereler düzeltildi.

# v6.05 — Menü yeniden adlandırma ve gruplama

- Sol menü üç gruba ayrıldı: GÜNCELLEMELER, ARAÇLAR, SİSTEM.
- Sayfa adları sadeleştirildi: Güncelleme Merkezi, Windows Sürüm Takibi, Yüklü Güncellemeler, Windows 11 Uyumluluğu, UUP ISO Oluşturucu, USB Kurulum Aracı.
- Her sayfanın alt başlığı, sayfanın amacını anlatan kısa bir cümleyle güncellendi.
- İlk açılışta 3 adımlık karşılama rehberi eklendi (bir kez gösterilir).
- Güncelleme Merkezi menü satırındaki ev simgesi kaldırıldı.

# v6.05 — Favorilerim ana menüye taşındı

- Favorilerim artık açılır pencere yerine ana uygulamanın sol menüsünde ayrı bir sayfa olarak çalışıyor.
- Favorilerim, USB Kurulum Merkezi'nin hemen altına eklendi.
- Eski Favorilerim açılır pencere tetikleyicisi kaldırıldı; ana arama ekranındaki Favorilere Ekle işlemi korunuyor.
- Favoriler sayfası mevcut açık tema ve uygulama tasarım diliyle aynı çalışma alanında açılıyor.

# v6.04 — Favoriler ekranı tasarım yenilemesi

- Favoriler penceresi genel uygulama tasarım diliyle uyumlu açık tema çalışma alanına dönüştürüldü.
- Arama, yenileme, Microsoft sayfası ve tümünü temizleme işlemleri düzenlendi.
- Favori ayrıntıları sağ panelde, kaldırma ve arama işlemleri alt aksiyonlarda toplandı.

# v6.02

- UUP Merkezi açılış hatası düzeltildi.
- Dil seçici oluşturulmadan önce ayarların uygulanmasına neden olan `language_combo` sıralama hatası giderildi.
- UUP Merkezi artık ana program içinde normal şekilde başlatılıyor.

# v6.03 — Başlangıç ve tepsi görünürlük düzeltmeleri

- Bildirimler açık olduğu için programın yalnızca sistem tepsisinde görünmesi engellendi. Tepsi simgesi artık yalnızca arka planda çalışma veya tepsiye küçültme seçildiğinde gösteriliyor.
- Bir sayfanın açılış hatası ana pencerenin başlamasını engellemiyor; sorunlu sayfa yerine hata bilgisi gösteriliyor ve ayrıntı loglanıyor.
- Ana pencere başlatma hataları artık windowed EXE içinde kullanıcıya görünür bir hata iletişim kutusuyla bildiriliyor.

# v6.00 — UUP Merkezi geliştirmeleri

- En yeni UUP build'lerini otomatik listeleme.
- Sürüm, kanal ve mimari filtreleri.
- Çoklu dil seçimi.
- Windows 11 Home, Pro ve Enterprise edition seçimi.
- UUP indirme ilerlemesi ve batch takibi.
- UUP tamamlandığında otomatik ISO oluşturma.
- ISO boyut kontrolü ve SHA-256 doğrulaması.
- UUP indirmelerinde `.part` üzerinden yarım kalan işlemi sürdürme.
- UUP/ISO görevleri için "Önceki İşlemi Sürdür" akışı.
- Build Tracker'dan UUP Merkezi'ne build aktarımı korunmuştur.

# v5.99

- Yüklü KB sayfası, referans tasarıma göre yeniden düzenlendi.
- Ayrı detay paneli ve seçili KB için gerçek "Kaldır" düğmesi eklendi.
- Yüklü KB satırına çift tıklama kaldırma akışını başlatır.
- Kaldırma öncesi yönetici yetkisi, kullanıcı onayı ve sistem geri yükleme noktası kontrolü zorunlu hale getirildi.
- Geri yükleme noktası oluşturulamazsa kaldırma işlemi engellenir.
- Uyumluluk sayfasındaki bağımsız mavi sekme kaldırıldı.
- Yüklü KB sayfasındaki bağımsız mavi sekme kaldırıldı.

# v5.98

- Sistem & Güncelleme Merkezi kaldırıldı.
- Bilgisayar Uyumluluğu bağımsız sol menüye taşındı.
- Yüklü KB Güncellemeleri bağımsız sol menüye taşındı.
- Yüklü KB kaldırma işlemi gerçek WUSA kaldırma akışıyla eklendi.
- KB kaldırmadan önce geri yükleme noktası zorunlu; oluşturulamazsa işlem engelleniyor.
- Uyumluluk ve Yüklü KB ekranlarına kısa açıklama metinleri eklendi.

## v5.97
- Favoriler ekranı yeniden tasarlandı: tablo, arama, detay paneli, Microsoft kaynak bağlantısı, aramayı geri yükleme, tekli/toplu silme ve yenileme eklendi.
- Favoriler artık boş/siyah liste görünümü yerine gerçek bir yönetim çalışma alanı olarak açılıyor.

## v5.96
- 6. adım tamamen yenilendi: Windows sürümü/build, x64/ARM64, TPM 2.0, Secure Boot, disk, CPU, RAM, dil, edition ve güncelleme kanalı birlikte kontrol ediliyor; hedef build/KB ile karşılaştırma ekranı eklendi.
- 7. adım genişletildi: yüklü KB, açıklama, kurulum tarihi, kaynak, kaldırılabilirlik ve kaldırma komutu; Build Tracker ile eksik KB kontrolü ve son Windows Update başarısızlık taraması eklendi.
- 8. adım genişletildi: KB için Catalog ürün/sınıf/sürüm/tarih/boyut bilgileri ve paket ayrıntı penceresi eklendi.
- 9. adım yenilendi: x64/ARM64, sistem dili, paket rolü ve normal LCU ile Dynamic Update/Safe OS ayrımı puanlanarak önerilen paket otomatik öne çıkarılıyor.
- 10. adım güvenlik zincirine dönüştürüldü: indirme öncesi HTTPS + Microsoft kaynak + mimari/paket rolü kontrolü; indirme sonrası otomatik SHA-256 ve Authenticode kontrolü. İsteğe bağlı beklenen SHA-256 karşılaştırması eklendi.
- İndirme Yöneticisi tamamlanan Microsoft Catalog paketlerini otomatik doğruluyor; doğrulama başarısızsa dosyayı siliyor ve yeniden indirme kuyruğuna alıyor.
- 11. adım güvenli kurulum kapısı oldu: kurulumdan hemen önce tekrar doğrulama, yönetici kontrolü, geri yükleme noktası, MSU/CAB/EXE kurulumu, yeniden başlatma tespiti ve yaygın hata kodları için Türkçe açıklamalar eklendi.
- 12. adım Windows Update/BITS, disk, pending reboot, DISM, SFC, önbellek ve son hata olaylarını tek raporda topluyor.

## v5.95
- Sistem & Güncelleme Merkezi eklendi: uygunluk, yüklü KB, Build Tracker karşılaştırması, KB paket seçimi, SHA-256/Authenticode doğrulaması, MSU/CAB/EXE kurulumu ve Windows Update tanılama.
- Kurulumdan önce isteğe bağlı geri yükleme noktası oluşturma ve yönetici yetkisi kontrolü eklendi.
- Windows Update/BITS servisleri, bekleyen yeniden başlatma, DISM/SFC ve son hata kodları raporlanıyor.

## v5.81
- Hakkında sayfasındaki üst banner zemini, programın ana arka plan rengiyle uyumlu hale getirildi.
- Brand banner görselindeki farklı açık mavi zemin temizlenerek ana sayfa zemin tonuna yaklaştırıldı.
- Hakkında ekranındaki banner gösterim boyutu bir miktar büyütülerek daha dengeli görünüm sağlandı.

## v5.80
- Hakkında ekranındaki kurumsal banner program arayüzüne uyumlu açık mavi zeminli sürümle güncellendi.
- Banner sabit küçük boyuttan çıkarılıp 900x170 hedef ölçüsünde daha büyük ve dengeli gösterilecek şekilde düzenlendi.
- Banner alanının yükseklik ve genişleme davranışı iyileştirildi; Hakkında kartının zeminiyle görsel bütünlük sağlandı.
- Programın açılışta maksimum pencere olarak başlama davranışı korundu.

## v5.79
- Hakkında sayfasındaki marka bannerı temiz beyaz arka planlı sürümle değiştirildi; transparan/dama desenli görünüm kaldırıldı.
- Program başlangıçta artık doğrudan maksimum pencere boyutunda açılıyor.
- Görev çubuğu ve pencere simgesi altyapısı korunuyor.


## v5.78
- EXE oluşturma altyapısı düzeltildi.
- PyInstaller çalışma, dist ve spec klasörleri açıkça oluşturuluyor.
- PyInstaller iç build adında nokta yerine alt çizgi kullanılıyor.
- Sorun çıkaran `.build_venv` bağımlılığı kaldırıldı; aktif Python ortamı kullanılıyor.
- Büyük ve kullanılmayan ML/bilimsel paketlerin yanlışlıkla pakete dahil edilmesi engellendi.
- `EXE_Build.log` ve gerçek çıktı kontrolü korunuyor.
# v5.76

- EXE oluşturma komut dosyalarındaki `call %PY_CMD%` kaynaklı sonsuz batch çağrısı kaldırıldı.
- Python Launcher (`py.exe -3`) ve `python.exe` doğrudan çalıştırılıyor.
- `Maximum setlocal recursion level reached` hatası giderildi.
- EXE oluşturma loglama ve doğrulama sistemi korundu.


## v5.74
- Windows görev çubuğu simgesi için native HWND ikon uygulaması eklendi.
- WM_SETICON ile büyük/küçük ikon ve pencere sınıfı ikonları zorlanıyor.
- Kaynak koddan python.exe ile çalıştırmada görülebilen generic/boş görev çubuğu simgesi düzeltildi.

# v5.73

- USB oluşturma sırasında görülen Windows çıkış kodu 112 (disk dolu) için WIM geçici çalışma alanı yönetimi yeniden düzenlendi.
- `install.wim` bölme işlemi artık körü körüne sistem TEMP klasöründe çalışmıyor; ISO'nun bulunduğu klasör ve uygun sabit diskler boş alan durumuna göre değerlendiriliyor.
- İşlem başlamadan önce WIM bölme için gerekli yaklaşık boş alan hesaplanıyor; yetersizse DISM başlatılmadan anlaşılır hata veriliyor.
- DISM `Split-Image` işlemine seçilen çalışma diskinde özel `/ScratchDir` eklendi.
- Windows hata kodu 112 artık doğrudan "çalışma diskinde alan yok" mesajına dönüştürülüyor.


## v5.72
- USB Kurulum Merkezi'nde SWM dosyalarının geçici klasörde yönetici yetkili DISM tarafından oluşturulması sonrası oluşabilen erişim/ACL sorunu düzeltildi.
- SWM dosyaları okunamıyorsa uygulama kısa süre bekliyor, ardından geçici çalışma klasörünün izinlerini mevcut kullanıcı SID'sine güvenli biçimde geri veriyor.
- SWM kopyalama ilerlemesi yeniden düzenlendi: hazırlık 0-70%, SWM kopyalama 70-100%.
- Aşama 3 ilerleme göstergesinin %53 civarında takılı kalmış gibi görünmesine neden olan ara faz hesaplaması düzeltildi.
- Mevcut USB servis regresyon testlerinin tamamı başarıyla geçti.
## v5.70

## v5.71
- USB hazırlama PowerShell akışında `Initialize-Disk` yalnızca disk RAW ise çalıştırılır.
- `Clear-Disk` sonrasında Windows Storage otomatik yenileme/claim yarışına karşı `Update-Disk` ve durum bekleme eklendi.
- Disk zaten hedef bölüm stilindeyse yeniden initialize edilmez; farklı stildeyse boş disk `Set-Disk -PartitionStyle` ile dönüştürülür.
- Bölüm oluşturulmadan önce hedef GPT/MBR durumunun gerçekten uygulandığı doğrulanır.
- Windows Build Tracker açılışında kaldırılmış `microsoft_button` referansı nedeniyle oluşan AttributeError düzeltildi.
- Sayfa ilk kayıt seçildiğinde yalnızca mevcut `package_button` ve `article_link` kontrollerini güncelliyor.

# v5.66

- USB Kurulum Merkezi kalan süre hesaplama motoru yenilendi.
- İlk 15 saniyede ve yeterli veri aktarılmadan kalan süre gösterilmiyor; bunun yerine "kalan süre hesaplanıyor..." yazıyor.
- Hız hesabı tek bir anlık örnek yerine son 30 saniyelik hareketli pencere üzerinden yapılıyor.
- İlk klasör oluşturma/küçük dosya metadata işlemlerinin 40 saat gibi gerçek dışı tahminler üretmesi engellendi.
- Tahmini kalan sürede ani yukarı/aşağı sıçramalar sınırlandırıldı.
- Normal kopyalama, paralel WIM hazırlama ve SWM kopyalama aşamalarının tamamı aynı stabil tahmin motorunu kullanıyor.

# v5.65

- FAT32 hedeflerde USB, Rufus'un varsayılan davranışıyla aynı şekilde 32K küme (allocation unit) boyutuyla biçimlendiriliyor; bu, Windows kurulum medyasındaki on binlerce küçük dosya için FAT tablosu metadata yazımını ciddi oranda azaltıp kopyalamayı hızlandırır.
- Küme boyutu, hedef bölüm gerçek boyutuna göre otomatik ölçekleniyor (gerekirse 16K/8K'ya düşer) — çok küçük FAT32 hedeflerde DiskPart'ın küme sayısı sınırını aşıp hata vermesi engellendi.
- NTFS hedeflerde küme boyutu bilinçli olarak varsayılanda bırakıldı (NTFS küçük dosyaları MFT üzerinden zaten verimli tutuyor).
- Yeni regresyon testleri eklendi (küçük/büyük FAT32 hedefler, NTFS varsayılanı).

# v5.64

- USB oluşturma performansı iyileştirildi.
- install.wim bölme işlemi USB yerine sistemin hızlı geçici alanında yapılır.
- Normal Windows dosyaları ile WIM hazırlığı paralel yürütülür.
- Robocopy çok iş parçacıklı `/MT:16` ve büyük dosyalarda `/J` ile çalışır.
- USB kopyalama sırasında gerçek aktarım hızı, yüzde ve tahmini kalan süre gösterilir.
- SWM parçaları hazırlandıktan sonra USB'ye çok iş parçacıklı kopyalanır.

# Changelog

## v5.63
- FAT32 için 4 GB üzerindeki `install.wim` dosyasını bölen DISM işlemi artık gerektiğinde UAC ile yönetici yetkisiyle çalıştırılır.
- DISM 740 / yükseltme gerekiyor hatası giderildi.
- `install.swm` çıktı doğrulaması eklendi.

## v5.62
- DiskPart bölüm stili dönüşümü betik modunda güvenli/idempotent hale getirildi.
- GPT hedeflerde `convert gpt noerr`, MBR hedeflerde `convert mbr noerr` kullanılıyor.
- USB zaten hedef bölüm stilindeyse DiskPart artık dönüşüm uyarısında durmuyor ve bölüm oluşturma/biçimlendirme adımlarına devam ediyor.
- GPT ve MBR için tekrar çalıştırılabilir DiskPart betiği regresyon testleri eklendi.

## v5.58

- Fixed USB creation failure with Windows error 740 (elevation required).
- DiskPart now requests UAC elevation only when privileged disk operations begin.
- BootSect MBR operations use the same elevated execution path.
- The main application can remain non-elevated; users only approve the standard Windows UAC prompt when required.

All notable changes to Windows Update & Build Center are documented here.

## v5.57

### GitHub publishing package
- Repository structure cleaned for public source publishing.
- Added `.gitignore` for Python caches, build outputs, runtime databases, logs, downloads and generated Windows media.
- Added `LICENSE` and `CHANGELOG.md`.
- Replaced the old development-history README with a public project README.
- Added `GitHub_Guncelle.bat` for the first push and later updates from the same project folder.
- Runtime database and cached tracker data were removed from the source package; the application recreates required runtime files automatically.

## v5.56
- Added USB Installation Center.
- Added ISO selection, removable-drive selection, GPT/MBR and file-system options.
- Added bootable USB creation workflow and Windows 11 hardware-requirement bypass option.

## v5.55
- Redesigned navigation sidebar with grouped menu sections and active-state cards.
- Removed duplicate page titles from content areas.

## v5.54
- Renamed the application to Windows Update & Build Center.
- Added the new application logo, taskbar icon and EXE branding.

For older development history, see the Git commit history and releases.

## v5.61
- USB DiskPart betiğinde yeni oluşturulan bölüm artık açıkça `select partition 1` ile seçiliyor.
- `There is no volume selected` hatası giderildi.
- MBR hedeflerde `active` komutu doğru sıraya taşındı.
- GPT/FAT32 ve MBR/NTFS DiskPart komut sıraları için regresyon testleri eklendi.
## v5.67
- Windows başlangıç kaydı `WindowsUpdateBuildCenter` olarak düzeltildi; eski kayıt temizleniyor.
- Ayarlar atomik `.tmp -> replace` yöntemiyle kaydediliyor ve son sağlam yedek korunuyor.
- Kullanıcı verileri `%LOCALAPPDATA%\Windows Update & Build Center` altına taşındı; eski veriler kayıpsız göç ettiriliyor.
- USB silinmeden önce ISO boyutu ile gerçek kullanılabilir USB kapasitesi karşılaştırılıyor.
- Geçici ağ hatalarında indirmelerin otomatik yeniden deneme kuyruğuna gerçekten dönmemesi hatası düzeltildi.
- Arama geçmişi son 100 kayıtla sınırlandı.
- Kullanılmayan `packages`, `downloads`, `app_state` tabloları yeni mimariden temizlendi.


## v5.68
- USB bölüm hazırlama altyapısı stateful DiskPart betiğinden Windows Storage PowerShell cmdlet'lerine taşındı.
- `There is no volume selected` ve tekrar denemelerde yanlış bölüm stili/odak hataları ortadan kaldırıldı.
- Disk hazırlama artık açık nesnelerle `Clear-Disk -> Initialize-Disk -> New-Partition -> Format-Volume` zincirini kullanıyor.
- GPT/MBR, FAT32/NTFS, 32 GB üstü FAT32 bölümü ve sürücü harfi marker akışları için yeni regresyon testleri eklendi.

## v5.77
- EXE oluşturma sistemi Windows batch komutlarının iç içe çağrılmasına bağımlı olmaktan çıkarıldı.
- Yeni `build_exe.py`, her derleme için proje içinde izole `.build_venv` ortamı kullanıyor.
- PyInstaller artık yalnızca projenin gerçek bağımlılıklarını içeren temiz ortamda çalışıyor; global Python paketleri derlemeyi kirletmiyor.
- `EXE_Olustur.bat` ve `build.bat` yalnızca Python derleme aracını başlatan sade ve recursion-safe yapıya geçirildi.
- Oluşan çıktı dosyası derleme sonunda fiziksel olarak doğrulanıyor ve ayrıntılı `EXE_Build.log` tutuluyor.
- PyInstaller paketleme akışı gerçek ortamda başarıyla tamamlandı ve oluşturulan paket başlatma testiyle doğrulandı.
# v5.82

- Windows Build Tracker canlı güncellemesi için WordPress REST yedek veri yolu eklendi.
- Canlı güncelleme başarısız olduğunda eski önbelleğin sessizce gösterilmesi düzeltildi.
- GA / Retail, Release Preview, Beta, Experimental, Dev ve Canary satırları sitedeki renklerle eşleştirildi.
# v5.83

- Build Tracker tablosunda her satırın tamamı ait olduğu kanalın rengiyle boyandı.
- Tablo sütun ölçüleri referans tasarımdaki oranlara sabitlendi.
- Yeni Güncellemeler kartlarındaki rozet ve kart renkleri doğrudan gerçek kanala bağlandı.
# v5.84

- Windows stil motorunun satır renklerini beyaza çevirmesi engellendi.
- Build Tracker satırları arka plan, metin ve ayırıcılarıyla doğrudan kanal paletinde çiziliyor.
# v5.85

- Yeni Build Bildirim Merkezi eklendi.
- Yeni kayıt bulunduğunda build, KB, sürüm ve kanal bilgisiyle Windows bildirimi gösteriliyor.
- Bildirime tıklayınca Build Tracker açılıp ilgili kayıt seçiliyor.
- Ayarlara bildirim açma/kapatma ve kanal seçimi eklendi.
- İlk açılışta mevcut kayıtlar için toplu bildirim gösterilmesi engellendi.
# v5.86

- Build Tracker tablosuna iki build seçerek karşılaştırma özelliği eklendi.
- Build numarası, KB, kanal geçişi ve yayın tarihleri yan yana gösteriliyor.
- Eklenen özellikler, düzeltilen sorunlar ve bilinen sorunlar ilgili içerik ve Microsoft kaynaklarından okunuyor.
- Kaynakta bulunmayan bilgi uydurulmadan açıkça belirtiliyor.
# v5.87

- Build karşılaştırma üst sınırı üç build'e çıkarıldı; iki build karşılaştırması korunuyor.
- Karşılaştırma penceresindeki toplu geçiş şeridi kaldırıldı.
- Her karşılaştırma sütununun başlığı kendi build numarası olacak şekilde düzenlendi.
- KB numarası build başlığı yerine yalnızca ilgili bilgi alanında gösteriliyor.
# v5.88

- Build Tracker Takip Listesi eklendi.
- Windows 11 sürümleri ve Insider/kararlı kanallar ayrı ayrı takip edilebiliyor.
- Belirli KB numarası veya 26300 gibi build ailesi takip listesine eklenebiliyor.
- Takip filtresi açıkken yalnız eşleşen yeni kayıtlar Windows bildirimi oluşturuyor.
- Etkin takip ölçütlerinin özeti Build Tracker ekranında gösteriliyor.
# v5.89

- Takip edilen sürüm ve kanal seçimleri görünür seçim kartlarına dönüştürüldü.
- Seçilmemiş kartlara +, seçilmiş kartlara ✓ işareti ve renkli zemin eklendi.
- Sürüm ve kanal gruplarına Tümünü seç ve Seçimi temizle eylemleri eklendi.
- Ayar açıklamaları seçeneklerin tıklanabilir olduğunu açıkça belirtecek şekilde yenilendi.
# v5.90

- v5.89 EXE'nin açılışta kapanmasına neden olan eksik QGridLayout içe aktarımı düzeltildi.
- Takip listesi seçim kartlarının Ayarlar sayfasında güvenli biçimde oluşturulması sağlandı.
# v5.91

- Hakkında bölümüne ayrı Güncelleme Geçmişi ekranı eklendi.
- Bugün, Bu Hafta ve Bu Ay bulunan yeni kayıt ve kontrol sayıları gösteriliyor.
- Her kontrolün tarih-saat, başarı durumu, yeni kayıt sayısı ve toplam kayıt sayısı saklanıyor.
- Yeni bulunan build/KB kayıtları geçmiş tablosunda ayrıntılı gösteriliyor.
- Başarısız Build Tracker kontrolleri hata açıklamasıyla geçmişe kaydediliyor.
# v5.92

- Güncelleme Geçmişi Hakkında bölümündeki pencereden çıkarıldı.
- Sol ana menüye bağımsız Güncelleme Geçmişi bölümü eklendi.
- Geçmiş artık ana içerik alanında tam sayfa olarak açılıyor.
- Güncelleme Geçmişi menüsü Windows Build Tracker'ın hemen altına yerleştirildi.
# v5.94

- Seçili build için Microsoft kaynaklı Bilinen Sorunlar ekranı eklendi.
- Sorun açıklaması, etkilenen sürüm, çözüm durumu, geçici çözüm ve Microsoft bağlantısı gösteriliyor.
- Program açılışta tam ekran ve Windows Build Tracker seçili başlayacak şekilde düzenlendi.

# v5.93

- Güncelleme Geçmişi üst kartları gerçek build yayın tarihlerine göre hesaplanıyor.
- Bu hafta ve bu ay yayımlanmış eski kayıtların sıfır görünmesi düzeltildi.
- Yayınlanan Güncellemeler ve Kontrol Geçmişi ayrı sekmelere ayrıldı.
- Yayınlanan Güncellemeler sekmesine Bugün, Bu Hafta, Bu Ay ve Tümü filtreleri eklendi.
- Build, KB, Windows sürümü, kanal ve açıklama bilgileri yayın tablosunda gösteriliyor.
