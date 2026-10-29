# NetInv : scan du réseau local

Application d'inventaire du réseau local, en Python, sans dépendance et sans droits administrateur.

Elle liste les appareils de ton réseau avec leur **adresse IP, nom d'hôte, adresse MAC, fabricant, ports ouverts et latence**, les montre dans une vue 3D animée et exporte un rapport HTML, CSV, JSON ou texte.

## Démarrer (Windows)

1. Installer Python 3.9 ou plus récent : `winget install Python.Python.3.12`
2. Double-cliquer sur **`NetInv.bat`**
3. Le réseau actuel est déjà rempli : cliquer sur **Lancer le scan**

Pour un rapport sans ouvrir l'application : double-cliquer sur **`Rapport-rapide.bat`**. Le rapport s'enregistre dans `rapports\` puis s'ouvre dans le navigateur.

## Organisation du dossier

```
App-Scan/
├── NetInv.bat             ouvre l'application
├── Rapport-rapide.bat     scan en console + rapport HTML
├── rapports/              exports et rapports (ignoré par git : données de ton réseau)
├── netinv/                le code
│   ├── cli.py             ligne de commande : netinv scan / netinv gui
│   ├── scanner.py         découverte des appareils (ping + TCP), en parallèle
│   ├── ports.py           ports par défaut, ports sensibles, lecture "22,80,8000-8010"
│   ├── arp.py             table ARP du système → adresses MAC
│   ├── vendor.py          MAC → fabricant (data/oui.txt)
│   ├── exporters.py       tableau, CSV, JSON, HTML
│   ├── models.py          un appareil (Host)
│   ├── i18n.py            traductions (locales/fr.json, locales/en.json)
│   ├── data/oui.txt       préfixes MAC des fabricants
│   ├── locales/           textes de l'interface
│   └── ui/                l'application de bureau (Tkinter)
│       ├── app.py         la fenêtre : formulaire, tableau, export
│       ├── view3d.py      la vue 3D animée
│       └── theme.py       couleurs et polices (toutes définies ici)
└── tests/                 tests sans réseau : python -m unittest
```

## L'application

Les appareils s'affichent au fur et à mesure du scan, qui peut être arrêté à tout moment.

**Vue 3D animée** : chaque appareil apparaît autour du scanner, avec une forme et une couleur selon son type deviné à partir de ses ports (routeur, serveur, poste Windows, imprimante, autre). Pendant le scan, un balayage radar tourne au sol et une onde marque chaque nouvelle découverte. Des paquets circulent sur les liens, et un anneau rouge pulse autour des appareils qui ont des ports sensibles ouverts.

- Glisser pour faire tourner la scène, molette pour zoomer
- Survol ou clic : fiche de l'appareil (IP, MAC, fabricant, ports, latence), synchronisée avec le tableau
- Le filtre assombrit les appareils qui ne correspondent pas
- Le séparateur entre la vue 3D et le tableau peut être déplacé

**Tableau** :

- Clic sur un en-tête de colonne : trier
- Champ **Filtrer** : chercher une IP, un nom, une MAC, un fabricant ou un port
- Double-clic : ouvrir l'interface web de l'appareil (ports 443, 8006, 80, 8080), sinon copier son IP
- Clic droit : copier l'IP ou la MAC, ouvrir dans le navigateur, analyser à nouveau l'appareil
- **Exporter…** : HTML, CSV, JSON ou texte, dans `rapports\` par défaut (les lignes affichées, dans l'ordre affiché)
- Lignes rouges : ports sensibles ouverts (FTP, Telnet, NetBIOS, SMB, RDP)

**Design** : l'interface s'inspire d'une baie de brassage. Les surfaces sont en graphite et l'accent est l'ambre d'une LED de liaison. Chaque type d'appareil a la couleur d'un câble réseau : ambre pour le routeur, bleu pour les serveurs, vert pour les postes, blanc pour les imprimantes, gris pour le reste. Le rouge ne veut dire qu'une chose : un port sensible est ouvert. Si les animations sont désactivées dans Windows (Paramètres > Accessibilité > Effets visuels), la scène reste immobile.

L'application utilise Tkinter, fourni avec Python sous Windows et macOS (sous Linux : `sudo apt install python3-tk`).

## En ligne de commande (Windows, Linux, macOS)

Depuis le dossier `App-Scan` :

```bash
python -m netinv gui --lang fr                         # l'application
python -m netinv scan 192.168.1.0/24 --lang fr         # tableau dans la console
python -m netinv scan -p 22,80,443,8006 -o rapports/inventaire.csv
python -m netinv scan --help
```

## Tests

```bash
python -m unittest
```

Ils ne touchent pas au réseau : plages d'adresses, ports, lecture de la table ARP, exports, traductions et types d'appareils de la vue 3D.

## Fonctionnement

- **Détection** : `ping` système et connexion TCP sur quelques ports courants (une connexion refusée prouve aussi que l'appareil est là).
- **Ports** : simple connexion TCP, pas de paquets bruts, donc pas besoin d'être admin.
- **MAC et fabricant** : lus dans la table ARP du système, puis comparés à `netinv/data/oui.txt`. Visibles uniquement pour les appareils du même sous-réseau.
- **Noms** : DNS inverse.

## ⚠️ Usage responsable

N'utilise cet outil que sur des réseaux qui t'appartiennent ou que tu es autorisé à scanner.

## Licence

[MIT](LICENSE) © Malo Le Foll
