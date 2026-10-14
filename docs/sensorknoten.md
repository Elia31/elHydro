# elHydro Sensorknoten

Diese Datei sollte Ihnen dabei helfen, falls Sie selber einen
elHydro-Sensorknoten bauen und mit der Firmware bespielen möchten.

## Welche Bauteile Sie brauchen

### 1x DFRobot FireBeetle 2 ESP32-C6

Beim FireBeetle 2 ESP32-C6 ist es leider so,
dass dieser in vielen Shops oft ausverkauft ist
und daher oft teurer als die 5,90 € UVP ist.

Hier könnten Sie ihn für 7,50 € bestellen: [botland.de](https://botland.de/arduino-kompatible-boards-dfrobot/25402-firebeetle-2-esp32-c6-wifi-bluetooth-zigbee-matter-dfrobot-dfr1075-6959420924509.html)

Zusätzlich hilfreicher Link zum FireBeetle: [wiki.dfrobot.com](https://wiki.dfrobot.com/dfr1075/#tech_specs)

Falls Sie beabsichtigen, den ESP32-C6 sowieso nur per USB mit Strom zu versorgen,
und Ihnen die Energieeffizienz nicht wichtig ist, würden theoretisch auch andere
ESP32-C6-Dev-Boards funktionieren, sofern sie genug GPIO-Pins zum Anschließen aller Komponenten haben.

### 1x Temperatur- und Luftfeuchtesensor-Breakoutboard HTU21D

Den vom System genutzten Temperatur- und Luftfeuchtesensor können Sie entweder auf Amazon oder AliExpress kaufen.
Andere Seiten haben diesen jedoch sicherlich auch im Angebot.

- Amazon; hier bekommen Sie 2 Stück für 8,39 €: [amazon.de](https://www.amazon.de/Hailege-Temperatur-Luftfeuchtigkeit-Breakout-Kompatibel/dp/B07Y83MR4X/)
- AliExpress; hier kostet ein Sensor 1,95 €: [aliexpress.com](https://de.aliexpress.com/item/1005007142978970.html)

### 1x Kapazitiver Bodenfeuchtesensor v2.0

Wie auch schon beim HTU21D können Sie den Bodenfeuchtesensor auf Amazon und AliExpress kaufen.
Im Unterschied zu anderen kapazitiven Bodenfeuchtesensoren (oft als „Kapazitiver Bodenfeuchtesensor v1.2“ vertrieben)
vertragen die als v2.0 verkauften Sensoren 3,3 V. Die v1.2 laufen oft nur mit 5 V.
Der Bodenfeuchtesensor wird in meinem System von einem GPIO-Pin des ESP32 mit Strom versorgt, und die GPIOs liefern 3,3 V.
Daher ist es wichtig, dass der genutzte Bodenfeuchtesensor mit 3,3 V arbeiten kann.

- Amazon; hier bekommen Sie 6 Stück für 8,99 €: [amazon.de](https://www.amazon.de/AYWHP-Bodenfeuchtesensor-Hygrometer-Kapazitive-Feuchtigkeitssensor/dp/B0FPFTS2BF/)
- AliExpress; hier bekommen Sie 1 für 1,45 € oder 3 für 2,09 €: [aliexpress.com](https://de.aliexpress.com/item/1005007353966390.html)

Grundsätzlich können Sie als Bodenfeuchtesensor auch resistive Sensoren verwenden.
Diese finden sich im Netz oft als LM393-Bodensensoren.
Da diese im Einsatz jedoch sehr schnell anfangen zu rosten, würde ich sie nicht empfehlen.
Wenn Sie trotzdem einen LM393-Sensor nutzen, stellen Sie in `firmware/main/config.h`
`USE_LM393_SENSOR` auf `1` und `USE_CAPACITIVE_V2_SENSOR` auf `0`.

Amazon: [amazon.de](https://www.amazon.de/AZDelivery-Bodenfeuchtesensor-Hygrometer-Feuchtigkeit-Arduino/dp/B07V4KXZ35/)

### 1x Tauchpumpe und MOSFET zur Steuerung

Zum Bewässern von Pflanzen nutze ich eine kleine 3–5-V-Tauchpumpe. Da die Pumpe beim Laufen mehr Strom zieht,
als ein Pin des ESP32 liefern kann, nutze ich einen MOSFET zum An- und Ausschalten der Pumpe.
Die Pumpe ist dabei mit ihrer Plus-Leitung direkt an Batterie-Plus angeschlossen,
die Minus-Leitung hängt am Ausgang (Drain) des MOSFETs. Ein MOSFET hat drei Anschlüsse: Gate, Source und Drain.
Gate ist der Anschluss, über den der MOSFET gesteuert wird. Beim hier verwendeten N-Kanal-MOSFET
fließt der Strom der Pumpe von Drain nach Source. Liegt am Gate eine Spannung an, schließt der MOSFET den Stromkreis
zwischen Drain und Source, und Strom kann fließen. Source des MOSFETs ist am GND des Systems angeschlossen, Drain an der
Minus-Leitung der Pumpe.
Die genutzte Pumpe arbeitet mit 3–5 V und kann daher ohne Bedenken direkt an der Batterie betrieben werden.

Die von mir genutzte Pumpe wird im Netz oft als JT-DC3W-Pumpe bezeichnet.
Der MOSFET, den ich nutze, ist der IRLZ44N. Grundsätzlich funktionieren aber auch andere MOSFETs,
die schon mit 3,3 V Gate-Spannung voll durchschalten (sogenannte Logic-Level-MOSFETs).

**Pumpe:**

- Amazon; 3 Stück für 8,99 €: [amazon.de](https://www.amazon.de/RUNCCI-YUN-Wasserpumpe-Motorpumpe-Schlauch-Bew%C3%A4sserung/dp/B082PM8L6X/)
- AliExpress; 1x für 1,89 €: [aliexpress.com](https://de.aliexpress.com/item/1005007401287244.html)

**MOSFET:**

- Reichelt; 1x 70 ct: [reichelt.de](https://www.reichelt.de/de/de/shop/produkt/mosfet_n-ch_55v_47a_110w_to-220ab-129819)
- AliExpress; 10 Stück für 3,35 €: [aliexpress.com](https://de.aliexpress.com/item/1005007900687643.html)

Zusätzlich habe ich mithilfe eines 10-kΩ-Widerstands Gate und Source des MOSFETs (also den GPIO-Ausgang und GND) verbunden,
um ein versehentliches Einschalten der Pumpe zu verhindern (z. B. beim Hochfahren des ESP32,
wenn die Ausgänge noch nicht klar definiert sind und die Spannungen floaten können).
Ein 10-kΩ-Widerstand kostet nur wenige Cent und ist überall erhältlich, daher verzichte ich hier auf einen konkreten Link.

### 2,9-Zoll-E-Paper-Display

Das E-Paper ist wohl das teuerste Teil des Sensorknotens. Das E-Paper-Display zeigt in meinem System die wichtigsten Infos direkt
an der Pflanze an, unabhängig davon, ob sich der Sensorknoten im letzten Durchgang mit der Webapp/dem Host verbinden konnte oder nicht.
Auf dem E-Paper wird z. B. angezeigt, wie feucht der Boden bei der letzten Messung war, ob und wie viel gegossen wurde,
wann die letzte Messung stattfand und wann die nächste stattfindet, und noch einiges mehr.
Dazu eignen sich nur E-Paper-Displays, weil diese nur beim Aktualisieren Strom brauchen und ohne Strom ihr Bild einfach behalten.

Die E-Paper, die mein System unterstützt, sind von der Marke „MH-ET LIVE“. Es gibt drei Versionen von diesem E-Paper:
eine schwarz/weiße, eine schwarz/weiß/rote und eine schwarz/weiß/rot/gelbe. Für alle drei wurden Treiber implementiert.
Empfohlen ist jedoch das schwarz/weiße, da es eine Displayaktualisierung in ca. 2 Sekunden schafft,
die farbigen Displays hingegen über 15 Sekunden brauchen. Somit ist das schwarz/weiße E-Paper deutlich energieeffizienter.

Die eigentlichen Panels dieser E-Paper-Module stammen von der Firma „Good-Display“. Es kann also sein,
dass andere E-Paper-Module die gleichen Panels verbaut haben und auch funktionieren. Das konnte ich bisher aber nicht testen.

Welche der drei Varianten Sie nutzen, müssen Sie auch in der Firmware einstellen: In
`firmware/main/config.h` gibt es dafür drei Flags — `USE_BW_DISPLAY`,
`USE_BWR_DISPLAY` und `USE_4COLOR_DISPLAY`. Genau einer davon muss auf `1` stehen, die anderen
beiden auf `0`. Default ist `USE_BW_DISPLAY=1` (also das schwarz/weiße); für die anderen
Varianten setzen Sie das jeweilige Flag auf `1` und die anderen zwei auf `0`, dann neu bauen
und flashen.

In Deutschland bekommen Sie das E-Paper leider nur in der schwarz/weiß/roten Variante:

Amazon oder AZ-Delivery direkt; 1 für 27,99 €: [amazon.de](https://www.amazon.de/AZDelivery-Stromverbrauch-Unterst%C3%BCtzung-kompatibel-Schnittstelle/dp/B0B2DQXPVZ/)

Auf AliExpress gibt es das E-Paper auch in den beiden anderen Versionen deutlich günstiger.

AliExpress; Schwarz/Weiß für 17,19 €, Schwarz/Weiß/Rot und Schwarz/Weiß/Rot/Gelb für 16,99 €: [aliexpress.com](https://de.aliexpress.com/item/1005001299386642.html)

### 18650-Batterie

In meinem System sorgt eine 18650-Zelle mit angegebenen 3400 mAh für Strom.
Der genutzte FireBeetle 2 unterstützt durch einen Laderegler das Aufladen von Batterien per USB oder Solarpanel.
Ein zusätzliches Ladegerät ist also nicht nötig.

18650-Zellen bekommen Sie eigentlich überall, die Kapazität ist durch den niedrigen Stromverbrauch meines Systems
auch nicht so wichtig.

- Conrad; 1 Batterie für 14,99 €: [conrad.de](https://www.conrad.de/de/p/panasonic-ncr18650b-zlf-spezial-akku-18650-li-ion-3-7-v-3400-mah-1-st-1693222.html)
- AliExpress; 2 Batterien für 7,29 €: [aliexpress.com](https://de.aliexpress.com/item/1005007282401139.html)

### Optional: 5-V-Solarpanel

Neben dem Laderegler hat der FireBeetle auch einen Solareingang, über den ein 5-V-Solarpanel die 18650-Zelle bei Sonnenschein aufladen kann.
Dadurch ergibt sich eine theoretisch unbegrenzte Laufzeit des Sensorknotens (bis die 18650-Zelle ihren Geist aufgibt).

Genutzt habe ich dieses 5-V-Solarpanel mit angegebenen 230 mA:

AliExpress; 1 Panel für 1,79 €: [aliexpress.com](https://de.aliexpress.com/item/1005009393447368.html)

### Eventuell auch benötigt

Falls Sie es zu Hause noch nicht haben, brauchen Sie zum Nachbauen außerdem einen Lötkolben,
z. B. für die Pin-Header am FireBeetle und am HTU21D, und entweder ein Breadboard oder ein Perfboard,
um alle Komponenten mit passenden Kabeln zu verbinden (Breadboardkabel beim Breadboard, normale Kabel beim Perfboard).

## Wie alles verkabelt wird

Welche GPIOs Sie verwenden, ist dank der sogenannten GPIO-Matrix des ESP32-C6 (also bei allen Boards mit dem ESP32-C6, nicht nur beim FireBeetle) frei wählbar.
I²C und SPI können daher an jeden GPIO-Pin angeschlossen werden.
Nur der Bodenfeuchtesensor muss an einen ADC-fähigen Pin, da nicht jeder Pin analoge Signale in digitale umwandeln kann.

Die Sensoren und das Display hängen nicht an der durchgängigen 3,3-V-Schiene des FireBeetle, sondern jeweils an einem eigenen GPIO-Pin
(sogenanntes Power Gating).

Die von mir verwendete Pinbelegung steht in der letzten Spalte der Tabelle unten und in `firmware/main/pins.h`.

Falls Sie das System anders verkabeln möchten, passen Sie diese `pins.h` einfach dementsprechend an.
Zwei Pins sind auf dem FireBeetle schon belegt und deshalb nicht frei: GPIO 0 misst über einen
eingebauten Spannungsteiler die Batteriespannung, und auf GPIO 9 liegt die Boot-Taste.
Eine Übersicht, welche Pins des FireBeetle GPIOs sind, finden Sie hier: [wiki.dfrobot.com](https://wiki.dfrobot.com/dfr1075/#tech_specs)

(Direkt zum [Pin-Diagramm](https://dfimg.dfrobot.com/5d57611a3416442fa39bffca/wiki/1fa8b29bf6d340347ccdc39f4648b949_0x0.png.webp))

**Zusammengefasst:**

| Bauteil | Anschluss | Ziel | Meine Belegung (`pins.h`) |
|---|---|---|---|
| E-Paper | BUSY | frei wählbarer GPIO-Pin | GPIO 6 |
| E-Paper | RST | frei wählbarer GPIO-Pin | GPIO 15 |
| E-Paper | D/C | frei wählbarer GPIO-Pin | GPIO 3 |
| E-Paper | CS | frei wählbarer GPIO-Pin | GPIO 4 |
| E-Paper | SCLK | frei wählbarer GPIO-Pin | GPIO 5 |
| E-Paper | SDI | frei wählbarer GPIO-Pin | GPIO 19 |
| E-Paper | VCC | frei wählbarer GPIO-Pin | GPIO 20 |
| E-Paper | GND | GND | GND |
| HTU21D | SDA | frei wählbarer GPIO-Pin | GPIO 22 |
| HTU21D | SCL | frei wählbarer GPIO-Pin | GPIO 21 |
| HTU21D | VCC | frei wählbarer GPIO-Pin | GPIO 23 |
| HTU21D | GND | GND | GND |
| Bodenfeuchtesensor | ADC | einer der ADC-Pins des FireBeetle (wichtig) | GPIO 1 |
| Bodenfeuchtesensor | VCC | frei wählbarer GPIO-Pin | GPIO 18 |
| Bodenfeuchtesensor | GND | GND | GND |
| Pumpe | Pumpe(+) | Batterie(+) | |
| Pumpe | Pumpe(-) | MOSFET Drain | |
| MOSFET | Gate | frei wählbarer GPIO-Pin | GPIO 8 |
| MOSFET | Source | GND | GND |
| MOSFET | Drain | Pumpe(-) | |
| MOSFET | Gate und Source | mit einem 10-kΩ-Widerstand verbinden | |
| 18650-Batterie | BAT(+) | BAT(+)-Pad oder -Stecker des FireBeetle und Pumpe(+) | |
| 18650-Batterie | BAT(-) | BAT(-)-Pad oder -Stecker des FireBeetle | |

Ein LM393-Sensor wird genauso angeschlossen: AO an den ADC-Pin (GPIO 1), VCC an GPIO 18, GND an GND.
Den Digitalausgang DO braucht elHydro nicht, er bleibt frei.

## Wie Sie die Software auf den ESP32 bekommen

Am bequemsten geht das über die offizielle ESP-IDF-Extension für Visual Studio Code.
Sie übernimmt die Installation der ganzen ESP-IDF-Toolchain und alles, was Sie zum Bespielen des FireBeetle benötigen.

Dieses dreiminütige YouTube-Video zeigt die Installation ganz gut: [youtube.com](https://www.youtube.com/watch?v=_3pegsTyRDE)

Anders als im Video würde ich empfehlen, eine v5.x-Version zu wählen (am besten v5.5),
weil elHydro mit ESP-IDF 5.5 entwickelt wurde.

Haben Sie die ESP-IDF-Extension in VS Code installiert und eingerichtet, gehen Sie so vor:

1. Den Firmware-Ordner in VS Code öffnen (Datei → Ordner öffnen → `firmware/`).

2. In `pins.h` prüfen, ob die Pinbelegung zu Ihrer Verkabelung passt, und einmal in die `config.h` schauen, ob die Display-Variante
   (Schwarz/Weiß, Schwarz/Weiß/Rot oder vier Farben), der genutzte Bodenfeuchtesensor (kapazitiv v2.0 oder LM393) und die Zeitzone
   richtig eingestellt sind. Allgemein lohnt es sich, dort einmal durchzuscrollen, ob alles so konfiguriert ist, wie Sie es haben möchten.

3. In der unteren Statusleiste das Target auf „esp32c6“ setzen (Button „ESP-IDF: Set Espressif device target“).

4. Den FireBeetle per USB-C an den Rechner anschließen und in der Statusleiste den Button
   „Build, Flash and start a monitor“ klicken (das Flammensymbol).
   Auf „Auto“ sollte der COM-Port den FireBeetle eigentlich selbstständig erkennen.
   Falls nicht, klicken Sie auf den Button „Select Port to use“ und wählen den passenden COM-Port aus.

## Einrichtung

Haben Sie den Sensorknoten gebaut und den FireBeetle mit der Firmware bespielt,
können Sie den Sensorknoten schon mal aufbauen (alles verbinden, Pumpe in den Wassertank, Sensor in die Erde).

Nach dem ersten Flash zeigt das E-Paper einen Setup-Bildschirm, und der Sensorknoten beginnt,
sich per BLE als „elHydro-ESP32C6“ zu melden.
Findet ihn 10 Minuten lang kein Host, legt er sich für 30 Minuten schlafen und meldet sich danach erneut,
damit der Akku nicht leer läuft. Mit einem Druck auf den Reset-Knopf meldet er sich sofort wieder.
Am einfachsten starten Sie deshalb zuerst die Desktopanwendung und schließen dann den Akku an.

Die weitere Einrichtung übernimmt das Web-Dashboard:

1. Die Desktopanwendung starten und den Webserver hochfahren
   (siehe [desktopanwendung.md](desktopanwendung.md)). Das Dashboard am Rechner oder Handy im Browser öffnen.

2. Auf „Gerät hinzufügen“ klicken. Der Sensorknoten taucht in der BLE-Liste auf.
   Vergeben Sie den gewünschten Namen und wählen Sie ein Pflanzen-Preset aus.
   Pflanzen-Presets können Sie im Tab Presets erstellen und bearbeiten.

3. Auswählen, ob der Sensorknoten eine Pflanze drinnen (Indoor) oder draußen (Outdoor) überwacht.
   Wählen Sie Outdoor, tragen Sie bitte entweder den Namen Ihrer Stadt oder die Koordinaten Ihrer Position ein.
   Im Outdoor-Modus werden Wettervorhersagen verwendet, um Schlafdauer und Bewässerungsentscheidung zu verbessern.

4. Auf „Gerät registrieren“ klicken.
   Der Sensorknoten sollte nach kurzer Zeit den Ersteinrichtungsmodus verlassen,
   die erste Messung durchführen und an die Webapp senden.

Herzlichen Glückwunsch, Sie haben es geschafft!

Ab diesem Zeitpunkt arbeitet der Sensorknoten autonom:
Er wacht in den vom Brain berechneten Intervallen auf, misst, sendet die Daten an die Anwendung,
bewässert bei Bedarf und legt sich anschließend wieder in den Deep Sleep schlafen.

Ich empfehle, an diesem Punkt den Bodenfeuchtesensor zu kalibrieren:
Drücken Sie dreimal hintereinander im Abstand von ca. einer Sekunde den Reset-Knopf des FireBeetle, dann startet der Sensorknoten im Kalibriermodus.
Folgen Sie dort den Anweisungen, die auf dem E-Paper erscheinen.

Wollen Sie den Sensorknoten auf Werkseinstellungen zurücksetzen, drücken Sie dazu fünfmal hintereinander den Reset-Knopf.
Nach dem dritten Druck erscheint kurz der Kalibriermodus, drücken Sie einfach weiter.
Zum Bestätigen drücken Sie dann, sobald das E-Paper-Display Sie dazu auffordert, den Boot-Knopf.
Tun Sie das nicht und lassen 15 Sekunden verstreichen, wird der Reset-Counter auf 0 zurückgesetzt, und der Sensorknoten startet einen regulären Zyklus.
Außerdem wird der Reset-Counter bei jedem Zyklusdurchlauf auf 0 gesetzt.
Zufälliges Starten des Kalibrier- oder Factory-Reset-Modus ist dadurch so gut wie ausgeschlossen,
vor allem da beide Modi nach einer Weile ohne Eingabe automatisch beendet werden.

Nach einem Werksreset startet der Sensorknoten wieder im Setup-Modus, und die Kalibrierung steht auf den Standardwerten.
Ist er im Dashboard noch registriert, müssen Sie ihn nicht neu hinzufügen: Die Desktopanwendung schickt ihm
die Einstellungen beim nächsten Kontakt von selbst. Das dauert nur etwa 20 Sekunden länger als eine normale Verbindung.
