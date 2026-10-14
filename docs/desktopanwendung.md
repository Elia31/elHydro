# elHydro Desktopanwendung

Diese Datei sollte Ihnen dabei helfen, die Desktopanwendung zu starten
und auszuprobieren. Ich habe versucht, die Desktopanwendung auch dann
zugänglich zu machen, wenn Sie keinen elHydro-Sensorknoten besitzen.

Falls Sie einen elHydro-Sensorknoten bauen möchten,
finden Sie eine Liste aller Teile und eine kleine Anleitung
in [`sensorknoten.md`](sensorknoten.md).

Der Source Code für die Desktopanwendung liegt im Repository unter [`webapp/`](../webapp/),
die Firmware für den ESP32 unter [`firmware/`](../firmware/).

Die Desktopanwendung ist das Gehirn des Systems. Sie empfängt per BLE die Messdaten der Sensorknoten,
berechnet auf Basis von Pflanzentyp, Wetter und Trocknungstrend, wann der Sensorknoten als nächstes
aufwachen soll und ob bewässert werden muss, und gibt diese Entscheidungen beim nächsten BLE-Kontakt
an den Sensorknoten zurück. Die Messhistorie wird gespeichert und in einem Web-Dashboard visualisiert,
das Sie vom Rechner selbst oder von jedem Gerät im lokalen Netzwerk öffnen können.

## Starten der Desktopanwendung

Es gibt drei Möglichkeiten, wie Sie die Desktopanwendung und damit die Webapp starten können.

### Starten über die `elHydro.exe` (empfohlen)

