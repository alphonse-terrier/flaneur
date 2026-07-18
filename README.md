# idfm-mcp

Serveur **MCP** (Model Context Protocol) pour le calcul d'itinéraires en **transports
en commun d'Île-de-France**, avec **étude des impacts travaux / incidents**, basé sur
l'**API PRIM** d'Île-de-France Mobilités.

À partir d'une adresse de départ et d'une adresse d'arrivée, le serveur géocode les
lieux, calcule les meilleurs itinéraires en temps réel et remonte les perturbations
affectant chaque étape du trajet.

## Fonctionnalités (outils MCP)

| Outil | Description |
|---|---|
| `geocode_address(query)` | Convertit une adresse ou un nom de lieu en coordonnées. |
| `plan_journey(origin, destination, when?, arrive_by?, max_journeys?)` | Itinéraire(s) complet(s) en temps réel, avec les perturbations rattachées à chaque étape. |
| `line_traffic(line?)` | Info trafic (travaux/incidents) : globale ou pour une ligne donnée. |
| `next_departures(stop, limit?)` | Prochains passages temps réel à un arrêt. |

`origin` / `destination` acceptent une **adresse** (« 29 rue de Rivoli, Paris »), un
**nom d'arrêt** (« Châtelet ») ou des **coordonnées** `longitude;latitude`.

## Architecture

```
src/idfm_mcp/
├── config.py        # Configuration (PRIM_API_KEY, URLs, timeouts)
├── prim_client.py   # Client httpx partagé (header apikey, gestion d'erreurs)
├── geocoding.py     # Adresse → coordonnées (BAN/Géoplateforme + Navitia /places)
├── journeys.py      # /journeys + résumé enrichi des perturbations
├── disruptions.py   # Info trafic (disruptions_bulk / line_reports)
├── departures.py    # Prochains passages (SIRI stop-monitoring)
├── models.py        # Modèles Pydantic des sorties
└── server.py        # Serveur FastMCP + enregistrement des outils
```

Sources de données :
- **Navitia** via PRIM (`/journeys`, `/places`, `/line_reports`, `disruptions_bulk`) —
  header `apikey`.
- **SIRI Lite** via PRIM (`stop-monitoring`) — header `apikey`.
- **Géocodeur national** (Base Adresse Nationale via Géoplateforme) — sans clé.

## Prérequis

- Python ≥ 3.10.
- Une **clé API PRIM** gratuite : créez un compte sur
  <https://prim.iledefrance-mobilites.fr>, puis générez un jeton sous
  *Mon compte → Mes jetons d'authentification*.

## Installation & lancement local

```bash
# 1. Dépendances (avec uv, recommandé)
uv sync
# ... ou avec pip
pip install -e ".[dev]"

# 2. Configuration
cp .env.example .env
# éditez .env et renseignez PRIM_API_KEY

# 3. Lancement (transport HTTP, écoute sur http://localhost:8000/mcp)
python -m idfm_mcp.server
```

### Test avec l'inspecteur MCP

```bash
# Interface web pour appeler les outils manuellement
uv run mcp dev src/idfm_mcp/server.py
# ou
npx @modelcontextprotocol/inspector
```

Exemples d'appels :
- `geocode_address("29 rue de Rivoli, Paris")`
- `plan_journey("Tour Eiffel, Paris", "Château de Vincennes")`
- `line_traffic("14")` puis `line_traffic()`
- `next_departures("Châtelet")`

## Déploiement sur Render

Le dépôt contient un blueprint `render.yaml`. Sur Render :

1. **New → Blueprint**, pointez sur ce dépôt.
2. Render crée un *web service* Python qui lance `python -m idfm_mcp.server`
   (écoute sur `0.0.0.0:$PORT`).
3. Dans **Environment**, ajoutez le secret `PRIM_API_KEY`.
4. Une fois déployé, l'endpoint MCP est exposé sur `https://<app>.onrender.com/mcp`.

### Brancher un client MCP

Exemple de configuration client (serveur distant HTTP) :

```json
{
  "mcpServers": {
    "idfm": {
      "url": "https://<app>.onrender.com/mcp"
    }
  }
}
```

## Tests

```bash
uv run pytest        # tests unitaires (parsing, sans appel réseau réel)
```

## Licence

MIT.
