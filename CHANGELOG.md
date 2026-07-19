
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
