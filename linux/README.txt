LCA Wrench – installation on Linux
==================================

Needs a 64-bit Linux with glibc (Ubuntu, Debian, Fedora, Linux Mint, openSUSE, Arch ...; not Alpine), on x86_64 or
aarch64, and curl or wget. No root password, no system Python needed.

1. Unpack the archive into a permanent place, e.g. your home folder:
     tar -xzf LCA-Wrench-Linux.tar.gz -C ~
   This gives the folder ~/LCA-Wrench.
2. Install, in a terminal:
     cd ~/LCA-Wrench && ./install.sh
   It loads the tool uv, with it its own Python 3.12 and the packages (Brightway and the app). Takes about 3 to 5
   minutes, needs internet. Everything is installed inside this folder only: no PATH, no shell profile, no conda,
   the Brightway projects are not changed. At the end it adds "LCA Wrench" to the applications menu.
   To update to a newer version, see "Updating to a newer version" below.
3. Start: "LCA Wrench" in the applications menu, or ./start.sh in this folder. The browser opens LCA Wrench.
   Keep the terminal window open, closing it (or Ctrl+C) stops LCA Wrench.
4. The interface is in English. "Deutsch" at the top right switches it to German.

Updating to a newer version (e.g. from 0.1.0)
Your projects, with your models, calculation setups and the settings of LCA Wrench, stay as they are: they are in
~/.local/share/Brightway3, not in the folder LCA-Wrench, and the update does not touch them. The Python and the
packages in LCA-Wrench stay too; ./install.sh only replaces what changed.
1. Close LCA Wrench: Ctrl+C in its terminal, or close the terminal window. Let an import that is still running
   finish first.
2. Delete the program code of the old version (the folder lca_wrench, none of your data is in it), unpack the new
   package over the folder and install, in a terminal:
     rm -rf ~/LCA-Wrench/lca_wrench
     tar -xzf LCA-Wrench-Linux.tar.gz -C ~
     cd ~/LCA-Wrench && ./install.sh
   (With the folder elsewhere, use its path instead of ~/LCA-Wrench, and its parent folder instead of ~.)
3. Check: cat ~/LCA-Wrench/VERSION shows the new version number first. Start LCA Wrench: your projects are in the
   list at the top, and lca-wrench.log in the folder has a line "Start, version <new number>".
If ./install.sh says the folder is incomplete, do step 2 again. Installing into a new, empty folder works as well:
LCA Wrench finds the projects again, as they are not in its folder.

Data: a new project with BAFU 2026 or ecoinvent
On the start page "New project": empty, or right away with background data. Other projects stay untouched.
- BAFU 2026: the life cycle inventories of the Swiss Federal Administration (BAFU:2026) with the 25 impact
  categories of EF 3.1, freely available, loaded with sentier-brightway (about 36 MB, about a minute).
- ecoinvent with account: with your own user name and password of ecoinvent.org (sent to ecoinvent only).
  About 1 GB download, 10 to 30 minutes.
- ecoinvent from files: the file "ecoinvent 3.x_cutoff_ecoSpold02.7z" downloaded from ecoinvent.org and, for the
  impact methods, "ecoinvent 3.x_LCIA_implementation.7z". 10 to 30 minutes.

Trying your own projects
Brightway projects are in ~/.local/share/Brightway3. At the first start LCA Wrench asks which project to open. To try
it with your own data, best use "Make a test copy": LCA Wrench copies the project file by file without opening the
original. Everything can be changed in the copy, the original stays as it is.
- Projects from the Activity Browser 2 are opened only as a copy (otherwise the Activity Browser 2 could not read
  them any more).
- Projects from the Activity Browser 3 can also be opened directly. Databases not made in LCA Wrench are protected
  there: view and calculate yes, change only in a test copy.
- Do not have the Activity Browser and LCA Wrench open with the same project at the same time.

