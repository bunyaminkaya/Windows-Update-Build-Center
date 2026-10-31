from __future__ import annotations
import hashlib, json, os, platform, re, subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

@dataclass
class InstalledUpdate:
    kb: str
    description: str
    installed_on: str
    hotfix_id: str
    source: str = "Windows"
    removable: bool = False

@dataclass
class SystemSnapshot:
    windows_version: str = "—"; build: str = "—"; architecture: str = "—"
    tpm: str = "—"; secure_boot: str = "—"; disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0; cpu: str = "—"; ram_gb: float = 0.0
    channel: str = "—"; edition: str = "—"; language: str = "—"

class WindowsUpdateService:
    @staticmethod
    def _ps(script: str, timeout: int = 30) -> tuple[bool,str]:
        if os.name != "nt": return False, "Bu özellik yalnızca Windows üzerinde kullanılabilir."
        try:
            p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-Command",script],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            return p.returncode==0,((p.stdout or "").strip() or (p.stderr or "").strip())
        except Exception as e:return False,str(e)

    @classmethod
    def snapshot(cls)->SystemSnapshot:
        if os.name!="nt":
            m=(platform.machine() or "").lower(); a="ARM64" if "arm64" in m or "aarch64" in m else ("x64" if m in ("x86_64","amd64","x64") else ("x86" if "86" in m else m or "—"))
            return SystemSnapshot(architecture=a,cpu=platform.processor() or "—")
        ok,text=cls._ps(r'''
$os=Get-CimInstance Win32_OperatingSystem;$cs=Get-CimInstance Win32_ComputerSystem;$cpu=Get-CimInstance Win32_Processor|select -First 1;$cv=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion';$a=$env:PROCESSOR_ARCHITECTURE;if($env:PROCESSOR_ARCHITEW6432){$a=$env:PROCESSOR_ARCHITEW6432};$t=Get-Tpm -ErrorAction SilentlyContinue;$tp='Yok';if($t -and $t.TpmPresent){$tp=if($t.SpecVersion){$t.SpecVersion+(if($t.TpmReady){' / Hazır'}else{' / Hazır değil'})}else{if($t.TpmReady){'2.0 / Hazır'}else{'2.0 / Hazır değil'}}};$sb='Bilinmiyor';try{$sb=if(Confirm-SecureBootUEFI -ErrorAction Stop){'Etkin'}else{'Devre Dışı'}}catch{$sb='Desteklenmiyor/Bilinmiyor'};$v=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'";[pscustomobject]@{Version=$cv.DisplayVersion;Build=("{0}.{1}"-f $cv.CurrentBuildNumber,$cv.UBR);Edition=$os.Caption;Arch=$a;TPM=$tp;SecureBoot=$sb;FreeGB=[math]::Round($v.FreeSpace/1GB,2);TotalGB=[math]::Round($v.Size/1GB,2);CPU=$cpu.Name;RAMGB=[math]::Round($cs.TotalPhysicalMemory/1GB,2);Language=(Get-Culture).Name}|ConvertTo-Json -Compress
''')
        s=SystemSnapshot()
        if ok:
            try:
                d=json.loads(text);a=str(d.get("Arch","")).upper();a="ARM64" if "ARM64" in a else ("x64" if "AMD64" in a or "X86_64" in a else ("x86" if "86" in a else a));s=SystemSnapshot(str(d.get("Version") or "—"),str(d.get("Build") or "—"),a or "—",str(d.get("TPM") or "—"),str(d.get("SecureBoot") or "—"),float(d.get("FreeGB") or 0),float(d.get("TotalGB") or 0),str(d.get("CPU") or "—"),float(d.get("RAMGB") or 0),"—",str(d.get("Edition") or "—"),str(d.get("Language") or "—"))
            except Exception:pass
        ok,ch=cls._ps("$p=@('HKLM:\\SOFTWARE\\Microsoft\\WindowsSelfHost\\Applicability','HKLM:\\SOFTWARE\\Microsoft\\WindowsSelfHost\\UI\\Selection');$x=@();foreach($i in $p){if(Test-Path $i){$v=Get-ItemProperty $i;$x+=@($v.BranchName,$v.ContentType,$v.RingName,$v.UIBranch)}};($x|?{$_}|select -First 4)-join ' / '")
        s.channel=ch if ok and ch else "Retail / Genel (Insider kaydı yok)";return s

    @classmethod
    def installed_updates(cls)->list[InstalledUpdate]:
        if os.name!="nt":return []
        ok,text=cls._ps(r'''Get-HotFix|sort InstalledOn -Descending|%{[pscustomobject]@{HotFixID=$_.HotFixID;Description=$_.Description;InstalledOn=if($_.InstalledOn){$_.InstalledOn.ToString('yyyy-MM-dd')}else{''}}}|ConvertTo-Json -Compress''')
        if not ok or not text:return []
        try:raw=json.loads(text);raw=[raw] if isinstance(raw,dict) else raw
        except Exception:return []
        return [InstalledUpdate(str(d.get("HotFixID")),str(d.get("Description") or "—"),str(d.get("InstalledOn") or "—"),str(d.get("HotFixID")),removable=cls._kb_removable(str(d.get("HotFixID")))) for d in raw if d.get("HotFixID")]

    @classmethod
    def _kb_removable(cls,kb):
        n=re.sub(r"\D","",kb)
        if not n:return False
        script=r'''$u=Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue|%{Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue}|?{$_.UninstallString -match 'KBNUM' -or $_.DisplayName -match 'KBKB'};if($u){'YES'}else{'NO'}'''.replace("KBNUM",n).replace("KBKB","KB"+n)
        ok,text=cls._ps(script);return ok and text.strip()=="YES"

    @classmethod
    def failed_updates(cls):
        if os.name!="nt":return []
        ok,text=cls._ps(r'''Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WindowsUpdateClient';StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue|?{$_.LevelDisplayName -in @('Error','Warning')}|select -First 50 -Expand Message''',40)
        return [x.strip() for x in re.split(r"\r?\n\r?\n",text) if x.strip()] if ok and text else []

    @classmethod
    def create_restore_point(cls):
        ok,text=cls._ps(r'''Checkpoint-Computer -Description "Windows Update & Build Center - Güncelleme Öncesi" -RestorePointType MODIFY_SETTINGS''',60);return ok,text or ("Geri yükleme noktası oluşturuldu." if ok else "Geri yükleme noktası oluşturulamadı.")

    @staticmethod
    def _official_url(url):
        try:
            host=(urlparse(url).hostname or "").lower();return urlparse(url).scheme=="https" and (host.endswith("microsoft.com") or host.endswith("windowsupdate.com") or host.endswith("mp.microsoft.com"))
        except Exception:return False

    @classmethod
    def pre_download_check(cls,package,snapshot):
        if not cls._official_url(getattr(package,"direct_url","")):return False
        arch=str(getattr(package,"architecture","")).upper()
        if arch not in {"","BELİRSİZ","—"} and snapshot.architecture.upper()!=arch:return False
        text=(getattr(package,"filename","")+" "+getattr(package,"update_title","")+" "+getattr(package,"classification","")).lower()
        return not any(x in text for x in ("dynamic update","safe os","setup dynamic"))

    @classmethod
    def verify_file(cls,path,expected_sha256=""):
        p=Path(path);r={"path":str(p),"exists":p.exists(),"size":p.stat().st_size if p.exists() else 0,"sha256":"","signature":"Kontrol edilmedi","signature_status":"Unknown","valid":False,"file_type":p.suffix.lower().lstrip("."),"message":"","expected_sha256":"","sha256_match":True}
        if not p.exists():r["message"]="Dosya bulunamadı.";return r
        h=hashlib.sha256()
        try:
            with p.open("rb") as f:
                for c in iter(lambda:f.read(1024*1024),b""):h.update(c)
            r["sha256"]=h.hexdigest().upper()
            expected=re.sub(r"\s+","",str(expected_sha256 or "")).upper()
            r["expected_sha256"]=expected
            r["sha256_match"]=(not expected) or (r["sha256"]==expected)
            if expected and not r["sha256_match"]:
                r["valid"]=False
                r["message"]="SHA-256 beklenen değerle eşleşmiyor. Dosya bozuk/değiştirilmiş olabilir."
        except Exception as e:r["message"]=str(e);return r
        safe=str(p).replace("'","''");ok,text=cls._ps("$s=Get-AuthenticodeSignature -LiteralPath '"+safe+"';[pscustomobject]@{Status=$s.Status;Subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''};Thumbprint=if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{''}}|ConvertTo-Json -Compress")
        if ok:
            try:
                d=json.loads(text);status=str(d.get("Status") or "Unknown");r["signature_status"]=status;r["signature"]=f'{status} • {d.get("Subject") or "İmzacı bilgisi yok"}';r["signer_subject"]=str(d.get("Subject") or "")
            except Exception:pass
        ext=p.suffix.lower();status=str(r["signature_status"]).lower();hard_fail=status in {"invalid","hashmismatch","nottrusted","unknownerror"}
        r["valid"]=((status=="valid" and "microsoft" in str(r.get("signer_subject","")).lower()) if ext==".exe" else not hard_fail) and r.get("sha256_match",True)
        r["message"]="SHA-256 hesaplandı. "+("İmza geçerli." if status=="valid" else "MSU/CAB için Authenticode bazı Windows sürümlerinde doğrudan raporlanmaz; açık imza hatası yoksa dosya bütünlüğü geçerli kabul edildi." if ext in {".msu",".cab"} else "İmza doğrulaması başarısız.")
        return r

    @staticmethod
    def format_verification(r):
        return f"Dosya: {r.get('path')}\nBoyut: {r.get('size',0):,} bayt\nTür: {r.get('file_type','—').upper()}\nSHA-256: {r.get('sha256') or '—'}\nDijital imza: {r.get('signature') or '—'}\nSonuç: {'GÜVENLİ / KURULUMA UYGUN' if r.get('valid') else 'DOĞRULAMA BAŞARISIZ — KURULUMU ENGELLE'}\n\n{r.get('message','')}"

    @classmethod
    def install_package(cls,path,silent=True):
        p=Path(path)
        if not p.exists():return False,"Paket bulunamadı."
        if os.name!="nt":return False,"Kurulum yalnızca Windows üzerinde desteklenir."
        verification=cls.verify_file(p)
        if not verification.get("valid"):return False,"Güvenlik doğrulaması başarısız. Kurulum engellendi.\n\n"+cls.format_verification(verification)
        e=p.suffix.lower()
        if e==".msu":args=["wusa.exe",str(p),"/quiet" if silent else "","/norestart"];args=[x for x in args if x]
        elif e==".cab":args=["dism.exe","/Online","/Add-Package","/PackagePath:"+str(p),"/NoRestart"]
        elif e==".exe":args=[str(p),"/quiet","/norestart"] if silent else [str(p)]
        else:return False,"Desteklenmeyen paket türü: "+e
        try:
            q=subprocess.run(args,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=3600,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            msg=(q.stdout or q.stderr or "").strip()
            code=q.returncode & 0xffffffff
            errors={0x800F081F:"Kaynak dosyaları bulunamadı (DISM/Windows Update kaynağı eksik).",0x80073712:"Windows bileşen deposu bozuk/eksik olabilir.",0x80073701:"Gerekli bileşen veya paket bulunamadı.",0x80240017:"Güncelleme bu sistem için uygulanabilir değil.",0x800F0922:"Kurulum veya ayrılmış sistem bölümü/bağlantı sorunu olabilir."}
            reboot=code in (3010,1641);success=code==0 or reboot;detail=("\nYeniden başlatma gerekiyor." if reboot else "");mapped=errors.get(code,"")
            return (True,(msg or "Kurulum komutu tamamlandı.")+detail) if success else (False,f"Çıkış kodu: 0x{code:08X}\n{mapped}\n{msg}")
        except Exception as e:
            return False,str(e)

    @classmethod
    def uninstall_update(cls, kb):
        """Gerçek KB kaldırma işlemi. Geri yükleme noktası çağrısı UI tarafından önce yapılır."""
        n=re.sub(r"\D", "", str(kb))
        if not n:
            return False, "Geçerli bir KB numarası bulunamadı."
        if os.name != "nt":
            return False, "KB kaldırma işlemi yalnızca Windows üzerinde desteklenir."
        try:
            q=subprocess.run(
                ["wusa.exe", f"/uninstall", f"/kb:{n}", "/quiet", "/norestart"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            code=q.returncode & 0xffffffff
            msg=(q.stdout or q.stderr or "").strip()
            errors={
                0x800F0825: "Güncelleme kaldırma işlemi geri alınamaz veya paket kaldırmaya izin vermiyor.",
                0x800F0900: "Windows bileşen işlemi başarısız oldu; DISM/servis durumunu kontrol edin.",
                0x80073712: "Windows bileşen deposu bozuk/eksik olabilir.",
                0x80240020: "İşlem için yeniden başlatma veya etkileşim gerekiyor.",
            }
            reboot=code in (3010, 1641)
            success=code == 0 or reboot
            if success:
                return True, (msg or f"{kb} kaldırma komutu tamamlandı.") + ("\nYeniden başlatma gerekiyor." if reboot else "")
            return False, f"Çıkış kodu: 0x{code:08X}\n{errors.get(code, 'Windows güncelleme kaldırma işlemi başarısız oldu.')}\n{msg}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def uninstall_command(kb):
        n=re.sub(r"\D","",kb);return f"wusa.exe /uninstall /kb:{n} /quiet /norestart" if n else ""

    @classmethod
    def troubleshoot(cls):
        s=cls.snapshot();checks=[("Windows Update hizmeti",cls._service_state("wuauserv"),"Servisin çalışır veya başlatılabilir olması gerekir."),("BITS hizmeti",cls._service_state("bits"),"Arka plan indirmeleri için kullanılır."),("Disk alanı",f"{s.disk_free_gb:.1f} GB boş","Güncelleme önbelleği için yeterli alan."),("Bekleyen yeniden başlatma","Var" if cls._pending_reboot() else "Yok","Bekleyen reboot güncellemeyi kilitleyebilir."),("DISM",cls._dism_check(),"Bileşen deposu temel sağlık kontrolü."),("SFC",cls._sfc_check(),"Sistem dosyaları doğrulaması."),("Windows Update önbelleği",cls._update_cache_state(),"SoftwareDistribution ve catroot2 dizinlerinin durumu.")];ev=cls.failed_updates();codes=sorted(set(sum([re.findall(r"0x[0-9A-Fa-f]{8}",x) for x in ev],[])));return {"checks":checks,"failed_events":ev,"error_codes":codes,"generated_at":datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
    @classmethod
    def _service_state(cls,n):
        ok,t=cls._ps(f"$s=Get-Service -Name '{n}' -ErrorAction SilentlyContinue;if($s){{'{n}: '+$s.Status}}else{{'Bulunamadı'}}");return t if ok and t else "Bulunamadı"
    @classmethod
    def _pending_reboot(cls):
        ok,t=cls._ps(r'''$p=@('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired');if($p|?{Test-Path $_}){'YES'}else{'NO'}''');return ok and t.strip()=="YES"
    @classmethod
    def _update_cache_state(cls):
        ok,t=cls._ps(r'''$a=Test-Path "$env:windir\SoftwareDistribution\Download";$b=Test-Path "$env:windir\System32\catroot2";"SoftwareDistribution="+$a+"; catroot2="+$b''');return t if ok else "Kontrol edilemedi"
    @classmethod
    def _dism_check(cls):
        ok,t=cls._ps("DISM.exe /Online /Cleanup-Image /CheckHealth",60);return t[-800:] if t else ("Başarılı" if ok else "Başarısız")
    @classmethod
    def _sfc_check(cls):
        ok,t=cls._ps("sfc.exe /verifyonly",180);return t[-800:] if t else ("Başarılı" if ok else "Başarısız")

    @staticmethod
    def _build_tuple(v):
        n=re.findall(r"\d+",str(v));return tuple(int(x) for x in n[:4]) if n else (0,)

    @classmethod
    def compatibility(cls,s,target=None):
        rows=[("Windows sürümü",s.windows_version,"Bilgi","Mevcut Windows sürümü."),("Mevcut build",s.build,"Bilgi","Hedef build ile karşılaştırılır."),("Mimari",s.architecture,"Uygun" if s.architecture in ("x64","ARM64") else "Destek dışı","Paket mimarisi seçimi."),("TPM 2.0",s.tpm,"Uygun" if "2.0" in s.tpm and "Hazır" in s.tpm else "Kontrol gerekli","Windows 11 donanım uygunluğu."),("Secure Boot",s.secure_boot,"Uygun" if s.secure_boot=="Etkin" else "Kontrol gerekli","Windows 11 güvenlik/kurulum koşulu."),("Disk alanı",f"{s.disk_free_gb:.1f} GB boş / {s.disk_total_gb:.1f} GB","Uygun" if s.disk_free_gb>=20 else "Yetersiz / kritik","Güvenli çalışma payı için 20 GB eşik."),("İşlemci",s.cpu,"Bilgi","CPU modeli; destek listesi ayrıca doğrulanmalıdır."),("RAM",f"{s.ram_gb:.1f} GB","Uygun" if s.ram_gb>=4 else "Yetersiz","Temel minimum kontrol."),("Güncelleme kanalı",s.channel,"Bilgi","Retail/Preview/Beta/Dev/Canary bilgisi."),("Dil",s.language,"Bilgi","Paket dil eşleştirmesi."),("Edition",s.edition,"Bilgi","Pro/Home/Enterprise vb. eşleşmesi.")]
        if target:
            tv=getattr(target,"windows_version","");tb=getattr(target,"build_number","")
            if tv:rows.append(("Hedef Windows",tv,"Eşleşiyor" if tv in s.windows_version or s.windows_version in tv else "Kontrol gerekli","Build Tracker hedefi."))
            if tb:
                cur=cls._build_tuple(s.build);want=cls._build_tuple(tb);rows.append(("Hedef build",tb,"Daha yeni" if cur<want else "Aynı veya daha yeni","Mevcut build hedefin altındaysa güncelleme gerekir."))
            ch=getattr(target,"channel","")
            if ch:rows.append(("Hedef kanal",ch,"Bilgi","Kanal değişikliği gerekiyorsa Windows Insider ayarları ayrıca kontrol edilmelidir."))
        return rows

    @classmethod
    def package_filter(cls,packages,s):
        arch=s.architecture.lower();lang=(s.language or "").lower();edition=(s.edition or "").lower();version=(s.windows_version or "").lower();scored=[]
        for p in packages:
            text=(getattr(p,"update_title","")+" "+getattr(p,"filename","")+" "+getattr(p,"product","")+" "+getattr(p,"classification","")).lower();score=0;reasons=[];pa=(getattr(p,"architecture","") or "").lower()
            if pa==arch:score+=60;reasons.append(arch.upper()+" mimari")
            elif pa in ("x86","arm64","x64") and pa!=arch:score-=80;reasons.append("mimari uyumsuz")
            if lang and (lang.replace("_","-") in text or lang.split("-")[0] in text):score+=20;reasons.append("sistem dili eşleşiyor")
            if any(k in text for k in ("dynamic update","safe os","setup dynamic")):score-=100;reasons.append("Dynamic/Safe OS — normal LCU değil")
            if any(k in text for k in ("cumulative update","quality update","security update","cumulative")):score+=25;reasons.append("normal LCU/kalite-güvenlik güncellemesi")
            if "preview" in text and "retail" in (s.channel or "").lower():score-=15;reasons.append("Preview — Retail sistem için geri planda")
            if getattr(p,"file_type","").upper() not in {"MSU","CAB","EXE"}:score-=30
            p.recommendation_score=score;p.recommended=False;p.recommendation_reason=", ".join(reasons) or "Genel eşleşme";scored.append(p)
        scored.sort(key=lambda x:(x.recommendation_score,x.filename.lower()),reverse=True)
        if scored and scored[0].recommendation_score>0:scored[0].recommended=True
        return scored
