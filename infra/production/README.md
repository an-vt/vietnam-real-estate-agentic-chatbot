# Production deployment

This deployment runs the frontend build, Nginx, and backend on one EC2
instance with Docker Compose. PostgreSQL runs on Amazon RDS; it is not included
in Compose.

## EC2 setup

Clone the repository on the EC2 instance and install Docker Engine, the Docker
Compose plugin, and Git. The EC2 security group should allow HTTP ports 80 and
443 from Cloudflare's published IP ranges and SSH only from an administrator
IP. The RDS security
group should allow PostgreSQL port 5432 only from the EC2 security group.

Create the application directory and pull the source:

```bash
git clone <github-repository-url> /opt/vietnam-real-estate
cd /opt/vietnam-real-estate
git pull
```

Create the production configuration:

```bash
cd /opt/vietnam-real-estate/infra/production
cp .env.example .env
${EDITOR:-vi} .env
```

Create the Docker secret files. Do not commit these files:

```bash
install -m 600 /dev/null secrets/postgres_password
install -m 600 /dev/null secrets/llm_api_key
${EDITOR:-vi} secrets/postgres_password
${EDITOR:-vi} secrets/llm_api_key
```

Create the Cloudflare Origin CA certificate files before starting the
production stack. The certificate must cover `speakaway.app` and
`www.speakaway.app`; keep both files private and do not commit them:

```bash
mkdir -p secrets/origin
install -m 644 /path/to/origin.crt secrets/origin/origin.crt
install -m 600 /path/to/origin.key secrets/origin/origin.key
```

The RDS database must support the `vector` extension. The first migration
creates the schema and extension, and the second creates the HNSW index.

## Start the application

```bash
cd /opt/vietnam-real-estate/infra/production
make up
make logs
```

The frontend build service writes static files to a named Docker volume. The
separate Nginx service serves that volume, publishes ports 80 and 443, redirects
HTTP to HTTPS, and proxies `/api` to the private backend container. Frontend,
backend, and Nginx share the explicit Docker network
`vietnam-real-estate-chatbot-net`; the backend is not published directly on the
EC2 host.

## Import listings

Copy the CSV to the EC2 path configured by `CSV_PATH`, then run:

```bash
make ingest
```

The importer deduplicates by listing ID, keeps the newest scrape, includes
price in the embedding text, uses token-aware batches, and resumes safely.
Use `make ingest FORCE=1` only when all embeddings must be regenerated.

For a small test import, limit physical CSV rows:

```bash
make ingest MAX_RECORDS=10
```

If `MAX_RECORDS` is omitted, the importer reads the full CSV. Rows are still
deduplicated by listing ID before upsert, so duplicate or invalid rows can make
the number of database records smaller than the raw-row limit.

## Update the application

```bash
cd /opt/vietnam-real-estate
git pull
cd infra/production
make up
```
