# Windows Update & Build Center - UI Stil Standardı

## Modern Mavi Açılır Menü

Kısa kullanım adı: **Modern Mavi Açılır Menü**  
Teknik bileşen adı: **ModernComboBox**

Yeni bir açılır menü eklenirken standart `QComboBox` yerine:

```python
from ui.widgets.modern_combo_box import ModernComboBox

combo = ModernComboBox()
```

kullanılmalıdır.

Bu bileşen programın standart açılır menü tasarımıdır ve bundan sonraki tüm ekranlarda varsayılan kabul edilir.


## Ayarlar Merkezi
Ayarlar ekranında solda kategori navigasyonu, sağda beyaz ayar kartları kullanılır. Seçili kategori programın ana mavi vurgu rengiyle gösterilir. Açılır menüler tüm programda ModernComboBox standardını kullanır.
