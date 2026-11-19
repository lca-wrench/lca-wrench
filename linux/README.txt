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
   To update, unpack a newer package over this folder and run ./install.sh again: the Python and the packages stay.
3. Start: "LCA Wrench" in the applications menu, or ./start.sh in this folder. The browser opens LCA Wrench.
   Keep the terminal window open, closing it (or Ctrl+C) stops LCA Wrench.
4. The interface is in English. "Deutsch" at the top right switches it to German.

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
   Zum Aktualisieren ein neueres Paket über diesen Ordner entpacken und ./install.sh nochmals laufen lassen:
   Python und Pakete bleiben.
3. Starten: «LCA Wrench» im Anwendungsmenü oder ./start.sh in diesem Ordner. Der Browser öffnet LCA Wrench.
   Das Terminal-Fenster offen lassen, Schliessen (oder Ctrl+C) beendet LCA Wrench.
4. Die Oberfläche ist englisch. «Deutsch» oben rechts schaltet auf Deutsch um.

Daten, eigene Projekte, Fehler und Entfernen: wie oben im englischen Teil. Brightway-Projekte liegen in
~/.local/share/Brightway3. Wenn etwas nicht klappt: «lca-wrench.log» (und bei einer misslungenen Installation
«installation-log.txt») aus diesem Ordner schicken.
