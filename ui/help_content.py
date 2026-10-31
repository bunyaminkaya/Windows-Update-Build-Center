"""Yardım sayfasının içeriği (Türkçe ve İngilizce birlikte).

Her bölüm: anahtar (kenar çubuğundaki sayfa adı), simge, başlık, "what" (sayfanın ne işe yaradığı;
paragraflar boş satırla ayrılır), "steps" (sırayla yapılacaklar), "notes" (bilinmesi gerekenler) ve
site bağlantıları. Metinler ``(tr, en)`` çiftidir. Bağlantıyı değiştirmek için yalnızca bu dosya düzenlenir.
"""
from __future__ import annotations

SITE = "https://bunyaminkaya.com"


def _u(path: str) -> str:
    return f"{SITE}/{path}"


# (Türkçe etiket, İngilizce etiket, adres)
L_BUILD_TRACKER = ("Windows Build Tracker (web aracı)", "Windows Build Tracker (web tool)", _u("windows-build-tracker/"))
L_VERSION_QUERY = ("Windows sürüm ve destek sorgulayıcı", "Windows version and support lookup", _u("windows-surum-ve-destek-sorgulayici/"))
L_INSIDER = ("Windows Insider Programı nedir, nasıl kayıt olunur?", "What is the Windows Insider Program and how to join", _u("windows-insider-programi-nedir-nasil-kayit-olunur/"))
L_UUP = ("UUP ile Windows ISO oluşturma", "Creating a Windows ISO with UUP", _u("uup-windows-10-iso-olusturma/"))
L_ISO_DL = ("Windows 11 ISO dosyası", "Windows 11 ISO file", _u("windows-11-iso-dosyasi/"))
L_ISO_25H2 = ("Windows 11 25H2 ISO indir", "Download Windows 11 25H2 ISO", _u("windows-11-25h2-iso-indir/"))
L_ISO_BLOCKED = ("Windows ISO indirme engellendi mi?", "Is the Windows ISO download blocked?", _u("windows-iso-indirme-engellendi-mi/"))
L_ISO_DOWNLOADER = ("Windows ISO Downloader", "Windows ISO Downloader", _u("windows-iso-downloader/"))
L_SHA = ("SHA-256 dosya doğrulama (web aracı)", "SHA-256 file verification (web tool)", _u("sha-256-dosya-dogrulama/"))
L_RUFUS_BYPASS = ("Windows 11 gereksinimlerini Rufus ile atlama", "Bypassing Windows 11 requirements with Rufus", _u("windows-11-gereksinim-atlama-rufus/"))
L_UEFI_USB = ("UEFI önyüklenebilir USB oluşturma", "Creating a UEFI bootable USB", _u("uefi-onyuklenebilir-windows-10-usb-surucu-yukleyicisi-nasil-olusturulur/"))
L_CMD_USB = ("Komut istemiyle önyüklenebilir USB", "Bootable USB with the command prompt", _u("komut-istemini-kullanarak-windows-10u-yuklemek-icin-onyuklenebilir-bir-usb-nasil-olusturulur/"))
L_NO_USB = ("USB kullanmadan Windows 11 temiz kurulum", "Clean install of Windows 11 without a USB", _u("usb-kullanmadan-windows-11-temiz-kurulum/"))
L_SECURE_BOOT = ("Secure Boot 2023 sertifikaları", "Secure Boot 2023 certificates", _u("secure-boot-2023-sertifikalari/"))
L_SECURE_BOOT_UPD = ("Secure Boot sertifikası güncelleme", "Updating the Secure Boot certificate", _u("secure-boot-sertifikasi-guncelleme/"))
L_BACKUP = ("Windows 10'u düzgün yedekleme", "Backing up Windows properly", _u("windows-10u-nasil-duzgun-yedeklenir/"))
L_BLOCK_DRIVER = ("Belirli aygıtlar için sürücü güncellemesini engelleme", "Blocking driver updates for specific devices", _u("windows-10da-belirli-aygitlar-icin-surucu-guncellestirmelerini-nasil-engeller/"))
L_ERROR_CODE = ("Windows hata kodu açıklayıcı (web aracı)", "Windows error code explainer (web tool)", _u("windows-hata-kodu-aciklayici/"))
L_TOOLS = ("Diğer web araçları", "More web tools", _u("araclar/"))

