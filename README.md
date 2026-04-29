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
- fichiers ASGI/WSGI présents pour un futur déploiement ;
- application métier `reservations` créée avec les modèles principaux.

## Stack technique

- Python 3
- Django 5.2.12
- SQLite en développement
- HTML/CSS/JavaScript pour l'interface à venir
- Intégration possible d'une solution de paiement en ligne selon le besoin du projet

## Structure actuelle

```text
TogoPlus/
├── .git/
├── .gitignore
├── README.md
├── manage.py
├── db.sqlite3
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── reservations/
    ├── __init__.py
    ├── admin.py
    ├── apps.py
    ├── models.py
    ├── tests.py
    └── migrations/
        └── __init__.py
```

Cette organisation suit une structure Django classique :

- `manage.py` est le point d'entrée des commandes Django ;
- `config/` contient la configuration globale du projet ;
- `reservations/` contient le code métier de l'application de réservation ;
- `.gitignore` évite de versionner les fichiers générés localement comme `db.sqlite3`, les environnements virtuels et les caches Python.

Le dépôt Git est placé à la racine du projet, au même niveau que `manage.py`, afin de suivre tout le projet Django.

## Rôle du dossier `config`

Le dossier `config/` est normal dans un projet Django. Il ne doit pas contenir la logique métier, mais uniquement la configuration globale :

- `settings.py` configure Django, les applications installées, la base de données, la sécurité et les fichiers statiques ;
- `urls.py` déclare les routes principales du projet ;
- `asgi.py` sert de point d'entrée pour un déploiement ASGI ;
- `wsgi.py` sert de point d'entrée pour un déploiement WSGI.

Les fonctionnalités de réservation restent dans l'application `reservations/`.

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

Créer une nouvelle application Django :

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

- conserver la racine Git au niveau du dossier `TogoPlus/` pour inclure `manage.py`, `config/`, les applications métier et le README principal ;
- ajouter un fichier `requirements.txt` ou `pyproject.toml` pour figer les dépendances ;
- utiliser des variables d'environnement pour `SECRET_KEY`, `DEBUG` et les paramètres sensibles ;
- séparer les paramètres de développement et de production avant tout déploiement ;
- écrire des tests sur la logique de disponibilité, car c'est le cœur fonctionnel du projet ;
- éviter de versionner `db.sqlite3` en production ou dans un dépôt partagé.

## Roadmap

1. Créer l'application `reservations`. Fait.
2. Définir les modèles métier : ressources, disponibilités, réservations. Fait.
3. Connecter les modèles à l'administration Django. Fait.
4. Ajouter les vues et templates pour consulter et réserver.
5. Implémenter les formulaires de création de réservation.
6. Ajouter les tests unitaires complets sur les règles de réservation.
7. Préparer l'extension paiement en ligne.

## Auteur

Projet réalisé dans le cadre du module Django - M1 AI & Big Data.
