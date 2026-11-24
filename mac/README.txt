LCA Wrench – installation on the Mac
====================================

1. Open "Install LCA Wrench" from the downloaded zip. The app is signed and notarized by Apple; macOS asks
   once whether to open an app downloaded from the internet.
2. Choose the folder: by default "LCA-Wrench" in your home folder (the house icon). In Documents, Desktop or
   Downloads macOS asks for Terminal access at every start. The installer copies this folder there and runs
   "Install LCA Wrench" in it: a Terminal window shows the progress. Takes about 3 to 5 minutes, needs internet.
   Everything is installed inside this folder only. The Activity Browser, conda and the
   Brightway projects are not changed. No administrator password needed.
   To update to a newer version, see "Updating to a newer version" below.
3. Start: double-click the app "LCA Wrench" on the desktop (the installer puts it there), or "Start LCA Wrench" in this
   folder.
   A package built without a signature is this folder alone: put it in a permanent place and double-click
   "Install LCA Wrench". macOS blocks it the first time: System Settings → Privacy & Security → at the bottom
   "Open Anyway", then double-click again (on older macOS versions: right-click → Open).
   The browser opens LCA Wrench (Google Chrome works best). Keep the Terminal window open,
   closing it stops LCA Wrench.
4. The interface is in English. "Deutsch" at the top right switches it to German.

Updating to a newer version (e.g. from 0.1.0)
Your projects, with your models, calculation setups and the settings of LCA Wrench, stay as they are: they are in
~/Library/Application Support/Brightway3, not in the folder LCA-Wrench, and the update does not touch them. The
Python and the packages in LCA-Wrench stay too; the installation only replaces what changed.
1. Close LCA Wrench: close its Terminal window. Let an import that is still running finish first.
2. Open "Install LCA Wrench" from the new zip and choose the same folder as before (the suggestion, if you kept
   it). The installer sees that it is an LCA Wrench folder: it replaces the program code of the old version (the
   folder "lca_wrench", none of your data is in it) and runs "Install LCA Wrench" there.
   A package without a signature is the folder alone: delete the folder "lca_wrench" in your LCA-Wrench folder,
   select everything in the new folder (Cmd+A), drag it into your LCA-Wrench folder and choose "Replace", then
   double-click "Install LCA Wrench" there.
3. Check: the file "VERSION" in LCA-Wrench begins with the new version number. Start LCA Wrench: your projects are
   in the list at the top, and the file "lca-wrench.log" in the folder has a line "Start, version <new number>".
If the installation says the folder is incomplete, do step 2 again. Installing into a new, empty folder works as
well: LCA Wrench finds the projects again, as they are not in its folder.

Data: a new project with BAFU 2026 or ecoinvent
On the start page "New project": empty, or right away with background data. Other projects stay untouched.
- BAFU 2026: the life cycle inventories of the Swiss Federal Administration (BAFU:2026) with the 25 impact
  categories of EF 3.1, freely available, loaded with sentier-brightway (about 36 MB, about a minute).
- ecoinvent with account: like in the Activity Browser, with your own user name and password of ecoinvent.org
  (sent to ecoinvent only). About 1 GB download, 10 to 30 minutes.
- ecoinvent from files: the file "ecoinvent 3.x_cutoff_ecoSpold02.7z" downloaded from ecoinvent.org and, for the
  impact methods, "ecoinvent 3.x_LCIA_implementation.7z". 10 to 30 minutes.

Comparing BAFU and ecoinvent
Build your model in a project with BAFU 2026, make a second project with ecoinvent, then open the result of
your product and the tab "Other database". Every BAFU dataset your model uses directly gets a counterpart in
ecoinvent: suggested from name, product, location and unit. Check the suggestions (the large ones first),
change them where needed, and confirm them. Confirmed matches are kept and can be exported as a JSON file in
the format of sentier-mappings, with ecoinvent datasets by code only.

Trying your own projects
At the first start LCA Wrench asks which project to open. To try it with your own data, best use
"Make a test copy": LCA Wrench copies the project file by file without opening the original. Everything
can be changed in the copy, the original stays as it is. With ecoinvent this takes a few minutes and needs
about as much disk space as the project.
- Projects from the Activity Browser 2 are opened only as a copy (otherwise the Activity Browser 2 could not
  read them any more).
