# Contributing to Homescreen Hero

Thanks for wanting to contribute! Whether it's a bug report, a feature idea, or a code change — it's all welcome.

## Ways to Contribute

- **Report bugs** — Something broken? Open an [issue](https://github.com/trentferguson/homescreen-hero/issues)
- **Suggest features** — Got an idea? Open an issue or start a discussion on [Discord](https://discord.gg/yQ8pJzURsr)
- **Submit a PR** — Bug fixes, new features, docs improvements, test coverage — all welcome
- **Help others** — Answer questions on Discord or in GitHub issues

## Submitting a Pull Request

You don't need to open an issue first — feel free to just send a PR. That said, for larger features it's a good idea to discuss the approach first (via an issue or Discord) so we're on the same page before you invest a bunch of time.

### Branch Naming

- Features: `feature-your-feature-name`
- Bug fixes: `fix-your-fix-name`
- All PRs should target the `develop` branch

### What Makes a Good PR

- **Keep it focused.** One PR per feature or fix. Smaller PRs are easier to review and merge.
- **Include tests** when possible, especially for bug fixes (prove it's fixed) and new features.
- **Run the existing tests** before submitting to make sure nothing is broken.

### PR Title/Description Formatting

Use this structure for your PR title and description:

**Title:** `{Type}: {Brief descriptive title}`

Where type is one of:
- `Feature:` — New functionality
- `Fix:` — Bug fixes
- `Hotfix:` — Urgent production fixes
- `Refactor:` — Code restructuring without behavior changes
- `Chore:` — Maintenance, dependencies, config

**Description:**

```markdown
## Copy PR Title Here (e.g. Fix: Solved World Hunger, Brokered Peace in the Middle East)

### Summary
A few sentences explaining what this PR does and why. Write like you're
explaining it to a teammate.

### Major Changes
- Notable changes that reviewers should pay attention to
- New features, significant modifications, anything that changes behavior

### Minor Changes
- Small stuff — tweaks, cleanup, minor fixes that came along for the ride

### Notes (optional)
Only include if there's something special: database migrations, breaking
changes, deployment considerations, etc.
```

A few tips:
- Keep it scannable — reviewers should get the gist in 30 seconds
- Don't pad it out — short PRs can have short descriptions
- Skip the Notes section if there's nothing special to call out

### AI-Generated Code

AI-assisted contributions are welcome! Just mention it in your PR description (e.g., "Used Copilot/Claude/ChatGPT for X"). This helps during review since AI-generated code sometimes needs a closer look for edge cases.

## Reporting Bugs

When filing a bug report, include:

- **What happened** vs. what you expected
- **Steps to reproduce** the issue
- **Your environment** — Docker or local install, OS, browser
- **Logs** if available (check `data/logs/` or `docker-compose logs`)
- **Config** (sanitized) — your `config.yaml` setup can help narrow things down

## Local Development Setup

### Prerequisites

- **Frontend:** Node.js (v18+) and npm
- **Backend:** Python (v3.9+) and pip
- Docker and Docker Compose (optional)

### Project Structure

```
homescreen-hero/
├── homescreen-hero-ui/     # React frontend (TypeScript, Vite, Tailwind)
│   ├── src/                # Components, hooks, pages
│   ├── package.json
│   └── vite.config.ts
├── homescreen_hero/        # Python backend (FastAPI)
│   ├── core/               # Business logic, config, integrations
│   ├── web/                # API routers and app entry point
│   ├── tests/              # Backend tests
│   └── requirements.txt
├── data/                   # Runtime data (config, DB, logs)
├── docker-compose.yml
└── example.config.yaml
```

### 1. Clone and Configure

```bash
git clone https://github.com/trentferguson/homescreen-hero.git
cd homescreen-hero

# Copy example config
cp example.config.yaml config.yaml
# Edit config.yaml with your Plex details
```

### 2. Backend

```bash
cd homescreen_hero

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run dev server
uvicorn homescreen_hero.web.app:app --reload --port 8000
```

The API will be at `http://localhost:8000` with Swagger docs at `http://localhost:8000/docs`.

### 3. Frontend

```bash
cd homescreen-hero-ui

# Install dependencies
npm install

# Run dev server
npm run dev
```

The frontend will be at `http://localhost:5173`.

### 4. Docker (Alternative)

```bash
docker-compose up -d --build
docker-compose logs -f
```

## Running Tests

Always run tests before submitting a PR.

**Backend:**
```bash
cd homescreen_hero
pytest
pytest --cov=homescreen_hero --cov-report=html  # With coverage
```

**Frontend:**
```bash
cd homescreen-hero-ui
npm run test:run      # Single run
npm test              # Watch mode
```

## Code Style

### Python
- Type hints preferred
- Pydantic models for request/response schemas
- Prefer `#` comments over docstrings — keep code readable through good naming

### TypeScript / React
- Functional components with hooks
- Tailwind CSS for styling
- Headless UI for accessible components
- Lucide React for icons

## Questions?

Open an [issue](https://github.com/trentferguson/homescreen-hero/issues) or join the [Discord](https://discord.gg/yQ8pJzURsr)!
