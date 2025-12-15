# Deployment ohjeet

## Esivalmistelut

### 1. Päivitä Caddy-proxy

```bash
cd ~/ha-proxy

# Päivitä Caddyfile
cat << 'EOF' > Caddyfile
# Redirect main domain to subdomain
ketunmetsa.fi {
    redir https://ha.ketunmetsa.fi{uri} permanent
}

# Home Assistant on subdomain
ha.ketunmetsa.fi {
    reverse_proxy ruuvidatacollector:8123
}

# Temperature control dashboard
temp.ketunmetsa.fi {
    reverse_proxy ha-temperature-web:5000
}
EOF

# Päivitä docker-compose.yml lisäämään network
cat << 'EOF' > docker-compose.yml
services:
  caddy:
    image: caddy:latest
    container_name: caddy-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped
    networks:
      - proxy

networks:
  proxy:
    name: caddy-proxy
    external: false

volumes:
  caddy_data:
  caddy_config:
EOF

# Käynnistä Caddy uudelleen
docker compose down
docker compose up -d
```

### 2. Asenna temperature controller

```bash
cd ~/omat/ha_rest_api/ha-api-test

# Varmista että .env on paikallaan
ls -la .env

# Rakenna ja käynnistä palvelut
docker compose build
docker compose up -d

# Tarkista lokit
docker compose logs -f
```

### 3. Tarkista että palvelut toimivat

```bash
# Tarkista että containerit pyörivät
docker ps | grep ha-temperature

# Tarkista scheduler-lokit
docker logs ha-temperature-controller --tail 50

# Tarkista web-lokit
docker logs ha-temperature-web --tail 50

# Testaa paikallisesti (palvelimella)
curl -s http://localhost:5000/api/status | jq .

# Testaa ulkoa
curl -s https://temp.ketunmetsa.fi/api/status | jq .
```

## Subdomainin DNS-asetus

Lisää DNS-tietue (esim. Cloudflare tai domain rekisteröijässä):

```
Type: A
Name: temp
Value: <palvelimen-ip>
Proxy: Ei (Caddy hoitaa HTTPS)
```

Tai jos käytät CNAME:

```
Type: CNAME
Name: temp
Value: ketunmetsa.fi
```

## Päivitys

```bash
cd ~/omat/ha_rest_api/ha-api-test

# Hae uusimmat muutokset
git pull

# Rakenna ja käynnistä uudelleen
docker compose build
docker compose restart
```

## Vianetsintä

### Web-palvelin ei vastaa

```bash
# Tarkista että container pyörii
docker ps | grep ha-temperature-web

# Tarkista lokit
docker logs ha-temperature-web

# Tarkista network
docker network inspect caddy-proxy

# Käynnistä uudelleen
docker compose restart web-dashboard
```

### Caddy ei löydä palvelua

```bash
# Tarkista että molemmat ovat samassa networkissa
docker inspect ha-temperature-web | grep -A 10 Networks
docker inspect caddy-proxy | grep -A 10 Networks

# Tarkista Caddy-lokit
docker logs caddy-proxy

# Reload Caddy config
docker exec caddy-proxy caddy reload --config /etc/caddy/Caddyfile
```

### Scheduler ei toimi

```bash
# Tarkista lokit
docker logs ha-temperature-controller --tail 100

# Testaa HA-yhteyttä containerista
docker exec ha-temperature-controller uv run python -c "import requests; import os; from dotenv import load_dotenv; load_dotenv(); print(requests.get(os.getenv('HA_URL') + '/api/').json())"
```