SECTIONS = [
    {
        "key": "Başlarken",
        "icon": "info-outline",
        "title": ("Başlarken", "Getting started"),
        "what": (
            "Windows Update & Build Center, Windows'un güncelleme tarafını tek pencerede toplar: yeni çıkan build'leri izler, KB paketlerini bulur, ISO hazırlar ve bunu önyüklenebilir bir USB belleğe yazar.\n\n"
            "Nereden başlayacağınızı bilmiyorsanız ihtiyacınızı düşünün. Neyin yayımlandığını öğrenmek istiyorsanız Güncelleme Merkezi ile Windows Sürüm Takibi, kurulum dosyası lazımsa UUP ISO Oluşturucu ile ISO Merkezi, bilgisayarı sıfırdan kuracaksanız USB Kurulum Aracı ile Sürücü Yedekleme işinizi görür.",
            "Windows Update & Build Center brings the update side of Windows into one window: it follows new builds, finds KB packages, prepares ISOs and writes them to a bootable USB drive.\n\n"
            "If you are not sure where to begin, start from what you need. To see what has been released, use Update Center and Windows Build Tracking; for an installation file, UUP ISO Builder and ISO Center; and for a fresh install, USB Install Tool and Driver Backup.",
        ),
        "steps": [
            ("Soldaki menü Güncellemeler, Araçlar ve Sistem olmak üzere üç gruba ayrılır. İhtiyacınıza en yakın gruptan bir sayfa açarak başlayın.",
             "The menu on the left is split into three groups: Updates, Tools and System. Open a page from the group closest to what you need."),
            ("Bir sayfada ne yapacağınızı bulamazsanız sol alttaki \"Bu sayfa nasıl kullanılır?\" düğmesine ya da F1 tuşuna basın. Yardım, doğrudan o sayfanın bölümünde açılır.",
             "If you cannot work out what to do on a page, press the \"How do I use this page?\" button at the bottom left or F1. Help opens right at that page's section."),
            ("Klavyeyle çalışmayı seviyorsanız Ctrl+1'den Ctrl+9'a kadar ilk dokuz sayfaya geçebilir, Ctrl+0 ile Ayarlar'ı, Ctrl+F ile sayfadaki arama kutusunu açabilirsiniz.",
             "If you prefer the keyboard, Ctrl+1 to Ctrl+9 jump to the first nine pages, Ctrl+0 opens Settings and Ctrl+F focuses the search box on the page."),
            ("Dili (Türkçe ya da English) ve açık ya da koyu temayı Ayarlar > Genel bölümünden seçersiniz.",
             "You choose the language (Türkçe or English) and the light or dark theme in Settings > General."),
        ],
        "notes": [
            ("Program, siz bir düğmeye basmadıkça bir işlem başlatmaz. Tek istisna, yeni build'leri arka planda kontrol eden Sürüm Takibi'dir.",
             "The program does not start anything until you press a button. The only exception is Build Tracking, which checks for new builds in the background."),
            ("Windows'a yazan işlemler (USB hazırlama, sürücü geri yükleme, güncelleme kaldırma) başlamadan önce onay ister; yanlışlıkla bir şeyin değişmesinden çekinmenize gerek yok.",
             "Actions that write to Windows (preparing a USB, restoring drivers, uninstalling updates) ask for confirmation before they start, so nothing changes by accident."),
        ],
        "links": [L_TOOLS],
    },
    {
        "key": "Güncelleme Merkezi",
        "icon": "windows-outline",
        "title": ("Güncelleme Merkezi", "Update Center"),
        "what": (
            "Elinizde bir KB ya da build numarası varsa Microsoft Update Catalog'daki resmi paketi buradan bulup indirebilirsiniz. Windows Update'in size sunmadığı ya da bir türlü kuramadığı bir güncellemeyi elle edinmenin en kısa yolu budur.\n\n"
            "Sonuçlar doğrudan Microsoft'un kataloğundan geldiği için paketi bir üçüncü taraf siteden aramanız gerekmez.",
            "If you have a KB or build number, you can find the official package in the Microsoft Update Catalog and download it here. It is the quickest way to get an update by hand when Windows Update does not offer it or keeps failing to install it.\n\n"
            "Results come straight from Microsoft's catalog, so you do not have to hunt for the package on a third-party site.",
        ),
        "steps": [
            ("Arama kutusuna KB5101650 ya da 26200.8875 gibi bir değer yazıp Ara'ya basın.",
             "Type a value such as KB5101650 or 26200.8875 in the search box and press Search."),
            ("ISO arıyorsanız KB ya da build numarası yerine 25H2 ya da 26H2 gibi bir sürüm adı yazın. Sonuçta tek bir ISO kaydı çıkar; program indirirken önce Microsoft'un resmi ISO'sunu dener, yoksa UUP ile hazırlar. Microsoft'tan İndir sizi ISO Merkezi'ne götürür; mimariyi ve dili orada seçip İndir'e basarsınız, dosya İndirme Yöneticisi'ne düşer.",
             "If you are after an ISO, type a version name such as 25H2 or 26H2 instead of a KB or build number. A single ISO record appears; when downloading, the program tries Microsoft's official ISO first and prepares one with UUP if it is not there. Download from Microsoft takes you to the ISO Center, where you choose the architecture and language and press Download; the file lands in the Download Manager."),
            ("Listeden bir paket seçtiğinizde ayrıntıları sağ panelde açılır; indirmeden önce aradığınız paket olduğundan emin olmak için oraya göz atın.",
             "When you select a package its details open in the right panel; glance at them to be sure it is the one you want before downloading."),
            ("İndirme seçeneklerinden birini kullanın. İndirme, İndirme Yöneticisi'nde ilerler; oradan durdurabilir ya da kaldığı yerden sürdürebilirsiniz.",
             "Use one of the download options. The download runs in the Download Manager, where you can pause it or carry on from where it stopped."),
            ("Sonra dönmek isterseniz kaydı Favorilere Ekle ile saklayın. UUP'ye Git ise aynı build için ISO seçeneklerini açar.",
             "To come back to it later, keep the record with Add to Favorites. Go to UUP opens the ISO options for the same build."),
        ],
        "notes": [
            ("Arama için internet bağlantısı gerekir; gördüğünüz kayıtlar Microsoft Update Catalog'un döndürdüğü kayıtlardır.",
             "Searching needs an internet connection; the records you see are the ones the Microsoft Update Catalog returns."),
            ("Microsoft resmi sitesinde yalnızca şu an sunduğu sürümün ISO'sunu verir; aradığınız sürüm farklıysa program soru sormadan UUP'ye geçer. Microsoft isteği reddederse (IP ya da VPN kontrolü gibi) program otomatik olarak UUP kaynağına geçip indirmeyi aynı seçimlerle başlatır ve sonraki aramalarda UUP'yi öne alır. UUP için build, Windows Sürüm Takibi verisinden bulunur; liste boşsa orada Şimdi Güncelle'ye basın.",
             "Microsoft's official site only offers the ISO of the version it currently serves; if you searched for another one the program switches to UUP without asking. If Microsoft rejects the request (an IP or VPN check, for example) the program switches to the UUP source automatically, starts the download with the same choices and puts UUP first in later searches. For UUP the build comes from the Windows Build Tracking data; if the list is empty, press Update Now there."),
        ],
        "links": [L_BUILD_TRACKER, L_ERROR_CODE],
    },
    {
        "key": "Windows Sürüm Takibi",
        "icon": "shield",
        "title": ("Windows Sürüm Takibi", "Windows Build Tracking"),
        "what": (
            "Yeni yayımlanan Windows build'lerini (GA, önizleme ve Insider) tek listede toplar. Bilgisayarınızın build'ini en yeni yayınla karşılaştırarak geride kalıp kalmadığınızı söyler ve Microsoft'un duyurduğu bilinen sorunları gösterir.\n\n"
            "Bir güncellemeyi kurmadan önce \"bunda sorun var mı?\" diye bakmak ya da Insider tarafında neler çıktığını izlemek için en uygun yer burasıdır.",
            "It collects newly released Windows builds (GA, preview and Insider) in a single list. It compares your PC's build with the latest release to tell you whether you are behind, and shows the known issues Microsoft has announced.\n\n"
            "It is the best place to check \"is there a problem with this one?\" before installing an update, or to follow what is landing on the Insider side.",
        ),
        "steps": [
            ("Şimdi Güncelle ile listeyi yenileyin. Yeni gelen kayıtlar bir rozetle işaretlenir, ilk bakışta fark edersiniz.",
             "Press Update Now to refresh the list. Newly arrived records carry a badge, so you spot them at a glance."),
            ("Filtrelerden mimariyi (x64 ya da ARM64) ve kanalı (GA, Önizleme, Insider) seçerek listeyi kendi bilgisayarınıza göre daraltın. Liste ve Kart görünümü arasında istediğiniz gibi geçebilirsiniz.",
             "Use Filters to narrow the list to your own PC by picking the architecture (x64 or ARM64) and channel (GA, Preview, Insider). You can switch between List and Card view as you like."),
            ("Bir kayda tıkladığınızda Microsoft kaynağındaki bilinen sorunlar ve ilgili makaleler açılır.",
             "Click a record to open the known issues and related articles from the Microsoft source."),
            ("İki ya da üç build seçip Build Değişikliklerini Karşılaştır'a basarsanız aralarındaki farkları yan yana görürsünüz.",
             "Pick two or three builds and press Compare Build Changes to see the differences side by side."),
        ],
        "notes": [
            ("Veriler sitenin yayımladığı listeden alınır. İnternet yoksa en son kaydedilen veriler gösterilir.",
             "Data comes from the list the site publishes. Without internet the last saved data is shown."),
            ("Insider ve Canary build'leri kararsız olabilir; ana bilgisayarınıza kurmadan önce iki kez düşünün.",
             "Insider and Canary builds can be unstable; think twice before putting them on your main PC."),
        ],
        "links": [L_BUILD_TRACKER, L_VERSION_QUERY, L_INSIDER],
    },
    {
        "key": "Güncelleme Geçmişi",
        "icon": "history",
        "title": ("Güncelleme Geçmişi", "Update History"),
        "what": (
            "Daha önce yayımlanmış Windows güncellemelerini tarihe ve sürüme göre gezmenizi sağlar. Bir sorunun hangi güncellemeyle başladığını ya da belirli bir ayda neler çıktığını öğrenmek istediğinizde işe yarar.\n\n"
            "Sayfanın ikinci bir işi de var: programın kendi kontrollerinde bulduğu yeni kayıtların günlüğünü tutar.",
            "It lets you browse previously released Windows updates by date and version. It helps when you want to find out which update a problem started with, or what came out in a particular month.\n\n"
            "The page has a second job too: it keeps a log of the new records the program found during its own checks.",
        ),
        "steps": [
            ("Üstteki kartlar seçili dönemdeki yayınların özetini verir. Aradığınız build ya da KB numarasını arama kutusuna yazarak listeyi süzebilirsiniz.",
             "The cards at the top summarize the releases in the selected period. Type the build or KB number you are after in the search box to filter the list."),
            ("Liste ve Kart görünümleri arasında geçebilirsiniz. Aylık Yayın Sayısı grafiği, son 12 ayı kanallara göre ayırarak gösterir.",
             "You can switch between List and Card views. The Monthly Releases chart splits the last 12 months by channel."),
            ("Kontrol Geçmişi sekmesinde programın canlı kontrollerinde yakaladığı yeni kayıtları görürsünüz.",
             "The Check History tab shows the new records the program caught during its live checks."),
        ],
        "notes": [],
        "links": [L_BUILD_TRACKER],
    },
    {
        "key": "Yüklü Güncellemeler",
        "icon": "doc",
        "title": ("Yüklü Güncellemeler", "Installed Updates"),
        "what": (
            "Bilgisayarınızda kurulu güncellemeleri KB numaralarıyla listeler. Başarısız olanları ve eksik görünenleri tarar, gerekirse bir güncellemeyi kaldırmanıza yardımcı olur.\n\n"
            "Bir güncellemeden sonra bir şeyler bozulduysa ilk bakacağınız yer burasıdır.",
            "It lists the updates installed on your PC with their KB numbers. It scans for failed and missing ones and can help you uninstall an update if needed.\n\n"
            "If something broke after an update, this is the first place to look.",
        ),
        "steps": [
            ("Yenile ile listeyi alın. KB numarası, açıklama ya da tarih yazarak aradığınızı bulabilirsiniz.",
             "Press Refresh to load the list. Type a KB number, description or date to find what you are looking for."),
            ("Bir güncellemeyi seçtiğinizde ayrıntıları ve kaldırılıp kaldırılamayacağı sağda görünür.",
             "Select an update and its details, along with whether it can be uninstalled, appear on the right."),
            ("Başarısız Güncellemeleri Tara ve Eksik KB'leri Kontrol Et, sorunlu ya da atlanmış güncellemeleri sizin yerinize bulur.",
             "Scan Failed Updates and Check Missing KBs find problematic or skipped updates for you."),
            ("Güncellemeyi Kaldır'a bastığınızda program önce bir geri yükleme noktası oluşturur. Kaldırmanın ardından bilgisayarı yeniden başlatmanız gerekebilir.",
             "When you press Uninstall Update the program first creates a restore point. You may need to restart the PC after the removal."),
        ],
        "notes": [
            ("Bu sayfa yalnızca Windows'ta çalışır ve yönetici izni isteyebilir.",
             "This page works on Windows only and may ask for administrator rights."),
        ],
        "links": [L_ERROR_CODE, L_BACKUP],
    },
    {
        "key": "Favorilerim",
        "icon": "star-fill",
        "title": ("Favorilerim", "My Favorites"),
        "what": (
            "Önemli bulup sakladığınız güncelleme ve build kayıtları burada toplanır. Aynı KB'yi ya da build'i her seferinde yeniden aramak zorunda kalmazsınız.",
            "The update and build records you saved because they matter to you are collected here, so you do not have to search for the same KB or build again every time.",
        ),
        "steps": [
            ("Kaydı eklemek için Güncelleme Merkezi'nde ya da Sürüm Takibi'nde Favorilere Ekle'ye basın.",
             "To add a record, press Add to Favorites in Update Center or Build Tracking."),
            ("Burada KB, build, sürüm ya da başlıkla arama yapabilir, Liste ve Kart görünümü arasında geçebilirsiniz.",
             "Here you can search by KB, build, version or title and switch between List and Card view."),
            ("Bir kayıt seçtiğinizde tüm bilgileri ve Microsoft kaynak bağlantısı sağ panelde açılır.",
             "Select a record and all its details, plus the Microsoft source link, open in the right panel."),
        ],
        "notes": [],
        "links": [],
    },
    {
        "key": "Windows 11 Uyumluluğu",
        "icon": "monitor",
        "title": ("Windows 11 Uyumluluğu", "Windows 11 Compatibility"),
        "what": (
            "Bilgisayarınızın seçtiğiniz bir Windows 11 güncellemesine uygun olup olmadığını bir kontrol listesiyle denetler. Yükseltmeye başlayıp yarı yolda takılmak yerine, engelleri önceden görmenizi sağlar.",
            "It checks with a checklist whether your PC is suitable for the Windows 11 update you choose. Instead of starting an upgrade and getting stuck halfway, you see the obstacles beforehand.",
        ),
        "steps": [
            ("Hedef güncellemeyi seçin; kontroller kendiliğinden çalışır.",
             "Choose the target update; the checks run by themselves."),
            ("Uyumluluk Özeti kaç kontrolün geçtiğini gösterir. Önerilen adımlar bölümü ise eksikleri gidermek için ne yapmanız gerektiğini sıralar.",
             "The Compatibility Summary shows how many checks passed. The Recommended steps section lists what to do to fix whatever is missing."),
            ("Sonucu saklamak ya da başkasına göstermek isterseniz Raporu Dışa Aktar'ı kullanın.",
             "To keep the result or show it to someone, use Export Report."),
        ],
        "notes": [
            ("TPM 2.0, Secure Boot ve RAM gibi gereksinimler özellikle yeni kurulumlarda ve bazı sürüm geçişlerinde sorun çıkarabilir. Çoğu zaman çözümü aşağıdaki yazılarda bulabilirsiniz.",
             "Requirements such as TPM 2.0, Secure Boot and RAM can cause trouble, especially on fresh installs and some version upgrades. The articles below usually have the fix."),
        ],
        "links": [L_SECURE_BOOT, L_SECURE_BOOT_UPD, L_RUFUS_BYPASS],
    },
    {
        "key": "UUP ISO Oluşturucu",
        "icon": "cloud",
        "title": ("UUP ISO Oluşturucu", "UUP ISO Builder"),
        "what": (
            "Seçtiğiniz bir Windows build'i için Microsoft'un UUP kaynaklarındaki ISO seçeneklerini bulur ve ISO'yu bilgisayarınızda kendisi hazırlar. Normal indirme sayfalarında bulunmayan bir build'e ihtiyacınız olduğunda, örneğin yeni çıkmış bir önizleme sürümü için, bu yol işe yarar.\n\n"
            "Önce paketler indirilir, sonra ISO otomatik oluşturulur; siz yalnızca build'i, dili ve sürümü seçersiniz.",
            "It finds the ISO options for the Windows build you choose in Microsoft's UUP sources and builds the ISO on your PC for you. When you need a build that is not on the regular download pages, such as a freshly released preview, this is the way to get it.\n\n"
            "The packages are downloaded first and the ISO is built automatically; all you do is pick the build, language and edition.",
        ),
        "steps": [
            ("Build Seç ile bir build belirleyin; seçiminiz Seçili Build alanında görünür.",
             "Choose a build with Select Build; your choice appears under Selected Build."),
            ("UUP / ISO Seçeneklerini Bul'a basın ve gelen sonuçlardan dili, sürümü (edition) ve mimariyi seçin.",
             "Press Find UUP / ISO Options and pick the language, edition and architecture from the results."),
            ("İşlem İndirme Yöneticisi'nde ilerler: paketler iner, ardından ISO oluşturulur. Bu sırada programı kapatmayın.",
             "The job runs in the Download Manager: the packages come down, then the ISO is built. Do not close the program meanwhile."),
            ("İş bittiğinde ISO, ISO Merkezi'nde listelenir.",
             "When the job finishes the ISO is listed in the ISO Center."),
        ],
        "notes": [
            ("İndirme ve ISO oluşturma için yeterli boş disk alanı bırakın; çoğu zaman 20 GB'ın üzeri gerekir.",
             "Leave enough free disk space for the download and the ISO build; it often takes more than 20 GB."),
        ],
        "links": [L_UUP, L_ISO_DL, L_ISO_25H2],
    },
    {
        "key": "İndirme Yöneticisi",
        "icon": "download-tray",
        "title": ("İndirme Yöneticisi", "Download Manager"),
        "what": (
            "Microsoft paket indirmelerini ve ISO oluşturma işlerini tek bir kuyrukta toplar. Büyük bir indirmenin nerede olduğunu, ne kadar sürede biteceğini ve bir sorun çıkıp çıkmadığını buradan görürsünüz.",
            "It gathers Microsoft package downloads and ISO building jobs in a single queue. This is where you see how far a big download has got, how long it will take and whether something went wrong.",
        ),
        "steps": [
            ("Kuyruktaki her işin durumu, hızı ve kalan süresi listede görünür.",
             "Each job in the queue shows its status, speed and remaining time."),
            ("Seçili iş için Duraklat, Devam Ettir, İptal Et ve Yeniden Dene düğmelerini kullanın. Hepsini birden yönetmek isterseniz Toplu İşlemler var.",
             "For the selected job use Pause, Resume, Cancel and Retry. To handle them all at once there is Bulk actions."),
            ("UUP ile ISO hazırlıyorsanız tablonun altındaki ISO Oluşturma bölümü her iş için durumu söyler: dosyalar iniyor, bazıları inemedi, ISO oluşturuluyor ya da hazır. Bazı dosyalar inmezse Başarısızları Yeniden Dene düğmesi çıkar; ISO için tüm dosyaların inmesi gerekir.",
             "If you are preparing an ISO with UUP, the ISO Creation section under the table tells you the state of each job: files downloading, some failed, ISO being built or ready. If some files fail, a Retry Failed button appears; the ISO needs every file."),
            ("İndirme bitince ISO varsayılan olarak kendiliğinden oluşturulur. Bunu istemezseniz Ayarlar'daki UUP / ISO bölümünden otomatik oluşturmayı kapatın; o zaman indirme bitince ISO'yu Şimdi Oluştur düğmesi etkinleşir ve ISO'yu siz başlatırsınız.",
             "By default the ISO is built automatically once the download finishes. If you do not want that, turn off automatic creation in the UUP / ISO section of Settings; then the Create ISO Now button becomes active when the download ends and you start the ISO yourself."),
            ("ISO işi için çalışma klasörünü Çalışma Konumu Seç ile belirleyebilirsiniz. İş bitince ISO Klasörünü Aç sizi doğrudan dosyaya götürür.",
             "For an ISO job you can set the working folder with Choose Working Folder. When it is done, Open ISO Folder takes you straight to the file."),
            ("Hız sınırını ve gece zamanlamasını Ayarlar > İndirme bölümünden değiştirirsiniz.",
             "The speed limit and night schedule are changed in Settings > Download."),
        ],
        "notes": [],
        "links": [L_ISO_BLOCKED],
    },
    {
        "key": "ISO Merkezi",
        "icon": "boxes",
        "title": ("ISO Merkezi", "ISO Center"),
        "what": (
            "Programın oluşturduğu ve bilgisayarınızda zaten bulunan Windows ISO dosyalarını tek listede toplar. Hangi dosyanın hangi build, dil ve sürüme ait olduğunu açmadan görür; doğrulama, bağlama ve USB'ye gönderme işlerini aynı yerden yaparsınız.",
            "It collects the Windows ISO files the program created and those already on your PC in one list. You see which file belongs to which build, language and edition without opening it, and you verify, mount and send to USB from the same place.",
        ),
        "steps": [
            ("Sayfanın üstündeki indirme kutusundan ISO'yu doğrudan indirebilirsiniz: kaynağı (Otomatik, yalnızca Microsoft ya da yalnızca UUP), mimariyi ve dili seçip İndir'e basın. Güncelleme Merkezi'nde bir sürüm adı aratıp Microsoft'tan İndir'e basarsanız seçenekler burada hazır gelir.",
             "From the download box at the top of the page you can download an ISO directly: pick the source (Automatic, Microsoft only or UUP only), the architecture and the language, then press Download. If you search for a version name in Update Center and press Download from Microsoft, the options arrive here already filled in."),
            ("Sayfa ilk açıldığında bilinen klasörler taranır. ISO'larınız başka bir yerdeyse ISO Klasörü Ekle'yi, listeyi tazelemek için Yeniden Tara'yı kullanın.",
             "Known folders are scanned when the page first opens. If your ISOs live elsewhere use Add ISO Folder, and use Rescan to refresh the list."),
            ("Bir ISO seçtiğinizde build, mimari, dil, sürüm ve boyutu sağda görünür. Üstteki süzgeçlerle listeyi daraltabilirsiniz.",
             "Select an ISO and its build, architecture, language, edition and size appear on the right. The filters above narrow the list."),
            ("SHA-256 Doğrula dosyanın özetini arka planda hesaplar. Çıkan değeri indirdiğiniz kaynaktaki değerle karşılaştırın; aynıysa dosya bozulmamış demektir.",
             "Verify SHA-256 calculates the file's hash in the background. Compare the result with the value at the place you downloaded from; if they match, the file is intact."),
            ("USB Hazırlamaya Gönder, seçili ISO'yu doğrudan USB Kurulum Aracı'na aktarır.",
             "Send to USB Preparation passes the selected ISO straight to the USB Install Tool."),
        ],
        "notes": [
            ("ISO'yu Sil, dosyayı diskten kalıcı olarak kaldırır ve önce onay ister.",
             "Delete ISO permanently removes the file from disk and asks for confirmation first."),
            ("ISO'yu Bağla yalnızca Windows'ta çalışır.",
             "Mount ISO works on Windows only."),
        ],
        "links": [L_SHA, L_ISO_DL],
    },
    {
        "key": "USB Kurulum Aracı",
        "icon": "usb",
        "title": ("USB Kurulum Aracı", "USB Install Tool"),
        "what": (
            "Bir Windows ISO'sundan önyüklenebilir USB kurulum medyası hazırlar. İsterseniz kurulumun nasıl ilerleyeceğini de baştan ayarlayabilirsiniz: yerel hesap, bilgisayar adı, gizlilik sayfalarını atlama gibi.\n\n"
            "Bilgisayarı sıfırdan kuracaksanız ya da desteklenmeyen bir cihaza Windows 11 yüklemek istiyorsanız burada vakit kazanırsınız.",
            "It prepares bootable USB install media from a Windows ISO. If you like, you can also decide in advance how the setup will go: a local account, a computer name, skipping the privacy pages and so on.\n\n"
            "If you are about to reinstall a PC, or want Windows 11 on a device it does not officially support, this saves you time.",
        ),
        "steps": [
            ("ISO dosyasını seçin (ya da ISO Merkezi'nden gönderin) ve doğru USB sürücüsünü işaretleyin.",
             "Select the ISO file (or send it from the ISO Center) and pick the correct USB drive."),
            ("Bölümleme ve dosya sistemi ayarlarına göz atın. Çoğu bilgisayar için varsayılanlar uygundur, değiştirmeniz gerekmez.",
             "Take a look at the partition scheme and file system. The defaults suit most PCs and you do not need to change them."),
            ("Dilerseniz ISO'nun SHA-256 değerini doğrulatın. Beklenen değeri yapıştırırsanız ve eşleşmezse işlem, USB'ye hiç dokunmadan durur.",
             "If you wish, have the ISO's SHA-256 verified. If you paste the expected value and it does not match, the job stops before touching the USB."),
            ("Kurulum Özelleştirme bölümünde yerel hesap, bilgisayar adı, gizlilik sayfalarını atlama ve Windows 11 donanım denetimlerini kaldırma seçeneklerini belirleyin.",
             "In Install customization choose a local account, a computer name, skipping the privacy pages and removing the Windows 11 hardware checks."),
            ("Onay penceresindeki özeti okuyup işlemi başlatın. Aşamalar ekranda adım adım izlenir.",
             "Read the summary in the confirmation window and start. The stages are followed on screen one by one."),
        ],
        "notes": [
            ("USB bellekteki TÜM veriler silinir. Başlamadan önce sürücü harfini ve boyutunu bir kez daha kontrol edin.",
             "ALL data on the USB drive is erased. Check the drive letter and size once more before you start."),
            ("Lisans sözleşmesi sayfası sizin yerinize kabul edilmez; onu kurulum sırasında siz onaylarsınız.",
             "The license agreement page is not accepted on your behalf; you accept it yourself during setup."),
            ("Bu özellik yalnızca Windows'ta çalışır.",
             "This feature works on Windows only."),
        ],
        "links": [L_RUFUS_BYPASS, L_UEFI_USB, L_CMD_USB, L_NO_USB, L_SHA],
    },
    {
        "key": "Sürücü Yedekleme",
        "icon": "cpu",
        "title": ("Sürücü Yedekleme", "Driver Backup"),
        "what": (
            "Format atmadan önce üçüncü taraf sürücüleri yedekler; kurulumdan sonra tek tıkla geri yüklemenizi sağlar. Temiz kurulumun en sıkıcı kısmı olan \"ekran kartı, ağ ve ses sürücüleri nereden bulunacak?\" derdini ortadan kaldırır.",
            "It backs up third-party drivers before a reformat and lets you restore them with one click afterwards. It takes away the most tedious part of a clean install: tracking down the graphics, network and audio drivers.",
        ),
        "steps": [
            ("Yenile ile sürücüleri tarayın. Aygıt, sağlayıcı ya da sınıfa göre arama yapabilirsiniz.",
             "Scan the drivers with Refresh. You can search by device, provider or class."),
            ("Yedeklemek istediklerinizi işaretleyin (Tümünü Seç ve Seçimi Kaldır işinizi kolaylaştırır) ve Seçili Sürücüleri Yedekle'ye basın.",
             "Tick the ones you want to back up (Select All and Clear Selection make it easier) and press Back Up Selected Drivers."),
            ("Kurulum USB'sine ekle ile yedeği, hazırladığınız kurulum medyasına koyabilirsiniz; böylece sürücüler kurulumla birlikte yanınızda olur.",
             "With Add to install USB you can put the backup on the install media you prepared, so the drivers travel with the installation."),
            ("Kurulumdan sonra yedek klasörünü seçip Sürücüleri Geri Yükle'ye basın. İsterseniz önce bir geri yükleme noktası oluşturulur.",
             "After installation choose the backup folder and press Restore Drivers. If you like, a restore point is created first."),
        ],
        "notes": [
            ("Yedek yalnızca aynı bilgisayar için uygundur; farklı bir donanıma yüklemek sorun çıkarabilir.",
             "A backup only suits the same PC; installing it on different hardware can cause trouble."),
            ("Bu özellik yalnızca Windows'ta çalışır ve yönetici izni ister.",
             "This feature works on Windows only and needs administrator rights."),
        ],
        "links": [L_BLOCK_DRIVER, L_BACKUP],
    },
    {
        "key": "Ayarlar",
        "icon": "gear",
        "title": ("Ayarlar", "Settings"),
        "what": (
            "Dil, tema, açılış davranışı, indirme klasörü ve hız sınırı gibi program ayarlarını buradan değiştirirsiniz. Çoğu kişi için varsayılanlar yeterlidir; yine de indirmeleri başka bir diske toplamak ya da gece indirmek gibi ihtiyaçlarınız olursa buraya uğrayın.",
            "You change program settings here, such as language, theme, startup behavior, download folder and speed limit. The defaults are enough for most people, but visit this page if you want to gather downloads on another disk or download at night.",
        ),
        "steps": [
            ("Genel bölümünde dili (Otomatik, Türkçe ya da English), temayı, son açık sayfanın hatırlanmasını ve açılıştaki karşılama rehberini ayarlarsınız.",
             "In General you set the language (Auto, Türkçe or English), the theme, whether the last page is remembered and the welcome guide at startup."),
            ("İndirme bölümü indirme klasörünü, hız sınırını ve gece zamanlamasını; UUP / ISO bölümü ISO oluşturma tercihlerini; Windows Sürüm Takibi bölümü kontrol sıklığını ve bildirimleri kapsar. Gelişmiş bölümünde log ve veri klasörleri ile ayarları sıfırlama seçeneği bulunur.",
             "Download covers the download folder, speed limit and night schedule; UUP / ISO the ISO building preferences; Windows Build Tracking the check frequency and notifications. Advanced holds the log and data folders and the option to reset settings."),
            ("Bitirince Değişiklikleri Kaydet'e basmayı unutmayın. Dil değiştirdiyseniz programın yeniden başlatılması istenebilir.",
             "When you are done, do not forget to press Save Changes. If you changed the language, you may be asked to restart the program."),
        ],
        "notes": [],
        "links": [],
    },
    {
        "key": "Hakkında",
        "icon": "info-fill",
        "title": ("Hakkında", "About"),
        "what": (
            "Programın sürümünü, bu sürümde nelerin değiştiğini ve güncelleme durumunu gösterir. Geri bildirim göndermek ya da iletişime geçmek için gereken bağlantılar da burada.",
            "It shows the program's version, what changed in this release and the update status. The links you need to send feedback or get in touch are here too.",
        ),
        "steps": [
            ("Sürüm notlarından bu sürümle gelen yenilikleri okuyabilirsiniz.",
             "The release notes tell you what this version brings."),
            ("Yeni bir sürüm yayımlandığında menüde \"Yeni sürüm mevcut\" düğmesi belirir.",
             "When a new version is published, a \"New version available\" button appears in the menu."),
        ],
        "notes": [],
        "links": [("bunyaminkaya.com", "bunyaminkaya.com", _u("")), ("İletişim", "Contact", _u("iletisim/"))],
    },
]

KEYS = [s["key"] for s in SECTIONS]


def section_for(page_name: str) -> str:
    """Bir sayfa adına karşılık gelen yardım bölümü (yoksa Başlarken)."""
    return page_name if page_name in KEYS else "Başlarken"
