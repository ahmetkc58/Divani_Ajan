# Organizasyon şemasının dijitalleştirilmesi

## Kaynak ve aktarım

`ustyonetimorganizasyonsema.jpg` görseli okunarak aynı yapı
`ustyonetimorganizasyonsema.md` dosyasına aktarıldı. Markdown aktarımı üst
yönetim, merkez teşkilatı, doğrudan bağlı birimler, idari/destek birimleri,
taşra teşkilatı ve diğer bağlı taşra birimlerini ayrı bölümlerde korur.

Kaynak görseldeki birim kısaltmaları ile vekâlet/görevlendirme işaretleri
transkripsiyon belgesinde korunmuştur. Bu belge insan tarafından karşılaştırma
ve kaynak izleme amacı taşır; doğrudan runtime verisi değildir. Gerçek kamu
personeli adları içerdiği için yerel çalışma belgesi olarak tutulur ve yarışma
teslim commit'ine eklenmez.

## Çalışma zamanı kataloğu

Yönlendirme için ayrı dosya kullanılır:

`data/organization/kgm_units_2026-07-16.json`

Katalog özellikleri:

- Şema sürümü: `2026-07-16`
- Toplam kayıt: 102
- Dış evrak adayı olarak kullanılabilen kayıt: 88
- Merkez daireleri, şubeler, doğrudan bağlı birimler ve taşra hedefleri
- Kararlı `unit_id` değerleri ve `parent_id` ilişkileri
- Personel/yönetici adı içermez
- Aynı kimlik veya tanımsız üst birim olduğunda yükleme reddedilir
- Hiyerarşi döngüsü olduğunda yükleme reddedilir

## Neden iki ayrı dosya var?

`ustyonetimorganizasyonsema.md` kaynak görselin insan tarafından okunabilir tam
aktarımıdır ve yönetici adlarını da kaynak sadakati için içerir. Runtime JSON'u
ise veri minimizasyonu uygular; yalnız yönlendirme için gereken birim yapısını
ve kurgusal görev profillerini taşır.

## Profil statüleri

- `synthetic_draft`: Görev/anahtar profili sistem testi için hazırlanmıştır;
  kurumsal uzman onayı bekler.
- `chart_only`: Şemadan yalnız birim adı veya merkez konumu bilinmektedir;
  yönlendirme insan incelemesini zorunlu kılar.

## Coğrafi sınır

Şema bölge müdürlükleri için merkez şehirlerini verir fakat il bazlı tam yetki
alanını vermez. Bu nedenle örneğin “İstanbul” bir konum sinyali olabilir, ancak
şehir tek başına kesin kurumsal yetki kanıtı sayılmaz. Resmî il-bölge matrisi
uzman onayıyla yeni katalog sürümüne eklenmelidir.

## Kişisel veri notu

Yönetici adları runtime kataloğuna, LLM prompt'una veya yönlendirme sonucuna
aktarılmaz. Yarışma testlerinde yalnız kurgusal kişi ve kurum adları kullanılır.