- Projects from the Activity Browser 3 can also be opened directly. Databases not made in LCA Wrench are
  protected there: view and calculate yes, change only in a test copy. If the project was made with an older
  Brightway version, LCA Wrench asks first: Brightway rebuilds its calculation data when it is first opened.
- Do not have the Activity Browser and LCA Wrench open with the same project at the same time.

If something goes wrong: send the file "lca-wrench.log" from this folder. It holds the errors and the version
of LCA Wrench.

Remove: move the folder "LCA-Wrench" and the app "LCA Wrench" (desktop and Applications in your home folder) to the
Trash. Copies LCA Wrench created are named "… (LCA Wrench)"
(older ones "… (Werkbank)" or "… (Workbench)") and can be deleted in the Activity Browser like any project.


LCA Wrench – Installation auf dem Mac (Deutsch)
===============================================

1. «Install LCA Wrench» aus dem heruntergeladenen Zip öffnen. Die App ist von Apple signiert und beglaubigt;
   macOS fragt einmal, ob eine aus dem Internet geladene App geöffnet werden soll.
2. Den Ordner wählen: vorgeschlagen ist «LCA-Wrench» im Benutzerordner (das Haus-Symbol). In «Dokumente»,
   «Schreibtisch» oder «Downloads» fragt macOS beim Start jedes Mal nach Zugriffsrechten für das Terminal.
   Die Installation kopiert diesen Ordner dorthin und startet darin «Install LCA Wrench»: ein Terminal-Fenster
   zeigt den Fortschritt. Dauer: etwa 3 bis 5 Minuten, Internet nötig.
   Alles wird nur in diesen Ordner installiert. Der Activity Browser, conda und die
   Brightway-Projekte werden nicht verändert. Kein Administrator-Passwort nötig.
   Zum Aktualisieren auf eine neuere Version siehe «Auf eine neuere Version aktualisieren» weiter unten.
3. Starten: Doppelklick auf die App «LCA Wrench» auf dem Schreibtisch (legt die Installation dorthin) oder auf «Start LCA Wrench»
   in diesem Ordner.
   Ein Paket ohne Signatur ist nur dieser Ordner: an einen festen Ort legen und «Install LCA Wrench»
   doppelklicken. macOS blockiert das beim ersten Mal: Systemeinstellungen → Datenschutz & Sicherheit → ganz
   unten «Dennoch öffnen», danach nochmals doppelklicken (auf älteren macOS-Versionen: Rechtsklick → «Öffnen»).
   Der Browser öffnet LCA Wrench (am besten Google Chrome). Das Terminal-Fenster offen lassen,
   Schliessen beendet LCA Wrench.
4. Die Oberfläche ist englisch. «Deutsch» oben rechts schaltet auf Deutsch um (der Browser merkt es sich).

Auf eine neuere Version aktualisieren (z.B. von 0.1.0)
Die Projekte, mit den eigenen Modellen, Rechnungen und den Einstellungen von LCA Wrench, bleiben wie sie sind: Sie
liegen in ~/Library/Application Support/Brightway3, nicht im Ordner LCA-Wrench, und das Update verändert sie nicht.
Auch Python und die Pakete in LCA-Wrench bleiben; die Installation ersetzt nur, was sich geändert hat.
1. LCA Wrench beenden: sein Terminal-Fenster schliessen. Einen laufenden Import vorher fertig laufen lassen.
2. «Install LCA Wrench» aus dem neuen Zip öffnen und denselben Ordner wie beim letzten Mal wählen (den Vorschlag,
   falls er übernommen wurde). Die Installation erkennt den LCA-Wrench-Ordner: Sie ersetzt den Programmcode der alten
   Version (den Ordner «lca_wrench», darin sind keine eigenen Daten) und startet dort «Install LCA Wrench».
   Ein Paket ohne Signatur ist nur der Ordner: im eigenen LCA-Wrench-Ordner den Ordner «lca_wrench» löschen, im
   neuen Ordner alles auswählen (Cmd+A), in den eigenen LCA-Wrench-Ordner ziehen und «Ersetzen» wählen, dann dort
   «Install LCA Wrench» doppelklicken.
