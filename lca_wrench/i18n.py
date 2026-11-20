"""Language of the texts the server sends to the UI: English (default) or German.

German texts are the keys (the app was written in German): `_("Projekt «{name}» gibt es nicht.", name=n)` gives the
English translation, or the German text when the request asked for German (header X-Lang: de, set per request in
api.py). LCA_WRENCH_LANG=de makes German the default of the server. A text without translation stays German. Texts that are stored and shown later (undo history, model errors, job phases) are kept
as `msg(...)` and rendered with `render` when they are read, so they follow the language of the reader.
"""

from __future__ import annotations

import contextvars
import os

DEFAULT = "de" if os.environ.get("LCA_WRENCH_LANG") == "de" else "en"
LANG: contextvars.ContextVar[str] = contextvars.ContextVar("lca_wrench_lang", default=DEFAULT)


def _(de: str, **kw) -> str:
    text = EN.get(de, de) if LANG.get() == "en" else de
    return text.format(**kw) if kw else text


def msg(de: str, **kw) -> tuple:
    """A text to render later; hashable, so lists of them can be de-duplicated."""
    return (de, tuple(kw.items()))


def render(m) -> str:
    """A stored text: plain string (older entries) or (template, params) as from `msg` or read back from JSON."""
    if isinstance(m, (list, tuple)) and len(m) == 2 and isinstance(m[0], str):
        return _(m[0], **dict(m[1] or {}))
    return str(m)


def q(name) -> str:
    """A name in quotes of the current language."""
    return f"“{name}”" if LANG.get() == "en" else f"«{name}»"


