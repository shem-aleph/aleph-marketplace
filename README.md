# Aleph Cloud Marketplace

One-click deployment of applications on decentralized infrastructure.

## Vision

An app store for Aleph Cloud - browse pre-configured applications and deploy them to your own instance with one click.

## Features

### For Users
- 🛒 Browse application catalog
- 🚀 One-click deployment to Aleph Cloud
- 💳 Pay-as-you-go with credits
- 📊 Monitor running instances
- 🔧 Manage deployments (start, stop, configure)

### For Developers
- 📦 Submit your apps to the marketplace
- 📝 Define deployment templates
- 💰 (Future) Monetization options

## App Categories

- **Web Apps**: WordPress, Ghost, Strapi, etc.
- **Databases**: PostgreSQL, Redis, MongoDB
- **Dev Tools**: GitLab, Gitea, code-server
- **AI/ML**: Ollama, LocalAI, Stable Diffusion
- **Monitoring**: Grafana, Prometheus
- **Communication**: Matrix, Mattermost

## Tech Stack

- **Frontend**: React + Vite (or vanilla for simplicity)
- **Backend**: FastAPI
- **Auth**: Ethereum wallet (Web3)
- **Deployment**: aleph-sdk-python
- **Hosting**: Aleph Cloud (dogfooding!)

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Backend API   │────▶│  Aleph Cloud    │
│   (React)       │     │   (FastAPI)     │     │   Network       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       ▼
        │               ┌─────────────────┐
        └──────────────▶│  App Templates  │
                        │   (JSON/YAML)   │
                        └─────────────────┘
```

## Getting Started

```bash
# Install dependencies
pip install -r requirements.txt

# Run the backend
uvicorn main:app --reload

# Access at http://localhost:8000
```

## Author

Built by Shem for Aleph Cloud
