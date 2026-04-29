# Togo+

**Togo+** est une application web Django de réservation de services ou de salles, conçue pour gérer des créneaux disponibles, des demandes de réservation et, à terme, le paiement en ligne.

Le nom public du projet est **Togo+**. Le nom technique recommandé pour les dossiers, dépôts ou identifiants est **TogoPlus**.

## Contexte du projet

Ce projet correspond au sujet académique **Application de réservation - Groupe P**.

Objectif principal :

- permettre à un utilisateur de consulter des services ou des salles réservables ;
- vérifier la disponibilité d'un créneau selon une date, une heure de début et une heure de fin ;
- enregistrer une réservation sans conflit de planning ;
- préparer une extension de paiement en ligne pour confirmer ou sécuriser les réservations.

## État actuel

Le projet contient actuellement le socle Django généré avec `django-admin startproject`.

Fonctionnel à ce stade :

- configuration Django principale dans `config/settings.py` ;
- routage principal dans `config/urls.py` ;
- interface d'administration Django disponible sur `/admin/` ;
- base de données SQLite configurée en développement ;
- fichiers ASGI/WSGI présents pour un futur déploiement.

Les applications métier de réservation restent à créer.

## Stack technique

- Python 3
- Django 5.2.12
- SQLite en développement
- HTML/CSS/JavaScript pour l'interface à venir
- Intégration possible d'une solution de paiement en ligne selon le besoin du projet

## Structure actuelle

```text
TogoPlus/
├── manage.py
├── db.sqlite3
└── config/
    ├── __init__.py
    ├── asgi.py
    ├── settings.py
    ├── urls.py
    ├── wsgi.py
    └── README.md
```

> Note : le dépôt Git est actuellement initialisé dans le dossier `config/`, tandis que le fichier `manage.py` se trouve dans le dossier parent du projet. Les commandes Django doivent donc être lancées depuis le dossier racine `TogoPlus/`.

## Installation locale

Depuis le dossier `TogoPlus/` :

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install Django
```

Appliquer les migrations :

```bash
python manage.py migrate
```

Créer un administrateur :

```bash
python manage.py createsuperuser
```

Lancer le serveur de développement :

```bash
python manage.py runserver
```

L'application sera accessible à l'adresse :

```text
http://127.0.0.1:8000/
```

L'administration Django sera accessible à l'adresse :

```text
http://127.0.0.1:8000/admin/
```

## Fonctionnalités prévues

### Gestion des comptes

- inscription et connexion des utilisateurs ;
- distinction possible entre administrateurs, gestionnaires et clients ;
- consultation de l'historique des réservations.

### Gestion des ressources réservables

- création de salles, services ou espaces réservables ;
- description, capacité, prix éventuel et statut de disponibilité ;
- administration des ressources depuis le back-office Django.

### Gestion des disponibilités

- définition des jours et horaires d'ouverture ;
- blocage de créneaux indisponibles ;
- vérification automatique des conflits entre réservations ;
- affichage des créneaux libres.

### Gestion des réservations

- choix d'une ressource ;
- sélection d'une date et d'un créneau horaire ;
- validation de la disponibilité avant enregistrement ;
- statut de réservation : en attente, confirmée, annulée ou terminée ;
- notification ou récapitulatif de réservation.

### Paiement en ligne

Extension possible :

- paiement obligatoire ou optionnel lors de la réservation ;
- confirmation automatique après paiement réussi ;
- conservation d'un statut de paiement ;
- intégration future avec un fournisseur comme Stripe, PayPal ou une solution mobile money selon les contraintes du projet.

## Modèle métier envisagé

Une première version peut s'appuyer sur les entités suivantes :

- `Resource` : salle, service ou espace réservable ;
- `Availability` : plage horaire disponible pour une ressource ;
- `Reservation` : réservation effectuée par un utilisateur ;
- `Payment` : paiement lié à une réservation, si l'extension paiement est activée.

Règle centrale :

```text
Une ressource ne peut pas avoir deux réservations confirmées qui se chevauchent sur le même créneau.
```

## Commandes utiles

Créer une application Django :

```bash
python manage.py startapp reservations
```

Créer les migrations après modification des modèles :

```bash
python manage.py makemigrations
python manage.py migrate
```

Lancer les tests :

```bash
python manage.py test
```

Vérifier la configuration du projet :

```bash
python manage.py check
```

## Bonnes pratiques recommandées

- déplacer la racine Git au niveau du dossier `TogoPlus/` pour inclure `manage.py`, les futures apps et le README principal ;
- ajouter un fichier `requirements.txt` ou `pyproject.toml` pour figer les dépendances ;
- utiliser des variables d'environnement pour `SECRET_KEY`, `DEBUG` et les paramètres sensibles ;
- séparer les paramètres de développement et de production avant tout déploiement ;
- écrire des tests sur la logique de disponibilité, car c'est le cœur fonctionnel du projet ;
- éviter de versionner `db.sqlite3` en production ou dans un dépôt partagé.

## Roadmap

1. Créer l'application `reservations`.
2. Définir les modèles métier : ressources, disponibilités, réservations.
3. Ajouter les vues et templates pour consulter et réserver.
4. Implémenter la validation anti-chevauchement des créneaux.
5. Connecter les modèles à l'administration Django.
6. Ajouter les tests unitaires sur les règles de réservation.
7. Préparer l'extension paiement en ligne.

## Auteur

Projet réalisé dans le cadre du module Django - M1 AI & Big Data.