EN = {
    # api
    "Nur lokal erreichbar.": "Only reachable from this computer.",
    "Nicht gefunden.": "Not found.",
    "Diese Wirkungsmethode gibt es in diesem Projekt nicht.": "This impact assessment method does not exist in this project.",
    # example
    "Das Beispiel braucht die Datenbank BAFU-2025-v2 in diesem Projekt.": "The example needs the database BAFU-2025-v2 in this project.",
    "Beispiel «{name}» angelegt": "Example “{name}” created",
    # engine
    "«{name}» hat keinen Referenzfluss (Produktion).": "“{name}” has no reference flow (production exchange).",
    "{n} Austausch(e) verweisen auf Prozesse, die es nicht mehr gibt.": "{n} exchange(s) point to activities that no longer exist.",
    "Ein Input verweist auf «{name}», das in keiner geladenen Datenbank liegt.": "An input points to “{name}”, which is not in any loaded database.",
    "Das Modell hat {n} Prozesse, aber {m} Produkte. Jeder Prozess braucht genau ein Referenzprodukt.":
        "The model has {n} activities but {m} products. Every activity needs exactly one reference product.",
    "Das Modell ist nicht lösbar: Die Produktionsmengen heben sich gegenseitig auf (singuläre Matrix).":
        "The model cannot be solved: the production amounts cancel each other out (singular matrix).",
    "Prozess {id} ist in diesem Projekt nicht berechenbar.": "Activity {id} cannot be calculated in this project.",
    "«{name}» hat mehrere Produkte. Wähle eines davon.": "“{name}” has several products. Choose one of them.",
    "«{name}» hat nur ein Produkt: eine Allokation ist nicht nötig.": "“{name}” has only one product: no allocation is needed.",
    "Eine Allokation von «{name}» nach «{strategy}» geht nicht: nicht alle Produkte haben diese Eigenschaft.":
        "“{name}” cannot be allocated by “{strategy}”: not all of its products have this property.",
    "Eine Allokation von «{name}» nach «{strategy}» geht nicht: die Werte ergeben zusammen null.":
        "“{name}” cannot be allocated by “{strategy}”: the values add up to zero.",
    "Allokation von «{name}» geändert": "Allocation of “{name}” changed",
    "Mehrere Produkte gibt es in Modellen im Format des Activity Browser 3. Lege dafür ein Modell mit mehreren Produkten "
    "pro Prozess an und kopiere den Prozess hinein.":
        "Several products exist in models in the format of the Activity Browser 3. Create a model with several products "
        "per activity for this and copy the activity into it.",
    "«{name}» hat mehrere Produkte: kopiere eines davon.": "“{name}” has several products: copy one of them.",
    "Inputs gehören zum Prozess, nicht zum Produkt: öffne den Prozess.":
        "Inputs belong to the activity, not to the product: open the activity.",
    "«{name}» hat mehrere Produkte: wähle eines davon als Input.": "“{name}” has several products: choose one of them as input.",
    "Die Menge eines Produkts kann nicht null sein.": "The amount of a product cannot be zero.",
    "Produkt «{product}» zu «{name}» hinzugefügt": "Product “{product}” added to “{name}”",
    "Das ist kein Produkt.": "This is not a product.",
    "Ein Prozess braucht mindestens ein Produkt.": "An activity needs at least one product.",
    "Dieses Produkt wird noch verwendet von {names}. Entferne dort zuerst den Input.":
        "This product is still used by {names}. Remove the input there first.",
    "Produkt «{product}» aus «{name}» entfernt": "Product “{product}” removed from “{name}”",
    "«{label}» von «{product}» geändert": "“{label}” of “{product}” changed",
    "Bitte einen Namen für die Eigenschaft eingeben (nicht «equal» oder «manual»).":
        "Please enter a name for the property (not “equal” or “manual”).",
    "Eigenschaft «{label}» für die Produkte von «{name}»": "Property “{label}” for the products of “{name}”",
    "Nach «{label}» wird gerade alloziert. Wähle zuerst eine andere Allokation.":
        "The allocation uses “{label}” now. Choose another allocation first.",
    "Eigenschaft «{label}» der Produkte von «{name}» entfernt": "Property “{label}” removed from the products of “{name}”",
    "«{name}» im Format des Activity Browser 3 gespeichert (mehrere Produkte pro Prozess)":
        "“{name}” stored in the format of the Activity Browser 3 (several products per activity)",
    "«{name}» hat mehrere oder fremde Referenzflüsse und lässt sich so nicht umstellen.":
        "“{name}” has several or foreign reference flows and cannot be converted like this.",
    "Für Modelle im Format des Activity Browser 3 (mehrere Produkte pro Prozess) geht das noch nicht.":
        "This does not work yet for models in the format of the Activity Browser 3 (several products per activity).",
    "Allokationen vergleichen geht für eigene Modelle; Hintergrunddaten sind schon alloziert.":
        "Comparing allocations works for own models; background data are already allocated.",
    "Die Allokationsfaktoren von «{name}» ergeben zusammen {total} statt 1.":
        "The allocation factors of “{name}” add up to {total} instead of 1.",
    # excel
    "Die Datei ist leer.": "The file is empty.",
    "Die Datei ist zu gross (höchstens 25 MB).": "The file is too large (25 MB at most).",
    "Das ist keine Excel-Datei (.xlsx).": "This is not an Excel file (.xlsx).",
    "Die Excel-Datei lässt sich nicht lesen (erwartet wird das Format von bw2io / Activity Browser): {error}":
        "The Excel file cannot be read (expected is the bw2io / Activity Browser format): {error}",
    "{n} Austausch(e) lassen sich keinem Datensatz im Projekt zuordnen, zum Beispiel: {shown}. Das Modell wurde nicht importiert.":
        "{n} exchange(s) cannot be linked to any dataset in the project, for example: {shown}. The model was not imported.",
    "{n} Austausch(e) passen auf mehrere Datensätze im Projekt (gleicher Name, gleiche Einheit, gleicher Ort, "
    "z. B. bei Prozessen mit mehreren Produkten), zum Beispiel: {shown}. Das Modell wurde nicht importiert.":
        "{n} exchange(s) match several datasets in the project (same name, unit and location, e.g. multi-output "
        "activities), for example: {shown}. The model was not imported.",
    "Die Parameter in der Datei lassen sich nicht berechnen: {error} Das Modell wurde nicht importiert.":
        "The parameters in the file cannot be calculated: {error} The model was not imported.",
    # uncertainty
    "Die Anzahl Ziehungen muss zwischen {lo} und {hi} liegen.": "The number of iterations must be between {lo} and {hi}.",
    "Für dieses Produkt gibt es keine Daten mit Unsicherheit.": "There is no data with uncertainty for this product.",
    "Schritt 1 von 2: Streuung der Daten messen und die wichtigsten Kandidaten auswählen":
        "Step 1 of 2: measuring the spread of the data and selecting the most important candidates",
    "Abgebrochen.": "Cancelled.",
    "Bitte den Schlüssel für die Szenariodaten von premise angeben.": "Please enter the key for the scenario data of premise.",
    "Bitte die Datenbank der Stoffflüsse wählen, mit der EXIOBASE verknüpft wird.": "Please choose the database of elementary flows EXIOBASE is linked to.",
    "Bitte ein oder mehrere Jahre zwischen 2005 und 2100 angeben.": "Please enter one or more years between 2005 and 2100.",
    "Bitte eine Version und ein Jahr von EXIOBASE wählen, oder eine Datei angeben.": "Please choose a version and a year of EXIOBASE, or give a file.",
    "Bitte eine ecoinvent-Datenbank des Projekts als Ausgangspunkt wählen.": "Please choose an ecoinvent database of the project as the starting point.",
    "Bitte genau eine Hintergrund-Datenbank wählen.": "Please choose exactly one background database.",
    "Bitte mindestens eine Hintergrund-Datenbank wählen.": "Please choose at least one background database.",
    "Datenbanken lassen sich nur dem offenen Projekt hinzufügen.": "Databases can only be added to the open project.",
    "Die Gegenprobe mit bw2calc": "The cross-check with bw2calc",
    "Die Unsicherheitsrechnung": "The uncertainty analysis",
    "EXIOBASE herunterladen (Zenodo, 0.6 bis 1 GB) …": "Downloading EXIOBASE (Zenodo, 0.6 to 1 GB) …",
    "EXIOBASE lesen (mehrere Minuten) …": "Reading EXIOBASE (several minutes) …",
    "Für premise fehlt das Installationswerkzeug uv. Installiere LCA Wrench neu (Installationsskript), dann ist es dabei.": "premise needs the installer tool uv, which is missing. Install LCA Wrench again (installation script) to get it.",
    "Szenario anwenden: Strom, Stahl, Zement, Treibstoffe, Verkehr … (10 bis 40 Minuten)": "Applying the scenario: electricity, steel, cement, fuels, transport … (10 to 40 minutes)",
    "Szenario-Datenbanken schreiben …": "Writing the scenario databases …",
    "Unbekannte Wahl für die Hintergrunddaten.": "Unknown choice of background data.",
    "Unbekannter Pfad «{p}».": "Unknown pathway «{p}».",
    "Die Liste der Datenbanken von «{name}» (databases.json) ist beschädigt, die Daten selbst sind unversehrt. "
    "Reparieren mit: python -m lca_wrench.repair \"{name}\" --write (im Ordner von LCA Wrench, mit dessen Python).":
        "The list of databases of «{name}» (databases.json) is damaged; the data themselves are intact. Repair with: "
        "python -m lca_wrench.repair \"{name}\" --write (in the LCA Wrench folder, with its Python).",
    "Die Szenariodatei {f} gibt es im Archiv von premise bei Zenodo nicht. Bitte ein anderes Modell oder einen anderen Pfad wählen.":
        "The scenario file {f} is not in premise's archive on Zenodo. Please choose another model or pathway.",
    "Für {m} gibt es den Pfad «{p}» im Archiv von premise {v} nicht. Vorhanden: {list}.":
        "premise {v} has no pathway «{p}» for {m} in its archive. Available: {list}.",
    "Unbekanntes Modell «{m}».": "Unknown model «{m}».",
    "Wirkungsmethoden um die EXIOBASE-Flüsse ergänzen …": "Adding the EXIOBASE flows to the impact methods …",
    "premise einrichten: eigene Python-Umgebung mit premise (einmalig, etwa 1 GB) …": "Setting up premise: its own Python environment (once, about 1 GB) …",
    "premise ist noch nicht eingerichtet.": "premise is not set up yet.",
    "premise liess sich nicht starten. Einzelheiten in lca-wrench.log.": "premise could not be started. Details in lca-wrench.log.",
    "premise starten und ecoinvent lesen (mehrere Minuten) …": "Starting premise and reading ecoinvent (several minutes) …",
    "premise {v} kann ecoinvent {ei} nicht verarbeiten (nur {ok}).": "premise {v} cannot process ecoinvent {ei} (only {ok}).",
    "{what} rechnet mit den Verknüpfungen, wie sie gespeichert sind. Die Modelle beziehen hier {n} Inputs aus einem anderen Hintergrund ({dbs}); wähle unter Start die Hintergrunddaten, mit denen die Modelle verknüpft sind, oder verschiebe die Modelle dorthin.": "{what} uses the links as they are stored. Here the models take {n} inputs from another background ({dbs}); under Start, choose the background data the models are linked to, or move the models there.",
    "Schritt 2 von 2: {n} Ziehungen mit {k} verfolgten Datenwerten": "Step 2 of 2: {n} iterations tracking {k} data values",
    "Für die Unsicherheitsrechnung braucht es mindestens ein Produkt und eine Methode.":
        "The uncertainty analysis needs at least one product and one method.",
    "Diese Unsicherheitsrechnung gibt es nicht (mehr).": "This uncertainty analysis does not exist (any more).",
    # models
    "«{name}» ist eine Hintergrund-Datenbank und bleibt unverändert. Kopiere den Prozess in ein eigenes Modell, um ihn zu ändern.":
        "“{name}” is a background database and stays unchanged. Copy the activity into your own model to change it.",
    "Bitte einen Namen eingeben.": "Please enter a name.",
    "Eine Datenbank «{name}» gibt es schon.": "A database “{name}” already exists.",
    "Modell «{name}» importiert": "Model “{name}” imported",
    "«{name}» wird noch von {n} Prozess(en) in anderen Datenbanken verwendet.": "“{name}” is still used by {n} activity(-ies) in other databases.",
    "Prozess «{name}» angelegt": "Activity “{name}” created",
    "«{name}» in «{database}» kopiert": "“{name}” copied into “{database}”",
    "«{name}» umbenannt oder beschrieben": "“{name}” renamed or described",
    "Dieser Prozess wird noch verwendet von {names}. Entferne dort zuerst den Input.":
        "This activity is still used by {names}. Remove the input there first.",
    "Prozess «{name}» gelöscht": "Activity “{name}” deleted",
    "Unbekannte Art von Austausch.": "Unknown exchange type.",
    "«{input}» zu «{name}» hinzugefügt": "“{input}” added to “{name}”",
    "Diese Art lässt sich hier nicht ändern.": "This type cannot be changed here.",
    "«{input}» in «{name}»: {old} → {new}": "“{input}” in “{name}”: {old} → {new}",
    "Den Referenzfluss kann man nicht entfernen, nur seine Menge ändern.": "The reference flow cannot be removed, only its amount changed.",
    "«{input}» aus «{name}» entfernt": "“{input}” removed from “{name}”",
    "Die Menge muss eine Zahl sein.": "The amount must be a number.",
    "GSD² muss grösser als 1 sein, z.B. 1.5.": "GSD² must be greater than 1, e.g. 1.5.",
    "Die Pedigree-Werte müssen ganze Zahlen von 1 bis 5 sein.": "The pedigree scores must be whole numbers from 1 to 5.",
    "Die Basisunsicherheit (GSD²) muss mindestens 1 sein.": "The basic uncertainty (GSD²) must be at least 1.",
    "Lauter 1 und eine Basisunsicherheit von 1 ergeben keine Streuung.":
        "All scores 1 and a basic uncertainty of 1 give no spread.",
    "Eine Lognormalverteilung braucht eine Menge, die nicht null ist.": "A lognormal distribution needs an amount that is not zero.",
    "Die Standardabweichung muss grösser als 0 sein.": "The standard deviation must be greater than 0.",
    "Das Minimum muss kleiner als das Maximum sein.": "The minimum must be smaller than the maximum.",
    "Die Menge muss zwischen Minimum und Maximum liegen.": "The amount must lie between minimum and maximum.",
    "Unbekannte Verteilung.": "Unknown distribution.",
    "Bitte für die Verteilung Zahlen eingeben.": "Please enter numbers for the distribution.",
    "Der Referenzfluss hat keine Unsicherheit.": "The reference flow has no uncertainty.",
    "Unsicherheit von «{input}» in «{name}»": "Uncertainty of “{input}” in “{name}”",
    "Es gibt nichts rückgängig zu machen.": "There is nothing to undo.",
    "Diesen Schritt gibt es nicht.": "This step does not exist.",
    # service
    "Projekt «{name}» gibt es nicht.": "There is no project “{name}”.",
    "{base} – Arbeitskopie": "{base} – working copy",
    "{base} – Arbeitskopie {n}": "{base} – working copy {n}",
    "Dieses Projekt ist ein Original und bleibt unverändert. Lege zuerst eine Arbeitskopie an oder kopiere den Prozess in ein eigenes Modell.":
        "This project is an original and stays unchanged. Create a working copy first, or copy the activity into your own model.",
    "Diese Änderung gibt es nicht.": "This change does not exist.",
    "Methode fehlt in diesem Projekt": "Method missing in this project",
    "Projekt im älteren Format von Brightway 2": "Project in the older Brightway 2 format",
    "Das Projekt «{name}» hat das ältere Format von Brightway 2 (Activity Browser 2). LCA Wrench öffnet "
    "es nicht direkt, sonst könnte der Activity Browser 2 es danach nicht mehr lesen. Lege eine Kopie an.":
        "The project “{name}” has the older Brightway 2 format (Activity Browser 2). LCA Wrench does not open it "
        "directly, otherwise the Activity Browser 2 could no longer read it afterwards. Create a copy.",
    "Das Projekt «{name}» hat schon das Format von LCA Wrench und braucht keine Kopie.":
        "The project “{name}” already has the LCA Wrench format and needs no copy.",
    "{base} (LCA Wrench)": "{base} (LCA Wrench)",
    "{base} (LCA Wrench {n})": "{base} (LCA Wrench {n})",
    "Der Ordner für die Kopie gibt es schon: {path}": "The folder for the copy already exists: {path}",
    "Nicht berechenbar": "Cannot be calculated",
    "«Warum anders?» gibt es nur in einer Arbeitskopie: dort wird mit dem Original verglichen.":
        "“Why different?” only exists in a working copy: it compares with the original.",
    # parameters
    "Formel «{formula}» ist nicht lesbar: {error}": "Formula “{formula}” cannot be read: {error}",
    "Formel «{formula}»: unbekannter Name {names}": "Formula “{formula}”: unknown name {names}",
    "Formel «{formula}» ergibt keine Zahl.": "Formula “{formula}” does not give a number.",
    "Projekt": "Project",
    "Modell «{name}»": "Model “{name}”",
    "Prozess-Parameter": "Activity parameters",
    "{where}: {error}": "{where}: {error}",
    "{where}, Parameter «{name}»: {error}": "{where}, parameter “{name}”: {error}",
    "Parameter «{name}» ({where}) = {value}": "Parameter “{name}” ({where}) = {value}",
    "Parameter «{name}» ({where}) gelöscht": "Parameter “{name}” ({where}) deleted",
    "Formel für «{input}» in «{name}»: {formula}": "Formula for “{input}” in “{name}”: {formula}",
    "Formel für «{input}» in «{name}» entfernt": "Formula for “{input}” in “{name}” removed",
    "Bitte einen Wert oder eine Formel eingeben.": "Please enter a value or a formula.",
    "«{name}» geht nicht als Name: nur Buchstaben, Ziffern und _, nicht mit einer Ziffer beginnen, kein reserviertes Wort (wie «sin» oder «pi»).":
        "“{name}” cannot be a name: only letters, digits and _, not starting with a digit, no reserved word (like “sin” or “pi”).",
    "Parameter gibt es hier nur für eigene Modelle.": "Here parameters exist only for your own models.",
    "Den Parameter «{name}» gibt es nicht.": "There is no parameter “{name}”.",
    "Den Namen «{name}» gibt es hier schon.": "The name “{name}” already exists here.",
    "«{name}» wird noch gebraucht: {error}": "“{name}” is still needed: {error}",
    "Der Referenzfluss bekommt keine Formel.": "The reference flow gets no formula.",
    "Das ist eine Zahl, keine Formel. Zahlen bitte direkt als Menge eingeben.": "This is a number, not a formula. Please enter numbers directly as the amount.",
    "Diese Menge kommt aus der Formel «{formula}». Ändere die Formel oder entferne sie.":
        "This amount comes from the formula “{formula}”. Change the formula or remove it.",
    # versions
    "Der Versionsvergleich geht für Hintergrunddaten (z.B. ecoinvent), nicht für eigene Modelle.":
        "The version comparison works for background data (e.g. ecoinvent), not for your own models.",
    "Die Methode fehlt im Projekt «{name}».": "The method is missing in the project “{name}”.",
    "«{name}» ({location}) gibt es in «{database}» nicht eindeutig.": "“{name}” ({location}) does not exist exactly once in “{database}”.",
    "Wähle eine andere Datenbank oder ein anderes Projekt als Vergleich.": "Choose another database or another project to compare with.",
    "Die Datenbank «{name}» gibt es in diesem Projekt nicht.": "The database “{name}” does not exist in this project.",
    "Der Preis muss grösser als 0 sein.": "The price must be greater than 0.",
    "Das Gegenstück gibt es in «{name}» nicht mehr. Rechne den Vergleich neu.": "The counterpart no longer exists in “{name}”. Run the comparison again.",
    "Diesen Vergleich gibt es nicht mehr. Bitte neu vergleichen.": "This comparison no longer exists. Please compare again.",
    # setups
    "Die Rechnung «{name}» gibt es nicht.": "There is no calculation setup “{name}”.",
    "Bitte der Rechnung einen Namen geben.": "Please give the calculation setup a name.",
    "Eine Rechnung «{name}» gibt es schon.": "A calculation setup “{name}” already exists.",
    # units
    "Stück": "unit",
    # projects, protection, undo
    "Brightway baut «{name}» beim ersten Öffnen um (alle Rechendaten neu). Lege lieber eine Testkopie an oder bestätige das Öffnen des Originals.": "Brightway converts “{name}” when it is first opened (all calculation data anew). Better make a test copy, or confirm opening the original.",
    "Brightway baut «{name}» beim ersten Öffnen um. Öffne es zuerst oben in der Projektauswahl.": "Brightway converts “{name}” when it is first opened. Open it first in the project choice at the top.",
    "«{name}» wurde nicht in LCA Wrench angelegt (z.B. im Activity Browser). Damit dort nichts verloren geht, ändert LCA Wrench sie nur in einer Kopie des Projekts: oben in der Projektauswahl eine Testkopie anlegen.": "“{name}” was not made in LCA Wrench (e.g. in the Activity Browser). So that nothing gets lost there, LCA Wrench changes it only in a copy of the project: make a test copy in the project choice at the top.",
    "«{label}» lässt sich nicht rückgängig machen: die Daten wurden inzwischen anders geändert (z.B. im Activity Browser). Der Verlauf ist geleert, damit kein alter Schritt diese Änderung überschreibt.": "“{label}” cannot be undone: the data has been changed differently in the meantime (e.g. in the Activity Browser). The history is cleared so that no old step overwrites that change.",
    "Datenbanken, die nicht in LCA Wrench angelegt wurden, verwenden Parameter dieses Projekts. Damit dort nichts verloren geht, ändert LCA Wrench Projekt-Parameter nur in einer Kopie des Projekts: oben in der Projektauswahl eine Testkopie anlegen.": "Databases not made in LCA Wrench use parameters of this project. So that nothing gets lost there, LCA Wrench changes project parameters only in a copy of the project: make a test copy in the project choice at the top.",
    "Bitte zuerst oben ein Projekt wählen.": "Please choose a project at the top first.",
    # bafu2026
    "Für den Import von BAFU 2026 fehlt das Paket sentier-brightway. Installiere LCA Wrench neu (Installationsskript), dann ist es dabei.": "The package sentier-brightway, needed to import BAFU 2026, is missing. Install LCA Wrench again (install script), then it is included.",
    "Die Daten für BAFU 2026 liessen sich nicht laden (github.com). Internetverbindung prüfen und nochmals versuchen. Details: {error}": "The data for BAFU 2026 could not be downloaded (github.com). Check the internet connection and try again. Details: {error}",
    "Der Import von BAFU 2026 ist fehlgeschlagen: {error}": "The import of BAFU 2026 failed: {error}",
    # new projects, ecoinvent
    "Das Projekt «{name}» hat schon Daten von BAFU 2026.": "The project “{name}” already has data from BAFU 2026.",
    "Anmeldung bei ecoinvent fehlgeschlagen. Benutzername und Passwort prüfen.": "Login at ecoinvent failed. Check user name and password.",
    "Anmeldung oder Download bei ecoinvent fehlgeschlagen: {error}": "Login or download at ecoinvent failed: {error}",
    "BAFU 2026 laden und schreiben (etwa eine Minute) …": "Loading and writing BAFU 2026 (about a minute) …",
    "Bei ecoinvent anmelden …": "Logging in at ecoinvent …",
    "Bitte Benutzername und Passwort von ecoinvent angeben.": "Please enter your ecoinvent user name and password.",
    "Bitte den Pfad zur ecoSpold02-Datei von ecoinvent angeben.": "Please enter the path to the ecoSpold02 file from ecoinvent.",
    "Bitte einen Projektnamen angeben (höchstens 100 Zeichen).": "Please enter a project name (at most 100 characters).",
    "Das Projekt «{name}» gibt es schon.": "The project “{name}” already exists.",
    "Das Projekt «{name}» hat schon Daten. Importiert wird nur in ein neues oder leeres Projekt; wähle einen anderen Namen.": "The project “{name}” already has data. Imports go only into a new or empty project; choose another name.",
    "Datei nicht gefunden: {path}": "File not found: {path}",
    "Datei oder Ordner nicht gefunden: {path}": "File or folder not found: {path}",
    "Datenbank schreiben (mehrere Minuten) …": "Writing the database (several minutes) …",
    "Datensätze lesen und verknüpfen (mehrere Minuten) …": "Reading and linking the datasets (several minutes) …",
    "Diesen Auftrag gibt es nicht (mehr).": "This job does not exist (any more).",
    "Es läuft schon ein Import. Bitte warten, bis er fertig ist.": "An import is already running. Please wait until it is done.",
    "Für den Import von ecoinvent fehlt das Paket ecoinvent_interface. Installiere LCA Wrench neu (Installationsskript), dann ist es dabei.": "The package ecoinvent_interface, needed to import ecoinvent, is missing. Install LCA Wrench again (install script), then it is included.",
    "In «{name}» fehlen die Ordner datasets und MasterData. Gebraucht wird die Datei ecoSpold02 von ecoinvent.org (z.B. «ecoinvent 3.10_cutoff_ecoSpold02.7z»).": "“{name}” lacks the folders datasets and MasterData. Needed is the ecoSpold02 file from ecoinvent.org (e.g. “ecoinvent 3.10_cutoff_ecoSpold02.7z”).",
    "In «{name}» ist keine LCIA-Datei (.xlsx).": "“{name}” holds no LCIA file (.xlsx).",
    "Projekt öffnen und die Rechnung vorbereiten …": "Opening the project and preparing the calculation …",
    "Unbekannte Datenquelle.": "Unknown data source.",
    "Unbekannte ecoinvent-Version «{v}» (erwartet z.B. 3.10).": "Unknown ecoinvent version “{v}” (expected e.g. 3.10).",
    "Unbekanntes Dateiformat: {name} (erwartet .7z, .zip oder einen Ordner).": "Unknown file format: {name} (expected .7z, .zip or a folder).",
    "Unbekanntes Systemmodell «{m}».": "Unknown system model “{m}”.",
    "Vorbereiten …": "Preparing …",
    "Wirkungsmethoden laden und zuordnen …": "Loading and matching the impact methods …",
    "ecoinvent herunterladen (beim ersten Mal ca. 1 GB, danach aus dem Zwischenspeicher) …": "Downloading ecoinvent (about 1 GB the first time, then from the cache) …",
    "ecoinvent ist nicht erreichbar. Internetverbindung prüfen.": "ecoinvent cannot be reached. Check the internet connection.",
    "ecoinvent-Daten auspacken …": "Unpacking the ecoinvent data …",
    "«{name}» ist ein Projekt des Activity Browsers 2. Importiere in ein neues Projekt.": "“{name}” is a project of the Activity Browser 2. Import into a new project.",
    # BAFU <-> ecoinvent
    "Die Datei ist kein JSON: {error}": "The file is not JSON: {error}",
    "In der Datei fehlen die Einträge «replace» (Format randonneur, wie in sentier-mappings).": "The file lacks the “replace” entries (randonneur format, as in sentier-mappings).",
    "Die Datei enthält keine Zuordnung nach «{name}».": "The file holds no matches into “{name}”.",
    "Im Projekt «{name}» gibt es keine passende Methode. Wähle sie bei «Methode dort».": "The project “{name}” has no matching method. Choose it under “Method there”.",
    # example model (names in the UI language when it is made)
    "Vereinfachtes Lehrbeispiel von LCA Wrench mit geschätzten Mengen. Kein validierter Datensatz.": "Simplified teaching example of LCA Wrench with estimated amounts. Not a validated dataset.",
    "Beispiel – E-Bike": "Example – e-bike",
    "Beispiel – E-Bike ({n})": "Example – e-bike ({n})",
    "Rahmen, Aluminium": "Frame, aluminium",
    "Akku 500 Wh": "Battery 500 Wh",
    "Antrieb, Nabenmotor": "Drive, hub motor",
    "E-Bike, montiert": "E-bike, assembled",
    "Fahrt mit dem E-Bike": "Ride on the e-bike",
    "Beispiel – pro Kilometer": "Example – per kilometre",
    "Beispiel – pro Kilometer ({name})": "Example – per kilometre ({name})",
    # overview, export, regions
    "Alle Kategorien": "All categories",
    "Beiträge nach Prozess": "Contributions by activity",
    "Beiträge nach Stoff": "Contributions by flow",
    "Bitte einen Ort angeben, z.B. DE oder France.": "Please give a location, e.g. DE or France.",
    "Datenbank": "Database",
    "Einheit": "Unit",
    "Ergebnis": "Result",
    "Inventar": "Inventory",
    "Kategorie": "Category",
    "Kompartiment": "Compartment",
    "Lang": "Long",
    "Menge": "Amount",
    "Methode": "Method",
    "Ort": "Location",
    "Produkt": "Product",
    "Prozess": "Activity",
    "Stofffluss": "Flow",
    "Teil": "Section",
    "Wert": "Value",
    "Übrige": "Rest",
    "«{name}» hat Parameter. Modelle mit Parametern lassen sich noch nicht in eine andere Region verschieben; ändere den Strom dort von Hand.": "“{name}” has parameters. Models with parameters cannot be moved to another region yet; change the electricity there by hand.",
    "«{name}» ist kein Modell.": "“{name}” is not a model.",
    # removing a scenario or EXIOBASE (service.remove_background)
    "«{name}» wurde nicht von LCA Wrench hinzugefügt (Szenario oder EXIOBASE) und bleibt, wie sie ist.":
        "“{name}” was not added by LCA Wrench (scenario or EXIOBASE) and stays as it is.",
    "Es läuft ein Import. Bitte warten, bis er fertig ist.": "An import is running. Please wait until it has finished.",
    "«{name}» liess sich nicht löschen. Einzelheiten in lca-wrench.log.": "“{name}” could not be deleted. Details in lca-wrench.log.",
    # factors: which flows a method assesses, completed factors (completion.py)
    "ja": "yes",
    "nein": "no",
    "ja, über Flusszuordnung": "yes, through the flow mapping",
    "ja, ergänzt": "yes, completed",
    "Charakterisiert": "Characterized",
    "Faktor": "Factor",
    "Gleichnamiger Fluss mit Faktor": "Flow of the same name with a factor",
    "Schätzung, falls gleich bewertet": "Estimate if assessed alike",
    "Ergänzte Faktoren": "Completed factors",
    "Übernommen von": "Taken from",
}
