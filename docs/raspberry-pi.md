# TicketBot on a Raspberry Pi

This guide runs TicketBot 24/7 on a Raspberry Pi 5 (4 GB or more) with Docker: the bot,
the web dashboard reachable from the internet through a Cloudflare Tunnel (no ports
opened on the router), automatic backups and, if you want, Prometheus and Grafana.
The same steps work on any Linux server or a PC with Docker.

## 1. The system

1. With [Raspberry Pi Imager](https://www.raspberrypi.com/software/) write
   **Raspberry Pi OS Lite (64-bit)** to the SD card or SSD. In the settings (the gear
   icon) choose a hostname (e.g. `ticketbot`), your user and password, enable **SSH**
   (best with your public key) and, if needed, the Wi-Fi.
2. Start the Pi and connect from your PC: `ssh <user>@ticketbot.local`
3. Update it:

   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

## 2. Docker

The official script installs Docker Engine and the Compose plugin:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
exit
```

Connect again (`ssh <user>@ticketbot.local`) and check: `docker compose version`.

## 3. TicketBot

```bash
sudo apt install -y git
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
git checkout v3.0.0
```

`git checkout` chooses the version: the latest one is on the
[releases page](https://github.com/TexAlphaWolf/ticketbot/releases).

## 4. Settings and data

**Moving from a PC** where TicketBot already runs: stop the bot there first (a Discord
bot token works in one place at a time), then copy `.env` and the `data` folder. From
the PC (PowerShell or a terminal, in the TicketBot folder):

```bash
scp .env <user>@ticketbot.local:~/ticketbot/
scp -r data <user>@ticketbot.local:~/ticketbot/
```

The `ENCRYPTION_KEY` in `.env` must stay the same: without it the encrypted data can't
be read.

**Starting from zero**: `cp .env.example .env`, then fill it in (`nano .env`): at least
`DISCORD_TOKEN` and `ENCRYPTION_KEY` (make one with
`docker compose run --rm ticketbot python -m ticketbot keygen`).

The containers run as the user with ID 1000 (the first user of Raspberry Pi OS); if
yours is different: `sudo chown -R 1000:1000 data`.

## 5. Start

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

`pull` downloads the image built on GitHub for the Pi (arm64), so nothing is compiled
on the Pi. The bot creates or updates the database, then the dashboard starts
(`ticketbot-web`, on `http://127.0.0.1:8080` of the Pi). `Ctrl+C` leaves the logs; the
containers keep running and start again by themselves after a reboot.

To see the settings as the bot reads them:
`docker compose exec ticketbot python -m ticketbot settings`

## 6. The dashboard on the internet (Cloudflare Tunnel)

You need a domain managed by Cloudflare (bought from
[Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) or moved there:
both free of extra costs). The tunnel is an outgoing connection from the Pi to
Cloudflare: no port is opened on the router and your home IP address stays hidden.

1. In the [Cloudflare dashboard](https://dash.cloudflare.com) open **Zero Trust →
   Networks → Tunnels → Create a tunnel**, type **Cloudflared**, name it `ticketbot`.
2. Copy the **token** shown in the install command (the long text after
   `--token`); you don't need to run that command.
3. Add a **public hostname**: subdomain `ticket`, your domain, service type **HTTP**,
   URL `web:8080`.
4. In `.env` on the Pi:

   ```bash
   TUNNEL_TOKEN=the-token-of-step-2
   WEB_PUBLIC_URL=https://ticket.example.com
   WEB_API_DOCS=false
   COMPOSE_PROFILES=tunnel
   ```

   `COMPOSE_PROFILES` starts the tunnel with every `docker compose up -d` (with
   Prometheus and Grafana too: `COMPOSE_PROFILES=tunnel,monitoring`).
5. In the [Discord Developer Portal](https://discord.com/developers/applications), the
   bot's application → **OAuth2 → Redirects**, add
   `https://ticket.example.com/api/v1/auth/callback` (the line `OAuth2 redirect` of
   the settings shows it).
6. `docker compose up -d` and open `https://ticket.example.com`.

With an `https://` address the dashboard uses secure cookies (`__Host-`) and HSTS, and
sees the visitors' real IP addresses through the tunnel.

## 7. Backups

The bot saves a compressed copy of the database every day in `data/backups` (the last
7). Keep a copy outside the Pi too, e.g. on your PC:

```bash
scp -r <user>@ticketbot.local:~/ticketbot/data/backups ./ticketbot-backups
```

and, with `.env`, in a safe place: the backups are useless without the
`ENCRYPTION_KEY`. With PostgreSQL (`--profile postgres`) use
`docker compose exec postgres pg_dump -U ticketbot ticketbot > ticketbot.sql`.

## 8. Updates

```bash
cd ~/ticketbot
git fetch --tags
git checkout v3.0.1
docker compose pull
docker compose up -d
```

The bot makes a backup before changing the database. Read the
[changelog](../CHANGELOG.md) of the new version first.

## 9. Monitoring

With `METRICS_TOKEN` and `GRAFANA_PASSWORD` in `.env` and the `monitoring` profile
(`COMPOSE_PROFILES=tunnel,monitoring`), Prometheus and Grafana run on the Pi, reachable
only from the Pi itself. From your PC, through SSH:

```bash
ssh -L 3000:127.0.0.1:3000 <user>@ticketbot.local
```

then open `http://127.0.0.1:3000` (user `admin`): the **TicketBot** dashboard is ready.

## Problems

- `docker compose logs ticketbot` / `web` / `tunnel`: the logs of one container
- The dashboard says the bot is offline, or `ticketbot_bot_up` is 0: the bot container
  stopped (`docker compose ps`)
- Login fails with a redirect error: the redirect of step 6.5 must be exactly the
  `OAuth2 redirect` of the settings
- `permission denied` on `data`: `sudo chown -R 1000:1000 data`
