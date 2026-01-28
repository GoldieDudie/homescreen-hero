<div align="center">
<img width="40%" height="40%" alt="homescreen-hero_logo_cropped_wide_again" src="https://github.com/user-attachments/assets/892ea966-cf31-4a2e-8494-c92afe08ad49" />

[![Typing SVG](https://readme-typing-svg.herokuapp.com?font=Oxanium&size=36&pause=1000&color=F3B358&background=FFFFFF00&center=true&repeat=false&width=435&lines=homescreen-hero)](https://git.io/typing-svg)

**A self-hosted Plex companion app with homescreen management, server insights, and useful tools, all in a sleek web dashboard**

![Static Badge](https://img.shields.io/badge/Plex-%20Built%20for%20Plex-e5a00d?style=flat&logo=Plex)
[![](https://dcbadge.limes.pink/api/server/https://discord.gg/yQ8pJzURsr?theme=default-inverted&style=flat&compact=true)](https://discord.gg/yQ8pJzURsr) ![Static Badge](https://img.shields.io/badge/Claude-vibecoded(ish)-%23D97757?style=flat&logo=Claude) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![GitHub Release](https://img.shields.io/github/v/release/trentferguson/homescreen-hero?logo=GitHub&color=%2327B63F)

## **[Try the Live Demo!](https://demo.homescreenhero.com)**
*Note: The demo does not currently have the widget/dashboard drag-n-drop feature implemented (**yet!**)*

</div>

## A Quick Heads Up

This app is very much a WORK IN PROGRESS. This started as a simple Python script to rotate my Plex homescreen, and slowly turned in to much, much more. I still have a lot of really cool things planned in the coming weeks, so stay tuned!

**Important Note:** portions of this app is vibe-coded (especially the frontend). As a Data Engineer who originally went to school to become a full-stack developer, a big part of creating this app for myself was to get a true understanding of where AI Coding Agents stand today, and what exactly they can/cannot do. I got tired of the headlines/Reddit comments and figured this was the quickest way to the truth.

## Features

- **Web Dashboard:** Manage your Plex Server, curate your homescreen(s), and get useful analytics & insights all in one place!
- **Automated Collection Rotation:** Schedule collections to rotate on your Plex home screen to constantly keep things fresh for all your users.
- **First-Time Setup Wizard:** Get started in minutes without touching config files
- **3rd Party List Integrations:** Grow your library with curated lists from your favorite websites! Create/Sync collections from Trakt, Letterboxd, and MDBLists
- **Widgets for your favorite apps:** Add widgets to your dashboard from popular self-hosted apps (Tautulli, Seerr, more to come!)
- **Useful Tools (WIP):** Collection of tools, scripts and utilites for managing your Plex server (checkout the Tools section below)

## See It In Action!

### Dashboard & Widget System
<details>
<summary><strong>Quick video demo of the homescreen-hero dashboard and widgets system</strong></summary>

<video src="https://github.com/user-attachments/assets/74216471-acb2-4a67-812e-c2c640bede66" autoplay muted loop playsinline width="100%"></video>

</details>

### Screenshots
<details>
<summary><strong>Check out screenshots of the homescreen-hero UI</strong></summary>

<table>
  <tr>
    <td align="center"><strong>Dashboard</strong></td>
    <td align="center"><strong>Groups Page</strong></td>
  </tr>
  <tr>
    <td><img width="600" alt="Dashboard" src="https://github.com/user-attachments/assets/b3b5ee09-522f-4a10-ae44-4aee56969bdc" /></td>
    <td><img width="600" alt="Groups Page" src="https://github.com/user-attachments/assets/10c1a547-9f4d-486e-b917-25ff2adb408a" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Group Details</strong></td>
    <td align="center"><strong>Group Collections</strong></td>
  </tr>
  <tr>
    <td><img width="600" alt="Group Details" src="https://github.com/user-attachments/assets/afad4b44-8c47-4e66-baeb-cdf7c12ee15e" /></td>
    <td><img width="600" alt="Group Collections" src="https://github.com/user-attachments/assets/831e5a3a-67bc-47b6-b2da-c54d3bfa94f9" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Collections Page</strong></td>
    <td align="center"><strong>Integrations Page</strong></td>
  </tr>
  <tr>
    <td align="center"><img width="600" alt="Collections Page" src="https://github.com/user-attachments/assets/50eb68ee-d24b-4591-9191-e8d49c36bc1a" /></td>
    <td aligh="center"><img width="600" alt="Integrations Page" src="https://github.com/user-attachments/assets/f44fb950-c8f0-4654-bd23-85e86db2d5ef" /></td>
  </tr>
   <tr>
    <td align="center" colspan="2"><strong>Tools Page</strong></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img width="600" alt="Tools Page" src="https://github.com/user-attachments/assets/e083f377-ebdc-4b4e-9db9-b6e582e0a84e" /></td>
  </tr>
</table>

</details>

## Quick Start

**Prerequisites:** [Docker](https://docs.docker.com/engine/install/), a running [Plex server](https://www.plex.tv/media-server-downloads/), and your [Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

> **Security tip:** Want to keep secrets out of config files? Copy `.env.example` to `.env` and fill in your sensitive values *before* running the wizard. The wizard will automatically use your environment variables instead of writing them to config.yaml.

```bash
git clone https://github.com/trentferguson/homescreen-hero.git
cd homescreen-hero
mkdir -p data
docker-compose up -d
Open http://localhost:8000 and the Setup Wizard will guide you through configuration.
```

## Environment Variables

Store sensitive values in a `.env` file (copy from `.env.example`). These override any values in `config.yaml`.

| Variable | Description | Required |
|----------|-----------------|:-----------:|
| `HSH_PORT` | Port you want homescreen-hero to run on (default: 8000) | Yes |
| `HSH_PLEX_URL` | Your Plex server URL (e.g., `http://192.168.1.100:32400`) | Yes |
| `HSH_PLEX_TOKEN` | Your Plex authentication token ([how to find](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)) | Yes |
| `HSH_AUTH_PASSWORD` | Password for web UI login | If auth enabled |
| `HSH_AUTH_SECRET_KEY` | JWT secret (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`) | If auth enabled |
| `HSH_TRAKT_CLIENT_ID` | [Get from Trakt](https://trakt.tv/oauth/applications) | If Trakt enabled |
| `HSH_MDBLIST_API_KEY` | [Get from MDBList](https://mdblist.com/preferences/) | If MDBList enabled |
| `HSH_TAUTULLI_API_KEY` | Found in Tautulli Settings → Web Interface → API | If Tautulli enabled |
| `HSH_TAUTULLI_BASE_URL` | Defaults to `http://localhost:8181` | No |
| `HSH_SEERR_API_KEY` | Found in Seerr Settings → General | If Seerr enabled |
| `HSH_SEERR_BASE_URL` | Defaults to `http://localhost:5055` | No |

<details>
<summary><strong>Internal/Docker paths</strong></summary>

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMESCREEN_HERO_CONFIG` | `/data/config.yaml` | Path to config file |
| `HOMESCREEN_HERO_DB` | `sqlite:////data/homescreen_hero.sqlite` | Database path |
| `HOMESCREEN_HERO_LOG_DIR` | `/data/logs` | Log directory |

</details>

## Configuration

Settings are stored in `data/config.yaml`. See [example.config.yaml](example.config.yaml) for a full template.

**Key sections:**
- **plex** – Server URL, token, and libraries to manage
- **rotation** – Interval, max collections, and strategy (`random`, `weighted`, or `lru`)
- **groups** – Named pools of collections with min/max picks and weights
- **trakt/mdblist** – Third-party list sync configuration

<details>
<summary><strong>Rotation Strategies</strong></summary>

| Strategy | Description |
|----------|-------------|
| `random` | Groups processed in config order, collections selected randomly |
| `weighted` | Groups processed by weight (highest first), collections selected randomly |
| `lru` | Least recently used collections selected first for fair rotation |

All strategies respect `min_gap_rotations` to prevent collections from appearing too frequently.

</details>

## Tools & Utilities

As this app as grown, so has the scope of tools and utilities I envision adding. Here you can find a list of current tools implemented on the Tools page, and a general overview of what they do. Do you have a Plex tool that you'd like to see added? I love adding requested features, so just open an issue here on Github, or ping me on our Discord server!

<details>
<summary><strong>Date Added Editor</strong></summary>

Fix the "Date Added" timestamp on movies and shows that were redownloaded to your library. Choose from a custom date, 30 days ago, or match the media's original release date.
</details>

<details>
<summary><strong>Watch History Cleaner</strong></summary>

Mark TV shows as unwatched to fix issues with Plex's "Continue Watching" row. Useful when shows disappear from Continue Watching or you want to start a fresh rewatch.
</details>

<details>
<summary><strong>Unwatched Report</strong></summary>

Find content that's collecting dust in your library. Search for items that have never been watched or haven't been watched within a specified time period (30 days, 90 days, 6 months, etc.). Requires Tautulli integration. Export results to CSV for library cleanup decisions.
</details>

## Docker Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `v0.3.1`, `v0.4.0`, etc. | Specific versions for pinned deployments |
| `nightly` | Automated builds from `develop` branch (unstable) |

```bash
docker pull trentferguson/homescreen-hero:latest
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

This project is licensed under the [MIT License](LICENSE) - see the [LICENSE](LICENSE) file for details. All contributions to this project are welcomed! 

## 🙏 Acknowledgments

-   [**Agregarr:**](https://github.com/agregarr/agregarr) For being an amazing self-hosted app and inspiring me to try building something myself. Seriously, this app is awesome.
-   [**ColleXions:**](https://github.com/jl94x4/ColleXions) For initially doing exactly what I needed this app today. Another great inspiration for me to try my own hand at an creating something like this.
-   **Stitch (Google):** For helping me come up with a clean frontend design philosophy. It took a lot of trial error (I have almost no frontend dev experience, but turns out I'm very picky about what it looks like lol)
-   **Claude Code, Chat GPT, and Github Copilot:** For building ~90% of my frontend. As a Data Engineer, a big part of creating this app for myself was to get a true understanding of where AI Coding Agents stand today, and what exactly they can/cannot do. I got tired of the headlines/Reddit comments and figured this was the quickest way to the truth.

## 🐶 Puppy Tax 
I'm not ashamed to use my cutie for free internet points! (she was also great moral support on the *"I've been banging my head against a wall for days trying to figure out why the rotation runs every thirty seconds lol*)

<img width="25%" height="25%" alt="IMG_3015" src="https://github.com/user-attachments/assets/e24b34da-b541-4ead-b822-98ec31b5154e" />
<img width="25%" height="25%" alt="IMG_1225" src="https://github.com/user-attachments/assets/a4b6ad17-063b-4068-ac2d-91ec60f117f2" />
<img width="25%" height="25%" alt="IMG_3017" src="https://github.com/user-attachments/assets/300e1e92-ea19-4dc0-8dfc-8a17413725c6" />

---

<div align="center">

Made with ❤️, 💧, and ☕ by [trentferguson](https://github.com/trentferguson)

</div>