If something goes wrong: send the file "lca-wrench.log" from this folder (and "installation-log.txt" if the
installation failed). They hold the errors and the version of LCA Wrench.

Remove: delete the folder "LCA-Wrench" and ~/.local/share/applications/lca-wrench.desktop. Copies LCA Wrench
created are named "… (LCA Wrench)" and can be deleted in the Activity Browser like any project.


LCA Wrench – Installation unter Linux (Deutsch)
===============================================

Braucht ein 64-Bit-Linux mit glibc (Ubuntu, Debian, Fedora, Linux Mint, openSUSE, Arch …; nicht Alpine) auf x86_64
oder aarch64, und curl oder wget. Kein Root-Passwort, kein System-Python nötig.

1. Das Archiv an einen festen Ort entpacken, z.B. in den Benutzerordner:
     tar -xzf LCA-Wrench-Linux.tar.gz -C ~
   Das ergibt den Ordner ~/LCA-Wrench.
2. Installieren, im Terminal:
     cd ~/LCA-Wrench && ./install.sh
   Lädt das Werkzeug uv, damit ein eigenes Python 3.12 und die Pakete (Brightway und die App). Dauer etwa 3 bis
   5 Minuten, Internet nötig. Alles wird nur in diesen Ordner installiert: kein PATH, kein Shell-Profil, kein conda,
   die Brightway-Projekte werden nicht verändert. Am Schluss kommt «LCA Wrench» ins Anwendungsmenü.
   Zum Aktualisieren auf eine neuere Version siehe «Auf eine neuere Version aktualisieren» weiter unten.
3. Starten: «LCA Wrench» im Anwendungsmenü oder ./start.sh in diesem Ordner. Der Browser öffnet LCA Wrench.
   Das Terminal-Fenster offen lassen, Schliessen (oder Ctrl+C) beendet LCA Wrench.
4. Die Oberfläche ist englisch. «Deutsch» oben rechts schaltet auf Deutsch um.

Auf eine neuere Version aktualisieren (z.B. von 0.1.0)
Die Projekte, mit den eigenen Modellen, Rechnungen und den Einstellungen von LCA Wrench, bleiben wie sie sind: Sie
liegen in ~/.local/share/Brightway3, nicht im Ordner LCA-Wrench, und das Update verändert sie nicht. Auch Python
und die Pakete in LCA-Wrench bleiben; ./install.sh ersetzt nur, was sich geändert hat.
1. LCA Wrench beenden: Ctrl+C in seinem Terminal, oder das Terminal-Fenster schliessen. Einen laufenden Import
   vorher fertig laufen lassen.
2. Den Programmcode der alten Version löschen (den Ordner lca_wrench, darin sind keine eigenen Daten), das neue
   Paket über den Ordner entpacken und installieren, im Terminal:
     rm -rf ~/LCA-Wrench/lca_wrench
     tar -xzf LCA-Wrench-Linux.tar.gz -C ~
     cd ~/LCA-Wrench && ./install.sh
   (Liegt der Ordner anderswo, dessen Pfad statt ~/LCA-Wrench und den Ordner darüber statt ~ nehmen.)
3. Prüfen: cat ~/LCA-Wrench/VERSION zeigt zuerst die neue Versionsnummer. LCA Wrench starten: Die Projekte stehen
   oben in der Liste, und lca-wrench.log im Ordner hat eine Zeile «Start, version <neue Nummer>».
Meldet ./install.sh, der Ordner sei unvollständig, Schritt 2 nochmals machen. Auch eine Installation in einen neuen,
leeren Ordner geht: LCA Wrench findet die Projekte wieder, denn sie liegen nicht in seinem Ordner.

Daten, eigene Projekte, Fehler und Entfernen: wie oben im englischen Teil. Brightway-Projekte liegen in
~/.local/share/Brightway3. Wenn etwas nicht klappt: «lca-wrench.log» (und bei einer misslungenen Installation
«installation-log.txt») aus diesem Ordner schicken.