Der erste und einfachste Weg ist, falls Sie einen Windows-Rechner nutzen, die Anwendung über die `elHydro.exe` zu starten. Sie finden sie unter [Releases](https://github.com/Elia31/elHydro/releases).
Sie brauchen dazu keine Abhängigkeiten oder sowas zusätzlich zu installieren.
In der `.exe` sind bereits alle notwendigen Abhängigkeiten integriert.
Falls Sie die Anwendung das erste Mal starten, kann es sein, dass Windows den Start der `.exe` mit einem
kleinen blauen Fenster unterbindet, in dem "Der Computer wurde durch Windows geschützt" steht.
Das passiert, weil die `.exe` nicht mit einem von Microsoft anerkannten Code-Signing-Zertifikat signiert ist.
Solche Zertifikate kosten Geld, das ich jetzt nicht unbedingt ausgeben wollte. Es ist also keine echte
Gefahr, sondern nur eine Standard-Warnung von Windows.
Starten können Sie die `.exe` dann, indem Sie im blauen Fenster auf "Weitere Informationen" klicken und
anschließend auf "Trotzdem ausführen".
Beim nächsten Starten sollte dieser Dialog nicht noch einmal vorkommen.

Außerdem fragt die Windows-Firewall beim ersten Start höchstwahrscheinlich, ob die Anwendung
Verbindungen im lokalen Netzwerk annehmen darf. Das ist nötig, damit Sie das Dashboard auch von anderen
Geräten (z. B. vom Handy) aus erreichen können. Klicken Sie hier auf "Zugriff zulassen" (nur für
"Private Netzwerke", nicht für öffentliche, da das Dashboard keine Anmeldung hat). Falls Sie "Abbrechen"
klicken, läuft die Anwendung trotzdem, das Dashboard ist dann aber nur direkt vom Host-Rechner erreichbar.

### Starten über die `launcher.py`

Die Alternative zur `.exe` ist das Starten über die `launcher.py`.
Voraussetzung dafür ist, dass Python 3.10 oder neuer auf Ihrem Rechner installiert ist.
Navigieren Sie in Ihrem Terminal in den Ordner `webapp/`. Unter Windows wäre der Befehl dazu:

```bash
cd C:/ihr_pfad/elHydro/webapp
```

Legen Sie dort am besten zuerst eine virtuelle Umgebung an und aktivieren Sie diese,
damit die Abhängigkeiten nicht in Ihre systemweite Python-Installation installiert werden:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Unter Linux lautet der zweite Befehl `source .venv/bin/activate`. Unter Debian/Ubuntu installieren Sie vorher
mit `sudo apt install python3-venv python3-tk` die benötigten Pakete (Tkinter braucht der Launcher)
und verwenden `python3` statt `python`. Falls PowerShell unter Windows das Aktivieren blockiert,
nutzen Sie stattdessen die Eingabeaufforderung (cmd).
Bei jedem weiteren Start müssen Sie die virtuelle Umgebung nur erneut aktivieren.

Installieren Sie dann mithilfe von pip einmalig die benötigten Abhängigkeiten mit dem Befehl:

```bash
pip install -r requirements.txt
```

Haben Sie das getan, können Sie die Anwendung mithilfe des Befehls

```bash
python launcher.py
```

starten.
Es öffnet sich der gleiche Launcher, den Sie auch mit dem Starten der `.exe` sehen würden.

### Starten über die `main.py`

Falls Sie den Launcher nicht benötigen, können Sie den Webserver auch direkt starten.
Der Wechsel in den Ordner und die Installation der Abhängigkeiten funktionieren genauso wie im Absatz oben.
Die `main.py` startet den FastAPI-Server unmittelbar.
Host und Port lassen sich über

```bash
python main.py --host 0.0.0.0 --port 8080
```

setzen. Standard ist `0.0.0.0:8000`.
Zu erwähnen ist, dass das Starten über `main.py` Ihre Messungen standardmäßig in `webapp/data/` speichert.
Einen anderen Ordner legen Sie über die Umgebungsvariable `ELHYDRO_DATA_DIR` fest.

### Dauerbetrieb ohne Bildschirm (z. B. Raspberry Pi)

Auf einem Linux-Rechner ohne Bildschirm läuft die `main.py` am besten als systemd-Dienst.
Sie startet dann beim Hochfahren automatisch und nach einem Absturz neu.
Für den Bluetooth-Zugriff braucht es BlueZ (unter Raspberry Pi OS meist schon installiert),
und Ihr Benutzer muss in der Gruppe `bluetooth` sein:

```bash
sudo apt install bluez
sudo usermod -aG bluetooth $USER
```

Legen Sie dann die Datei `/etc/systemd/system/elhydro.service` an (z. B. mit `sudo nano /etc/systemd/system/elhydro.service`)
und ersetzen Sie `<benutzer>` und die Pfade passend zu Ihrem Klon und Ihrer virtuellen Umgebung:

```ini
[Unit]
Description=elHydro Host-Anwendung
After=bluetooth.target network-online.target
Wants=bluetooth.target network-online.target

[Service]
User=<benutzer>
WorkingDirectory=/home/<benutzer>/elHydro/webapp
ExecStart=/home/<benutzer>/elHydro/webapp/.venv/bin/python main.py --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Anschließend den Dienst aktivieren und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now elhydro
```

Die Ausgaben sehen Sie mit `journalctl -u elhydro -f`. Die Messungen landen wie oben beschrieben in `webapp/data/`,
außer Sie legen in der `[Service]`-Sektion mit `Environment=ELHYDRO_DATA_DIR=/pfad/zum/ordner` einen anderen Ordner fest.

### Die `elHydro.exe` selbst bauen

Die `.exe` aus den Releases entsteht mit PyInstaller aus der Datei `webapp/elHydro.spec`.
Wer sie selbst bauen möchte, installiert in der virtuellen Umgebung zusätzlich PyInstaller und baut im Ordner `webapp/`:

```bash
pip install pyinstaller
pyinstaller elHydro.spec
```

Die fertige `elHydro.exe` liegt danach in `webapp/dist/`.

### Tests ausführen

Für Änderungen am Code gibt es im Ordner `webapp/tests/` automatische Tests. Sie prüfen unter anderem
die Brain-Entscheidungen und dass Host und Firmware dasselbe Datenformat verwenden.
In der virtuellen Umgebung im Ordner `webapp/`:

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

Dieselben Prüfungen laufen auf GitHub automatisch bei jedem Pull Request und jedem Push auf `main`.

## Launcher im Überblick

Im Tab "Server" sehen Sie folgende Felder:

**Port:**
Den Port des Webservers (Standard ist `8000`)
Mit Port `80` müssen Sie im Browser keine Portnummer (wie `:8000`) an die Adresse hängen. Eventuell brauchen Sie dafür Administratorrechte.

**Datenverzeichnis:**
Das Datenverzeichnis, in dem alle Messungen und Konfigurationen gespeichert werden.
Standardmäßig werden Mess- und Konfigurationsdaten hier gespeichert:

- Windows: `C:\Users\<Benutzer>\elHydro`
- Linux:   `~/.local/share/elHydro`

Den Ort für die Konfigurationsdatei des Launchers können Sie nicht anpassen.

**mDNS aktivieren/deaktivieren:**
Ist mDNS nicht aktiviert, startet der Webserver auf der IP-Adresse Ihres Rechners (also irgendwas wie `192.168...`).
Ist mDNS aktiviert, können Sie einstellen, ob der Webserver auf dem Hostnamen Ihres Rechners (z. B. `Elia-Laptop.local:8000`) startet
oder ob Sie mithilfe von Zeroconf einen eigenen Namen festlegen, wie zum Beispiel `elhydro.local`.
Zusammen mit dem Setzen des Ports auf `80` lässt sich so die benutzerfreundlichste Konfiguration einstellen. Nutzer können innerhalb des Netzwerkes
dann über z. B. `elhydro.local` oder `pflanzen.local` ihre Pflanzen auch vom Handy schnell überprüfen.
Nicht jedes Gerät kann `.local`-Namen auflösen, vor allem ältere Android-Handys nicht. Klappt die Adresse dort nicht,
deaktivieren Sie mDNS. Adresse und QR-Code enthalten dann die IP-Adresse des Rechners.

**Optionen:**

- "Beim Schließen in System Tray minimieren" - Ist diese Option ausgewählt, läuft der Server auch dann weiter, wenn Sie das Bestätigungsfenster,
  das nach dem Starten des Webservers erscheint, mit X schließen.
  Im System Tray (der Ort in der Taskleiste, wo man z. B. auch sieht, dass OneDrive läuft) erscheint dann das elHydro-Icon.
  Per Linksklick öffnen Sie das Bestätigungsfenster erneut.
  Per Rechtsklick öffnet sich ein Menü, mit dem Sie das Bestätigungsfenster öffnen, die Dashboardseite im Browser öffnen
  oder die elHydro-Anwendung sofort beenden und schließen.
  Unter Linux hängt es von der Desktopumgebung ab, ob der Linksklick funktioniert, das Menü gibt es dort immer.

- "Bei Systemstart automatisch starten" - Ist diese Option ausgewählt, startet elHydro bei der Anmeldung am Rechner von selbst
  und fährt den Server gleich mit den gespeicherten Einstellungen hoch. Ist das Minimieren in den System Tray aktiv,
  läuft er dort im Hintergrund, sonst wird das Fenster minimiert.
  Unter Windows wird hierfür ein Eintrag in `HKEY_CURRENT_USER\…\Run` angelegt, unter Linux eine `.desktop`-Datei in `~/.config/autostart/`.
  Hinterlegt wird der aktuelle Pfad der `.exe` bzw. der `launcher.py`, bei jedem Start des Launchers neu.
  Wenn Sie die Anwendung später woandershin verschieben, starten Sie sie einmal von Hand am neuen Ort.

**Extras:**

- "E-Paper Simulator starten" - startet den E-Paper Simulator in einem neuen Fenster. Dazu im späteren Absatz mehr.

**Button: "Server starten"** - Durch Klicken dieses Buttons wird, wie der Name schon verrät, der Webserver mit den konfigurierten Einstellungen gestartet.
Es öffnet sich ein Bestätigungsfenster mit der Adresse, wo der Webserver läuft, einem QR-Code zum einfachen Scannen mit dem Handy,
einem Button zum Öffnen des Dashboards im Browser und einem Button zum Stoppen des Webservers.
Haben Sie in den Optionen das Minimieren in den System Tray aktiviert, können Sie dieses Bestätigungsfenster per X schließen und der Server läuft weiter.

## Test von elHydro ohne Hardware

Wie vorhin schon angeschnitten, bietet der Launcher zwei Funktionen, die auch Nutzern ohne elHydro-Sensorknoten
einen kleinen Einblick in elHydro bieten sollen. Zum einen wäre das der E-Paper-Simulator
und zum anderen die Möglichkeit, Testdaten zu erstellen, wie sie auch vom elHydro-Sensorknoten real hätten kommen können.

### E-Paper-Simulator

Klicken Sie im Reiter "Server" unter "Extras" auf "E-Paper Simulator starten".
Es öffnet sich ein Fenster, das das E-Paper-Display des Sensorknotens 1:1 nachbildet.
Das nachgebildete E-Paper ist die Vier-Farben-Variante.
Auf dem echten elHydro-Sensorknoten werden die Farben je nach verwendetem E-Paper reduziert:
Das 4-Farben-Display zeigt alle Farben an, also Schwarz/Weiß/Rot/Gelb,
bei der schwarz/weiß/roten Variante wird Gelb zu Schwarz
und bei der schwarz/weißen Variante werden Rot und Gelb zu Schwarz.
Das Layout unterscheidet sich bei den Varianten nicht.

Mit den Pfeiltasten Hoch/Runter können Sie den Bodenfeuchtewert um jeweils 5 Prozent erhöhen bzw. verringern.
Mit den Pfeiltasten Links/Rechts können Sie durch die verschiedenen Screens wechseln, die auch im realen Betrieb des E-Papers vorkommen können.
Falls die Pfeiltasten nicht reagieren, klicken Sie mit der Maus bitte einmal auf das Terminal-Fenster unter dem Screen.

Im eingebauten Terminal gibt `help` alle integrierten Befehle aus, mit denen Sie das E-Paper anpassen können.
Ein Beispiel wäre `soil 42`. So würde der Bodenfeuchtewert auf 42 % gesetzt werden.

### Testdaten-Tab

Den Tab "Testdaten" finden Sie im Launcher oben neben dem Tab "Server".
Über den Testdaten-Tab können Sie Messhistorien erzeugen, wie sie ein echter Sensorknoten über Tage/Wochen liefern würde.
Die Schlafzeit- und Bewässerungsberechnung greift dabei auf dieselbe Brain-Logik (`brain.py`) zurück,
die auch im Realbetrieb auf dem Host läuft und dem ESP32 die nächste Schlafdauer und Bewässerungsentscheidung vorgibt.
Sie sehen also genau die Entscheidungen, die im echten Betrieb fallen würden.

Damit das Ergebnis realistisch wirkt, können auch Offline-Phasen auftreten, bei denen der Sensorknoten den Host nicht erreichen konnte.
Zwei Werte, die Sie im Testdaten-Tab festlegen können, steuern das Verhalten in solchen Phasen:

**Bewässerungs-Delta (in %)** - Wie weit darf die Bodenfeuchte unter den Zielwert fallen, bevor bewässert wird?
Beispiel: Ziel 45 %, Delta 10 % - bewässert wird spätestens ab unter 35 %, bei Wärme und trockener Luft etwas früher. Gilt sowohl im Online- als auch im Offline-Modus.

**Offline Sleep (in Minuten)** - Basis-Schlafdauer im Offline-Modus.
Wird abhängig vom Abstand der aktuellen Bodenfeuchte zum Schwellwert sowie von der Verdunstungsrate dynamisch verkürzt oder verlängert.

Wird als Gerätestandort Outdoor gewählt, werden nur für die letzte (die aktuellste) Messung die Wetterdaten abgerufen,
bei der Brain-Entscheidung berücksichtigt und im Dashboard angezeigt.

Die generierten Daten landen im konfigurierten Datenverzeichnis, genauso wie es bei einem echten Gerät der Fall wäre.

Ohne Launcher erzeugt `python tools/generate_dummy_data.py` (im Ordner `webapp/`) dieselben Testdaten, die Optionen zeigt `--help`.
Das Skript schreibt wie `python main.py` standardmäßig nach `webapp/data/`, mit `--data-dir` in einen anderen Ordner,
z. B. in das Datenverzeichnis des Launchers. Lassen Sie es nur laufen, während der Server gestoppt ist, und starten Sie
den Server danach (neu): Ein laufender Server kennt das neue Gerät nicht und überschreibt die `device_settings.json`
beim nächsten Speichern mit seinem alten Stand.

## Hinweise zum Betrieb

**Mehrere Sensorknoten:**
Die Desktopanwendung verbindet sich immer nur mit einem Sensorknoten gleichzeitig. Ein Knoten wartet nach dem Aufwachen
etwa 15 Sekunden auf die Verbindung. Wachen zwei Knoten fast gleichzeitig auf, oder sendet einer gerade viele
gepufferte Messungen nach, verpasst der zweite unter Umständen dieses Zeitfenster. Er entscheidet dann in diesem Durchlauf
selbst über Schlafdauer und Bewässerung, wie ohne Host, und liefert die Messung beim nächsten Kontakt nach.
Es gehen also keine Daten verloren.

**Wetter ohne Internet:**
Für Outdoor-Geräte ruft die Anwendung die Wettervorhersage schon ab, während sie sich mit dem Knoten verbindet.
Liegt sie nach dem Empfang der Messung nicht innerhalb von 3 Sekunden vor, entscheidet das Brain ohne Wetter,
damit die Entscheidung noch rechtzeitig beim Knoten ankommt. Ein verspäteter Abruf wird für den nächsten Kontakt zwischengespeichert.

## Wie Sie elHydro wieder vollständig entfernen

Falls Sie die Anwendung samt aller Daten loswerden möchten:

1. Im Launcher den Autostart deaktivieren. Damit wird der entsprechende Registry- bzw. Autostart-Eintrag automatisch gelöscht.
2. Den Datenordner löschen (Windows: `C:\Users\<Benutzer>\elHydro`, Linux: `~/.local/share/elHydro`).
3. Falls Sie das Datenverzeichnis verlegt haben, diesen zusätzlichen Ordner ebenfalls löschen.
