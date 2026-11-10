---
name: docker-troubleshooting
description: Debug Docker containers and Docker Compose setups and write correct Dockerfiles and compose files. Use when a container exits, restarts, cannot be reached, cannot reach another service, loses data, or when the user asks for a Dockerfile or docker-compose.yml.
---

# Docker troubleshooting

## Look before changing

Ask for, or run:

```
docker ps -a                          # status and exit codes of all containers
docker logs --tail 100 NAME           # why it stopped
docker inspect NAME --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'
docker compose ps
docker compose logs --tail 100 SERVICE
docker compose config                 # the file as Docker understands it, with variables filled in
```

## By symptom

**Container exits at once**
- Read `docker logs`. The error is usually the last lines.
- Exit 0: the main process finished. A container lives only as long as its foreground process.
- Exit 1 or 2: the application failed; often a missing environment variable or config file.
- Exit 126 or 127: the command is not executable or not found. Check the path, the file's execute bit, and Windows line endings in the entrypoint script.
- Exit 137: killed, usually out of memory (`OOMKilled` is true). Exit 139: segfault.
- To look inside: `docker run --rm -it --entrypoint sh IMAGE`.

**Cannot reach the service from the host**
- Is the port published? `docker ps` must show `0.0.0.0:8080->80/tcp`. `ports: "HOST:CONTAINER"`.
- The application must listen on `0.0.0.0` inside the container, not `127.0.0.1`.

**Containers cannot reach each other**
- In Compose, use the service name as the host name and the container's port: `http://db:5432`, not `localhost` and not the published host port.
- `localhost` inside a container is that container itself. To reach the host, use `host.docker.internal` (on Linux add `extra_hosts: ["host.docker.internal:host-gateway"]`).
- They must share a network. `depends_on` only orders the start; it does not wait until the service is ready. Use a healthcheck with `condition: service_healthy`.

**Data is gone after recreating**
- Anything not in a volume is lost with the container. Mount a named volume at the path where the application stores data.
- `docker compose down -v` deletes named volumes. Warn before suggesting it.

**Permission denied on a mounted folder**
- The user id inside the container differs from the owner of the host folder. Match them with `user: "1000:1000"` or fix the ownership of the host folder. Do not use `chmod 777`.

**Changes do not show up**
- An image was built before the change: `docker compose up -d --build`. A changed compose file or `.env` needs `docker compose up -d` again; `restart` does not reread it.

**Disk full**
- `docker system df` shows what uses the space. `docker image prune` and `docker builder prune` are safe. `docker system prune --volumes` deletes data; say so.

## Writing a Dockerfile

- Pin the base image to a version (`python:3.12-slim`), not `latest`.
- Copy the dependency list and install before copying the source, so the layer cache survives code changes.
- One process per container, started in exec form: `CMD ["python", "app.py"]`.
- Run as a non-root user. Add a `.dockerignore` (`.git`, `node_modules`, `.env`).
- No secrets in the image or in `ENV`; pass them at run time.

## Writing a compose file

- Named volumes for data, `restart: unless-stopped`, a healthcheck for databases, secrets in `.env` (kept out of git).
- Publish only the ports that must be reachable from outside. Bind admin ports to `127.0.0.1:`.

## Answer format

What the evidence shows, the cause, the exact change (as a diff of the compose file or Dockerfile when relevant), the command to apply it, and how to check that it worked. Flag every command that deletes data.