3. Prüfen: Die Datei «VERSION» in LCA-Wrench beginnt mit der neuen Versionsnummer. LCA Wrench starten: Die Projekte
   stehen oben in der Liste, und die Datei «lca-wrench.log» im Ordner hat eine Zeile «Start, version <neue Nummer>».
Meldet die Installation, der Ordner sei unvollständig, Schritt 2 nochmals machen. Auch eine Installation in einen
neuen, leeren Ordner geht: LCA Wrench findet die Projekte wieder, denn sie liegen nicht in seinem Ordner.

Daten: neues Projekt mit BAFU 2026 oder ecoinvent
Auf der Startseite «Neues Projekt»: leer, oder gleich mit Hintergrunddaten. Andere Projekte bleiben unberührt.
- BAFU 2026: die Ökoinventare der Bundesverwaltung (BAFU:2026) mit den 25 Wirkungskategorien von EF 3.1,
  frei verfügbar, geladen mit sentier-brightway (ca. 36 MB, etwa eine Minute).
- ecoinvent mit Konto: wie im Activity Browser, mit dem eigenen Benutzernamen und Passwort von ecoinvent.org
  (gehen nur an ecoinvent). Etwa 1 GB Download, 10 bis 30 Minuten.
- ecoinvent aus Dateien: die von ecoinvent.org heruntergeladene Datei «ecoinvent 3.x_cutoff_ecoSpold02.7z» und,
  für die Wirkungsmethoden, «ecoinvent 3.x_LCIA_implementation.7z». 10 bis 30 Minuten.

BAFU und ecoinvent vergleichen
Das Modell in einem Projekt mit BAFU 2026 bauen, ein zweites Projekt mit ecoinvent anlegen, dann beim Ergebnis
des Produkts den Reiter «Andere Datenbank» öffnen. Jeder BAFU-Datensatz, den das Modell direkt verwendet, bekommt
ein Gegenstück in ecoinvent, vorgeschlagen aus Name, Produkt, Ort und Einheit. Die Vorschläge prüfen (die grossen
zuerst), wo nötig ändern und bestätigen. Bestätigte Zuordnungen bleiben gespeichert und lassen sich als JSON-Datei
im Format von sentier-mappings exportieren, ecoinvent-Datensätze nur mit ihrem Code.

Eigene Projekte ausprobieren
Beim ersten Start fragt LCA Wrench, welches Projekt es öffnen soll. Zum Ausprobieren mit eigenen
Daten am besten «Testkopie anlegen»: LCA Wrench kopiert das Projekt Datei für Datei, ohne das Original
zu öffnen. In der Kopie lässt sich alles ändern, das Original bleibt wie es ist. Bei ecoinvent dauert das
einige Minuten und braucht etwa so viel Speicherplatz wie das Projekt.
- Projekte aus dem Activity Browser 2 öffnet LCA Wrench nur als Kopie (sonst könnte der Activity Browser 2
  sie danach nicht mehr lesen).
- Projekte aus dem Activity Browser 3 lassen sich auch direkt öffnen. Datenbanken, die nicht in LCA Wrench
  angelegt wurden, sind dort geschützt: ansehen und rechnen ja, ändern nur in einer Testkopie.
  Wurde das Projekt mit einer älteren Brightway-Version angelegt, fragt LCA Wrench vorher: Brightway baut
  beim ersten Öffnen seine Rechendaten neu auf.
- Activity Browser und LCA Wrench nicht gleichzeitig mit demselben Projekt offen haben.

Wenn etwas nicht klappt: die Datei «lca-wrench.log» in diesem Ordner schicken. Darin stehen die Fehler
und die Version von LCA Wrench.

Entfernen: den Ordner «LCA-Wrench» und die App «LCA Wrench» (Schreibtisch und «Programme» im Benutzerordner) in den
Papierkorb legen. Kopien, die LCA Wrench angelegt hat, heissen
«… (LCA Wrench)» (ältere «… (Werkbank)» oder «… (Workbench)») und lassen sich im Activity Browser wie jedes
Projekt löschen.
